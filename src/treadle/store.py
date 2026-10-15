"""Local-filesystem store, atomic publication, attestations and cooperative leases."""

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


class StoreError(RuntimeError):
    """A store operation was refused or an attested file changed."""


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, name):
    """Reject traversal and symlinks, including symlinks that stay inside root."""
    root = Path(root)
    relative = Path(name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise StoreError(f"file must be inside call directory: {name}")
    current = root
    if root.is_symlink():
        raise StoreError(f"symlink is not allowed: {root}")
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise StoreError(f"symlink is not allowed: {current}")
    return current


def read_bytes(path):
    """Do not follow a final symlink, and accept only ordinary files."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise StoreError(f"not a regular file: {path}")
        return file.read()


def read_json(path):
    return json.loads(read_bytes(path))


def atomic_write(path, data, *, replace=False):
    """Publish a complete file; default is write-once, even across processes."""
    path = Path(path)
    if isinstance(data, str):
        data = data.encode()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        if replace:
            os.replace(tmp, path)
        else:
            try:
                os.link(tmp, path)
            except FileExistsError:
                return False
        return True
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock(self, *, step=False):
        """Steps are serial; worker transactions use a separate blocking lock."""
        path = self.path / (".step.lock" if step else ".lock")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if step else 0))
            except BlockingIOError as exc:
                raise StoreError("another step or use_store run is active; run steps serially") from exc
            yield
        finally:
            os.close(fd)

    def directory(self, key, *, create=False):
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise StoreError(f"invalid call key: {key!r}")
        directory = safe_path(self.path, key)
        if create:
            directory.mkdir(exist_ok=True)
        return directory

    def resolve(self, prefix):
        if not re.fullmatch(r"[0-9a-f]{1,64}", prefix):
            raise StoreError(f"invalid key prefix: {prefix!r}")
        hits = [
            p.name
            for p in self.path.iterdir()
            if p.name.startswith(prefix) and re.fullmatch(r"[0-9a-f]{64}", p.name)
        ]
        if len(hits) != 1:
            raise StoreError(f"key prefix {prefix!r} matches {len(hits)} calls")
        directory = self.directory(hits[0])
        read_json(safe_path(directory, "call.json"))
        return directory

    def committed(self, directory):
        manifest = safe_path(directory, "commit.json")
        if not manifest.exists():
            return None
        commit = read_json(manifest)
        files = {}
        for name, expected in commit["files"].items():
            path = safe_path(directory, name)
            try:
                data = read_bytes(path)
            except FileNotFoundError as exc:
                raise StoreError(f"committed file missing: {path}") from exc
            if digest(data) != expected:
                raise StoreError(f"committed file hash mismatch: {path}")
            files[name] = data
        if commit.get("answer") not in files:
            raise StoreError(f"commit has no attested answer: {manifest}")
        return files, commit["answer"]

    def publish_open(self, records):
        with self.lock():
            atomic_write(self.path / "open.json", json_text(records), replace=True)

    def open_keys(self):
        path = safe_path(self.path, "open.json")
        return {record["key"] for record in read_json(path)} if path.exists() else set()

    def live_claim(self, directory):
        path = safe_path(directory, "claim.json")
        if path.exists():
            claim = read_json(path)
            if claim["expires_at"] > time.time():
                return claim
        return None

    def _agent(self, directory):
        call = read_json(safe_path(directory, "call.json"))
        if call["kind"] != "agent":
            raise StoreError("cached operations are recorded by the workflow, not by workers")
        if safe_path(directory, "commit.json").exists():
            raise StoreError(f"call {directory.name} is already committed")
        return call

    def claim(self, prefix, worker, lease):
        if not worker or not math.isfinite(lease) or lease <= 0:
            raise StoreError("claim requires a nonempty worker and a positive finite lease")
        with self.lock():
            keys = self.open_keys()
            if prefix is None:
                directories = [self.directory(key) for key in sorted(keys)]
                directories = [
                    d
                    for d in directories
                    if not safe_path(d, "commit.json").exists() and not self.live_claim(d)
                ]
                if not directories:
                    raise StoreError("no unclaimed open call; next: run treadle step")
                directory = directories[0]
            else:
                directory = self.resolve(prefix)
            self._agent(directory)
            if directory.name not in keys:
                raise StoreError("call is not in the latest open set")
            claim = self.live_claim(directory)
            if claim and claim["worker"] != worker:
                raise StoreError(f"call is claimed by {claim['worker']}")
            now = time.time()
            claim = {"worker": worker, "claimed_at": now, "expires_at": now + lease}
            atomic_write(directory / "claim.json", json_text(claim), replace=True)
            return directory.name, claim

    def release(self, prefix, worker):
        with self.lock():
            directory = self.resolve(prefix)
            self._agent(directory)
            claim = self.live_claim(directory)
            if not claim or claim["worker"] != worker:
                raise StoreError("release requires the live claim holder")
            (directory / "claim.json").unlink()
            return directory.name

    def attest(self, directory, answer, names=(), worker=None):
        """Caller holds the worker lock. No schema validation beyond a JSON object."""
        files = {}
        for name in dict.fromkeys([answer, *names]):
            path = safe_path(directory, name)
            if Path(name).parts[0] in {"call.json", "prompt.md", "commit.json", "claim.json"}:
                raise StoreError(f"cannot attest store metadata: {name}")
            files[str(Path(name))] = digest(read_bytes(path))
        commit = {"worker": worker, "committed_at": time.time(), "answer": answer, "files": files}
        if not atomic_write(directory / "commit.json", json_text(commit)):
            raise StoreError(f"call {directory.name} is already committed")
        claim = safe_path(directory, "claim.json")
        if claim.exists():
            claim.unlink()
        return commit

    def commit(self, prefix, names=(), worker=None):
        with self.lock():
            directory = self.resolve(prefix)
            call = self._agent(directory)
            claim = self.live_claim(directory)
            if claim and claim["worker"] != worker:
                raise StoreError(f"call is claimed by {claim['worker']}")
            present = [
                name
                for name in ("answer.md", "answer.json", "failure.md")
                if safe_path(directory, name).exists()
            ]
            expected = "answer.json" if call["typed"] else "answer.md"
            if len(present) != 1 or present[0] not in (expected, "failure.md"):
                raise StoreError(f"write exactly one of {expected} or failure.md (no other answer file)")
            answer = present[0]
            if answer == "answer.json":
                try:
                    value = json.loads(read_bytes(directory / answer), parse_constant=_bad_constant)
                except (ValueError, UnicodeError) as exc:
                    raise StoreError("typed answer must be one JSON object") from exc
                if not isinstance(value, dict):
                    raise StoreError("typed answer must be one JSON object")
            return directory.name, self.attest(directory, answer, names, worker)


def _bad_constant(value):
    raise ValueError(f"not a JSON constant: {value}")
