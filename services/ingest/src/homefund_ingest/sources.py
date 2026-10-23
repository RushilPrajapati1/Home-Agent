"""sources.yaml: the list of official pages ingest reads, with when each was fetched."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from homefund_contracts.enums import GuideSource

SERVICE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SOURCES = SERVICE_DIR / "sources.yaml"
DEFAULT_DATA_DIR = SERVICE_DIR / "data" / "guides"

HEADER = """\
# Guides corpus for Home Fund. Official CFPB and HUD pages only; ingest fetches each once into
# data/guides/<id>.<format> and never needs the network again to re-chunk.
# `make ingest-fetch` downloads missing files and fills in fetched + sha256; edit the rest by hand.
#   source:   cfpb | hud | glossary (Citation.source). Glossary entries use `glossary`.
#   kind:     guide (heading-aware parent/child) | glossary (one term per chunk)
#   tax_year: set only when the figures are for one year (e.g. FHA loan limits); else null.
"""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TermSpan(_Model):
    """A glossary term cut from a document's text, from ``start`` through ``end``."""

    term: str
    aliases: list[str] = Field(default_factory=list)
    start: str
    end: str


class SourceDoc(_Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    source: GuideSource
    kind: Literal["guide", "glossary"]
    publisher: Literal["cfpb", "hud"]
    title: str
    url: str
    format: Literal["html", "pdf"] = "html"
    tax_year: int | None = None
    selector: str | None = Field(default=None, description="CSS selector of the content root")
    drop: list[str] = Field(default_factory=list, description="CSS selectors removed first")
    terms: list[TermSpan] = Field(
        default_factory=list, description="Glossary terms cut from this document's text"
    )
    aliases: dict[str, list[str]] = Field(
        default_factory=dict, description="Extra names for terms of a glossary page"
    )
    notes: str | None = None
    fetched: date | None = None
    sha256: str | None = None

    @property
    def filename(self) -> str:
        return f"{self.id}.{self.format}"


class Sources(_Model):
    drop_sections: list[str] = Field(
        default_factory=list, description="Headings whose whole section is site chrome"
    )
    documents: list[SourceDoc]


def load_sources(path: Path = DEFAULT_SOURCES) -> Sources:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources = Sources.model_validate(data)
    ids = [d.id for d in sources.documents]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate document ids in {path}")
    return sources


def save_sources(sources: Sources, path: Path = DEFAULT_SOURCES) -> None:
    data = sources.model_dump(mode="json", exclude_defaults=True)
    for doc in data["documents"]:
        doc.setdefault("tax_year", None)
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(HEADER + "\n" + body, encoding="utf-8")
