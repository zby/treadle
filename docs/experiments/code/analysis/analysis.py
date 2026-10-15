# Code-base analysis, steps 2-9. Portable script: Monty subset, agents called as `await name(task=...)`.
# Inputs (top-level names supplied by the runner):
#   system, checkout_path, source_commit, method_commit : str  (step 1, acquisition, happened outside)
#   source_files : list[str]  tracked files of the frozen checkout, so the boundary check needs no file access
# Result: {"outcome": "accepted"|"problem"|"blocked"|"out-of-scope", ...}; publication happens outside.
import asyncio

ROLES = ["runtime", "memory", "epistemic", "workflow"]
ANALYSTS = {
    "runtime": runtime_analyst,
    "memory": memory_analyst,
    "epistemic": epistemic_analyst,
    "workflow": workflow_analyst,
}
MAX_ROUNDS = 3
CHECK_ATTEMPTS = 3
CTX = (
    f"System: {system}\nFrozen checkout: {checkout_path} at commit {source_commit}\n"
    f"Method files: commit {method_commit} (read them directly)\n"
)


# ---- deterministic checks: pure code, no files ----


def inside_source(path):
    p = path.rstrip("/")
    if p == "" or p.startswith("/") or ".." in p.split("/"):
        return False
    return p in source_files or any([f.startswith(p + "/") for f in source_files])


def inside_boundary(path: str, boundary: Boundary) -> bool:
    p = path.rstrip("/")
    return any([p == b.rstrip("/") or p.startswith(b.rstrip("/") + "/") for b in boundary["paths"]])


def check_boundary(b: Boundary) -> list[str]:
    problems = []
    if b["statement"].strip() == "" or len(b["paths"]) == 0:
        problems.append("boundary needs a statement and at least one path")
    problems += [f"path outside the frozen source: {p}" for p in b["paths"] if not inside_source(p)]
    return problems


def check_report(r: Report, boundary: Boundary) -> list[str]:
    problems = []
    if len(r["report"].strip()) < 200:
        problems.append("report is empty or too short")
    if r["answers"].strip() == "":
        problems.append("answers file is empty (write 'no requests yet' if there are none)")
    if len(r["cited_paths"]) == 0:
        problems.append("report cites no evidence paths")
    problems += [f"cited path outside the boundary: {p}" for p in r["cited_paths"] if not inside_boundary(p, boundary)]
    return problems


def check_profile(p: Profile, boundary: Boundary) -> list[str]:
    problems = []
    if p["profile"].strip() == "":
        problems.append("profile is empty")
    problems += [f"cited path outside the boundary: {c}" for c in p["cited_paths"] if not inside_boundary(c, boundary)]
    return problems


def check_reconciliation(r: Reconciliation) -> list[str]:
    problems = []
    for c in r["conflicts"]:
        if c["report_a"] not in ROLES or c["report_b"] not in ROLES or c["report_a"] == c["report_b"]:
            problems.append(f"conflict must cite two different reports from {ROLES}")
        if c["prevented_conclusion"].strip() == "":
            problems.append("conflict names no prevented conclusion")
    return problems


def structural_check(boundary, reports, reconciliation):
    """Findings are {"target", "message"}; a target that is a role needs an explicit request."""
    findings = []
    for role in ROLES:
        m = reports[role]
        if m["refused"]:
            findings.append({"target": role, "message": f"{role} report was refused: {m['value']['reason']}"})
            continue
        for p in check_report(m["value"], boundary):
            findings.append({"target": role, "message": p})
    if reconciliation["refused"]:
        findings.append({"target": "reconciliation", "message": "reconciliation was refused"})
    else:
        findings += [{"target": "reconciliation", "message": p} for p in check_reconciliation(reconciliation["value"])]
    return findings


def check_verdict(v: Verdict, findings: list[dict[str, str]], targets: list[str]) -> list[str]:
    problems = []
    if v["accepted"] and (len(v["requests"]) > 0 or v["problem"]):
        problems.append("an accepted verdict must have no requests and no problem")
    if v["problem"] and v["accepted"]:
        problems.append("a problem verdict must not be accepted")
    if not v["accepted"] and not v["problem"] and len(v["requests"]) == 0:
        problems.append("a rejection needs a request to a named target, or a problem")
    asked = [r["target"] for r in v["requests"]]
    problems += [f"request to unknown target {t}" for t in asked if t not in targets]
    for f in findings:
        if f["target"] in targets and f["target"] not in asked and not v["problem"]:
            problems.append(f"structural failure needs an explicit request to {f['target']}: {f['message']}")
    return problems


# ---- one job with the check-and-re-ask loop; a refusal is a result, not a failure ----


