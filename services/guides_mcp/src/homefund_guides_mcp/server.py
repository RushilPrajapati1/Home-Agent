"""FastMCP server, streamable HTTP at /mcp. Tool names and parameters are the design's."""

from __future__ import annotations

import logging
import os
import uuid

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from homefund_contracts.clock import Clock, clock_from_env
from homefund_contracts.mcp.guides import (
    SERVER,
    DefineTermInput,
    DefineTermOutput,
    GetSectionInput,
    GetSectionOutput,
    SearchGuidesInput,
    SearchGuidesOutput,
)
from homefund_guides_mcp.chunks import Filters
from homefund_guides_mcp.service import GuidesService, SectionNotFound

INSTRUCTIONS = (
    "Home-buying guidance from CFPB and HUD, with citations. search_guides returns the most "
    "relevant guide sections (reranked) with a Citation each; define_term looks a term up "
    "in the glossary (PMI, MIP, escrow, DTI, LTV, PITI, closing costs, reserves, earnest "
    "money); get_section returns the full parent section of a chunk_id."
)


def default_filters(clock: Clock) -> Filters:
    """search_guides has no filter parameters (the design fixes its signature), so the server
    applies the current tax year: year-specific figures from other years are left out."""
    return Filters(tax_year=clock.today().year)


def build_server(service: GuidesService) -> FastMCP:
    mcp = FastMCP(SERVER, instructions=INSTRUCTIONS)

    @mcp.tool
    async def search_guides(query: str, k: int = 5) -> SearchGuidesOutput:
        """Hybrid (BGE-M3 dense + sparse) search over CFPB and HUD guides and the glossary,
        reranked with bge-reranker-v2-m3. Returns up to k parent sections with citations."""
        try:
            args = SearchGuidesInput(query=query, k=k)
        except ValidationError as e:
            raise ToolError(str(e)) from e
        return await service.search_guides(args.query, args.k)

    @mcp.tool
    async def define_term(term: str) -> DefineTermOutput:
        """Glossary definition of a home-buying term (exact, then fuzzy match), falling back
        to the best guide passage."""
        try:
            args = DefineTermInput(term=term)
        except ValidationError as e:
            raise ToolError(str(e)) from e
        return await service.define_term(args.term)

    @mcp.tool
    async def get_section(chunk_id: str) -> GetSectionOutput:
        """The full parent section that a chunk (e.g. a search hit's chunk_id) belongs to."""
        try:
            args = GetSectionInput(chunk_id=uuid.UUID(chunk_id))
            return await service.get_section(args.chunk_id)
        except (ValueError, ValidationError) as e:
            raise ToolError(f"chunk_id must be a UUID: {e}") from e
        except SectionNotFound as e:
            raise ToolError(str(e)) from e

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": SERVER})

    return mcp


def main() -> None:
    from homefund_embed.client import EmbedClient

    from homefund_guides_mcp.store import PgGuideStore

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    service = GuidesService(
        PgGuideStore.from_env(),
        EmbedClient(timeout=60.0),
        default_filters=default_filters(clock_from_env()),
    )
    build_server(service).run(
        transport="http",
        host=os.environ.get("GUIDES_MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("GUIDES_MCP_PORT", "8103")),
        path="/mcp",
    )


if __name__ == "__main__":
    main()
