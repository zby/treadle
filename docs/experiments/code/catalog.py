"""The agent catalog shared by both runners: name, description, output type.

Pydantic AI turns each entry into an Agent. The step runner turns each into a prompt header
and validates answers against the output type. Scripts never import this file.
"""

from pydantic import BaseModel


class Verdict(BaseModel):
    ok: bool
    problems: list[str] = []


CATALOG = {
    "writer": {"description": "Writes or revises one paragraph.", "output": str},
    "checker": {"description": "Checks one paragraph; returns ok and a list of problems.", "output": Verdict},
}