def failure_text(failures):
    if len(failures) == 0:
        return ""
    return "\nEarlier attempts were rejected by deterministic checks:\n" + "\n".join(
        [f"Attempt {i + 1}: " + "; ".join(f) for i, f in enumerate(failures)]
    )


async def job(label, call, make_task, check, limit):
    failures = []
    for attempt in range(1, limit + 1):
        out = await call(task=make_task(failure_text(failures)))
        if out["kind"] == "refusal":
            return {"attempt": attempt, "refused": True, "value": out}
        problems = check(out)
        if len(problems) == 0:
            return {"attempt": attempt, "refused": False, "value": out}
        failures = failures + [problems]
    raise RuntimeError(f"{label}: out of attempts after {limit}: {failures[-1]}")


def show(m):
    if m["refused"]:
        return "REFUSED. Reason: " + m["value"]["reason"]
    v = m["value"]
    return "\n".join(
        [f"{k.upper()}:\n{v[k]}" for k in ["report", "answers", "profile", "synthesis", "text", "statement"] if k in v]
    ) + "\nCITED: " + ", ".join(v.get("cited_paths", v.get("paths", [])))


def show_reports(reports):
    return "\n\n".join([f"=== {role} report ===\n{show(reports[role])}" for role in ROLES])


def show_findings(findings):
    return "\n".join([f"- [{f['target']}] {f['message']}" for f in findings]) or "none"


# ---- steps ----


async def analyst_job(role, boundary, request, previous):
    def make_task(fail):
        if previous is None:
            what = f"Write the {role} report and its answers file."
        else:
            what = (
                f"Correct your {role} report. Reply to the request in the answers file.\n"
                f"Request: {request}\n\nYour current report:\n{show(previous)}"
            )
        return f"{what}\n{CTX}Boundary: {boundary['value']['statement']}\nPaths: {boundary['value']['paths']}{fail}"

    return await job(f"{role} report", ANALYSTS[role], make_task, lambda r: check_report(r, boundary["value"]), CHECK_ATTEMPTS)


async def verify_reports(boundary, reports, reconciliation, findings):
    def make_task(fail):
        return (
            f"Verify the reports. Accept, or address a correction request to a named report "
            f"({ROLES}); every structural failure needs an explicit request. If the reports cannot support any "
            f"bounded conclusion, return a problem instead.\n{CTX}"
            f"Boundary:\n{show(boundary)}\n\n{show_reports(reports)}\n\n"
            f"=== reconciliation ===\n{show(reconciliation)}\n\nStructural findings:\n{show_findings(findings)}{fail}"
        )

    return await job("report verification", report_verifier, make_task, lambda v: check_verdict(v, findings, ROLES), CHECK_ATTEMPTS)


def verdict_feedback(who, v):
    return f"{who} did not accept: " + "; ".join([r["request"] for r in v["requests"]]) + (v["problem"] or "")


async def verified_profile(boundary, reports, verdict):
    feedback = ""
    for attempt in range(1, CHECK_ATTEMPTS + 1):
        mapped = await job(
            "memory profile",
            profile_mapper,
            lambda fail: f"Build the memory profile from the accepted reports.\n{CTX}{show_reports(reports)}\n\nVerdict: {verdict}{feedback}{fail}",
            lambda p: check_profile(p, boundary["value"]),
            CHECK_ATTEMPTS,
        )
        if mapped["refused"]:
            return {"profile": mapped, "outcome": "blocked", "reason": "profile refused"}
        shown = show(mapped)
        v1 = await report_verifier(
            task=f"Verify this memory profile against the reports (target: profile).\n{CTX}{show_reports(reports)}\n\nProfile:\n{shown}"
        )
        if v1["kind"] == "refusal":
            return {"profile": mapped, "outcome": "blocked", "reason": "profile verification refused"}
        if v1["problem"]:
            return {"profile": mapped, "outcome": "problem", "reason": v1["problem"]}
        v2 = None
        if v1["accepted"]:
            v2 = await profile_verifier(
                task=f"Independently verify this memory profile.\n{CTX}{show_reports(reports)}\n\nProfile:\n{shown}\n\nReport verifier said: {v1}"
            )
            if v2["kind"] == "refusal":
                return {"profile": mapped, "outcome": "blocked", "reason": "profile verification refused"}
            if v2["problem"]:
                return {"profile": mapped, "outcome": "problem", "reason": v2["problem"]}
            if v2["accepted"]:
                return {"profile": mapped, "outcome": "accepted", "verdicts": [v1, v2]}
        feedback = "\n" + verdict_feedback("report verifier", v1) if v2 is None else "\n" + verdict_feedback("profile verifier", v2)
    raise RuntimeError("memory profile: out of verification attempts")


