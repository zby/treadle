"""Agent catalog for the code-base analysis workflow (steps 2-9), in the style of shared/catalog.py.

Every typed agent may answer with a Refusal instead of its normal result, so output types are unions
`X | Refusal` discriminated by `kind` (a required Literal, so Monty's checker can narrow on it).
NOTE for runners: output_type here may be a union, not a single BaseModel; validate with
`pydantic.TypeAdapter(entry.output_type)`.
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel


class Refusal(BaseModel):
    kind: Literal["refusal"]
    reason: str


class Boundary(BaseModel):
    kind: Literal["boundary"]
    statement: str  # what the analysis covers and why
    paths: list[str]  # repo-relative files or directories, all inside the frozen source


class Report(BaseModel):
    kind: Literal["report"]
    report: str  # the report document
    answers: str  # the answers file: replies to correction requests so far
    cited_paths: list[str]  # repo-relative paths the report cites as evidence


class Conflict(BaseModel):
    report_a: str  # role
    finding_a: str
    report_b: str  # role
    finding_b: str
    prevented_conclusion: str


class Reconciliation(BaseModel):
    kind: Literal["reconciliation"]
    text: str
    conflicts: list[Conflict]


class Request(BaseModel):
    target: str  # a report role, "profile" or "synthesis"
    request: str


class Verdict(BaseModel):
    kind: Literal["verdict"]
    accepted: bool
    requests: list[Request]  # correction requests to named targets; empty when accepted
    problem: str | None  # set when no bounded conclusion is supportable; then accepted is false


class Profile(BaseModel):
    kind: Literal["profile"]
    profile: str
    cited_paths: list[str]


class Synthesis(BaseModel):
    kind: Literal["synthesis"]
    synthesis: str


@dataclass(frozen=True)
class CatalogAgent:
    name: str
    description: str
    output_type: Any = None  # a BaseModel, a union of BaseModels, or None (string answer)


def _analyst(role: str, focus: str) -> CatalogAgent:
    return CatalogAgent(
        f"{role}_analyst",
        f"Writes or corrects the {role} report of the analysis ({focus}) and its answers file, reading the "
        "frozen checkout and method files directly. May refuse with a reason.",
        Report | Refusal,
    )


CATALOG = [
    CatalogAgent(
        "boundary_declarer",
        "Declares what the analysis covers in the frozen source. May refuse (out of scope).",
        Boundary | Refusal,
    ),
    _analyst("runtime", "how the system runs"),
    _analyst("memory", "what it stores and recalls"),
    _analyst("epistemic", "what it knows and how it justifies it"),
    _analyst("workflow", "how work is sequenced and delegated"),
    CatalogAgent(
        "reconciler",
        "Records conflicts between the four reports, citing both findings and the conclusion they prevent.",
        Reconciliation | Refusal,
    ),
    CatalogAgent(
        "report_verifier",
        "Reads boundary, reports, reconciliation and structural findings. Never writes corrections: accepts, "
        "addresses a request to a named target, or returns a problem if no bounded conclusion is supportable.",
        Verdict | Refusal,
    ),
    CatalogAgent("profile_mapper", "Builds the memory profile from the accepted reports.", Profile | Refusal),
    CatalogAgent(
        "profile_verifier",
        "Independently verifies a memory profile (or a synthesis against the profile).",
        Verdict | Refusal,
    ),
    CatalogAgent("synthesizer", "Writes the synthesis from reports, verdict and profile.", Synthesis | Refusal),
    CatalogAgent(
        "synthesis_verifier",
        "Independently verifies a synthesis against everything it rests on.",
        Verdict | Refusal,
    ),
]
