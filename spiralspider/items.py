"""What a source spider yields: a quest it lists, and the fields it gives for a quest."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Listed:
    source: str
    quest: str


@dataclass(frozen=True)
class Record:
    source: str
    quest: str
    fields: dict
    provenance: dict
