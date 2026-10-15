"""The agent catalog shared by both runners: name, description, output type.

In Pydantic AI each entry becomes an `Agent(name=..., description=..., output_type=...)`.
In the bl step runner each entry becomes a prompt header and the schema an answer is validated against.
"""

from dataclasses import dataclass

from pydantic import BaseModel


class Verdict(BaseModel):
    accepted: bool
    problems: list[str] = []


@dataclass(frozen=True)
class CatalogAgent:
    name: str
    description: str
    output_type: type[BaseModel] | None = None  # None: the answer is a string


CATALOG = [
    CatalogAgent("writer", "Writes or rewrites one paragraph as instructed. Returns the paragraph only."),
    CatalogAgent("reviewer", "Reviews a paragraph. Accepts it or lists concrete problems.", Verdict),
    CatalogAgent("summarizer", "Summarizes several paragraphs in two sentences."),
]
