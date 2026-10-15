import asyncio
from typing import Any, TypedDict, NotRequired, Literal

system: str
checkout_path: str
source_commit: str
method_commit: str
source_files: list[str]


class Boundary(TypedDict):
    kind: Literal['boundary']
    statement: str
    paths: list[str]

class Refusal(TypedDict):
    kind: Literal['refusal']
    reason: str

class Report(TypedDict):
    kind: Literal['report']
    report: str
    answers: str
    cited_paths: list[str]

class Conflict(TypedDict):
    report_a: str
    finding_a: str
    report_b: str
    finding_b: str
    prevented_conclusion: str

class Reconciliation(TypedDict):
    kind: Literal['reconciliation']
    text: str
    conflicts: list[Conflict]

class Request(TypedDict):
    target: str
    request: str

class Verdict(TypedDict):
    kind: Literal['verdict']
    accepted: bool
    requests: list[Request]
    problem: str | None

class Profile(TypedDict):
    kind: Literal['profile']
    profile: str
    cited_paths: list[str]

class Synthesis(TypedDict):
    kind: Literal['synthesis']
    synthesis: str

async def boundary_declarer(*, task: str) -> Boundary | Refusal:
    raise NotImplementedError()

async def runtime_analyst(*, task: str) -> Report | Refusal:
    raise NotImplementedError()

async def memory_analyst(*, task: str) -> Report | Refusal:
    raise NotImplementedError()

async def epistemic_analyst(*, task: str) -> Report | Refusal:
    raise NotImplementedError()

async def workflow_analyst(*, task: str) -> Report | Refusal:
    raise NotImplementedError()

async def reconciler(*, task: str) -> Reconciliation | Refusal:
    raise NotImplementedError()

async def report_verifier(*, task: str) -> Verdict | Refusal:
    raise NotImplementedError()

async def profile_mapper(*, task: str) -> Profile | Refusal:
    raise NotImplementedError()

async def profile_verifier(*, task: str) -> Verdict | Refusal:
    raise NotImplementedError()

async def synthesizer(*, task: str) -> Synthesis | Refusal:
    raise NotImplementedError()

async def synthesis_verifier(*, task: str) -> Verdict | Refusal:
    raise NotImplementedError()