async def verified_synthesis(boundary, reports, profile, verdict):
    feedback = ""
    for attempt in range(1, 3):
        out = await job(
            "synthesis",
            synthesizer,
            lambda fail: f"Write the synthesis.\n{CTX}{show_reports(reports)}\n\nProfile:\n{show(profile)}\n\nVerdict: {verdict}{feedback}{fail}",
            lambda s: [] if s["synthesis"].strip() else ["synthesis is empty"],
            CHECK_ATTEMPTS,
        )
        if out["refused"]:
            return {"synthesis": out, "outcome": "blocked", "reason": "synthesis refused"}
        base = f"{CTX}{show_reports(reports)}\n\nProfile:\n{show(profile)}\n\nSynthesis:\n{show(out)}"
        verdicts = []
        rejected = ""
        for name, call in [("report verifier", report_verifier), ("profile verifier", profile_verifier), ("synthesis verifier", synthesis_verifier)]:
            v = await call(task=f"Verify this synthesis as the {name} (target: synthesis).\n{base}\n\nEarlier verdicts: {verdicts}")
            if v["kind"] == "refusal":
                return {"synthesis": out, "outcome": "blocked", "reason": f"{name} refused"}
            if v["problem"]:
                return {"synthesis": out, "outcome": "problem", "reason": v["problem"]}
            verdicts.append(v)
            if not v["accepted"]:
                rejected = verdict_feedback(name, v)
                break
        if rejected == "":
            return {"synthesis": out, "outcome": "accepted", "verdicts": verdicts}
        feedback = "\nThe previous synthesis was rejected. " + rejected
    raise RuntimeError("synthesis: out of attempts after 2")


def member(name, m, version=0):
    return {"name": name, "attempt": m["attempt"], "version": version, "refused": m["refused"]}


# ---- the workflow ----

boundary = await job(
    "boundary",
    boundary_declarer,
    lambda fail: f"Declare what the analysis covers in the frozen source.\n{CTX}{fail}",
    check_boundary,
    2,
)
if boundary["refused"]:
    result = {"outcome": "out-of-scope", "reason": boundary["value"]["reason"]}
else:
    # The runtime report must exist first; the other three do not read it, so it is not in their prompts.
    reports = {"runtime": await analyst_job("runtime", boundary, None, None)}
    rest = await asyncio.gather(*[analyst_job(r, boundary, None, None) for r in ROLES[1:]])
    for i, role in enumerate(ROLES[1:]):
        reports[role] = rest[i]
    versions = {role: 0 for role in ROLES}

    result = None
    for round in range(1, MAX_ROUNDS + 1):
        reconciliation = await job(
            "reconciliation",
            reconciler,
            lambda fail: f"Record conflicts between the reports, citing both findings and the conclusion they prevent.\n{CTX}{show_reports(reports)}{fail}",
            check_reconciliation,
            CHECK_ATTEMPTS,
        )
        findings = structural_check(boundary["value"], reports, reconciliation)
        vm = await verify_reports(boundary, reports, reconciliation, findings)
        if vm["refused"]:
            result = {"outcome": "blocked", "reason": "report verifier refused: " + vm["value"]["reason"]}
            break
        verdict = vm["value"]
        if verdict["problem"]:
            result = {"outcome": "problem", "detail": verdict["problem"], "round": round, "verdict": verdict}
            break
        if len(verdict["requests"]) == 0:
            break
        asked = [r["target"] for r in verdict["requests"]]
        fixed = await asyncio.gather(
            *[analyst_job(r["target"], boundary, r["request"], reports[r["target"]]) for r in verdict["requests"]]
        )
        for i, t in enumerate(asked):
            reports[t] = fixed[i]
            versions[t] += 1
    else:
        raise RuntimeError(f"report verification did not converge in {MAX_ROUNDS} rounds")

    if result is None:
        prof = await verified_profile(boundary, reports, verdict)
        if prof["outcome"] != "accepted":
            result = {"outcome": prof["outcome"], "reason": prof["reason"]}
        else:
            syn = await verified_synthesis(boundary, reports, prof["profile"], verdict)
            if syn["outcome"] != "accepted":
                result = {"outcome": syn["outcome"], "reason": syn["reason"]}
            else:
                # Assemble: overview and manifest. Publication is outside the script.
                members = {"boundary": boundary, "reconciliation": reconciliation, "profile": prof["profile"], "synthesis": syn["synthesis"]}
                for role in ROLES:
                    members[role] = reports[role]
                manifest = [member(n, m, versions.get(n, 0)) for n, m in members.items()]
                overview = f"# {system} at {source_commit}\n\n" + show(syn["synthesis"])
                result = {
                    "outcome": "accepted",
                    "overview": overview,
                    "manifest": manifest,
                    "members": {n: m["value"] for n, m in members.items()},
                    "verdict": verdict,
                    "verifications": {"profile": prof["verdicts"], "synthesis": syn["verdicts"]},
                }
result
