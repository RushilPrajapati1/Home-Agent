"""guides-mcp tools. Names and parameters exactly as on the design's APIs page."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from homefund_contracts.domain import Citation
from homefund_contracts.types import ContractModel

SERVER = "guides-mcp"


# search_guides(query, k=5) -> hybrid search, reranked, with citations
class SearchGuidesInput(ContractModel):
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=20)


class GuideHit(ContractModel):
    chunk_id: UUID
    parent_id: UUID | None
    content: str
    score: float = Field(description="Reranker score; not money, so float is fine")
    citation: Citation


class SearchGuidesOutput(ContractModel):
    hits: list[GuideHit]


# define_term(term) -> glossary entry for PMI, escrow, DTI and more
class DefineTermInput(ContractModel):
    term: str = Field(min_length=1)


class DefineTermOutput(ContractModel):
    term: str
    found: bool
    definition: str | None = None
    citation: Citation | None = None


# get_section(chunk_id) -> parent section for full context
class GetSectionInput(ContractModel):
    chunk_id: UUID


class GetSectionOutput(ContractModel):
    section_id: UUID = Field(description="The parent chunk's id")
    title: str
    content: str
    citation: Citation
