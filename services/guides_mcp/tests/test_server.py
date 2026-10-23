"""The MCP surface: tool names and parameters exactly as the design, called in-memory."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

from fastmcp import Client
from homefund_guides_mcp.server import build_server, default_filters

from homefund_contracts.clock import FixedClock
from homefund_contracts.mcp import TOOLS
from homefund_contracts.mcp.guides import (
    SERVER,
    DefineTermOutput,
    GetSectionOutput,
    SearchGuidesOutput,
)


def run(coro):
    return asyncio.run(coro)


def test_tools_match_the_contract(service) -> None:
    async def go():
        async with Client(build_server(service)) as c:
            return await c.list_tools()

    tools = {t.name: t for t in run(go())}
    assert set(tools) == set(TOOLS[SERVER])
    assert set(tools["search_guides"].input_schema["properties"]) == {"query", "k"}
    assert tools["search_guides"].input_schema["properties"]["k"]["default"] == 5
    assert set(tools["define_term"].input_schema["properties"]) == {"term"}
    assert set(tools["get_section"].input_schema["properties"]) == {"chunk_id"}


def test_call_every_tool(service) -> None:
    async def go():
        async with Client(build_server(service)) as c:
            found = await c.call_tool("search_guides", {"query": "What is PMI?", "k": 2})
            out = SearchGuidesOutput.model_validate(found.structured_content)
            term = await c.call_tool("define_term", {"term": "escrow"})
            section = await c.call_tool("get_section", {"chunk_id": str(out.hits[1].chunk_id)})
            return (
                out,
                DefineTermOutput.model_validate(term.structured_content),
                GetSectionOutput.model_validate(section.structured_content),
            )

    search, term, section = run(go())
    assert len(search.hits) == 2 and search.hits[0].citation.section == "PMI"
    assert term.found and term.term == "Escrow"
    assert section.section_id == search.hits[1].parent_id


def test_bad_arguments_are_tool_errors(service) -> None:
    async def go():
        async with Client(build_server(service)) as c:
            return [
                await c.call_tool(
                    "search_guides", {"query": "What is PMI?", "k": 50}, raise_on_error=False
                ),
                await c.call_tool("search_guides", {"query": ""}, raise_on_error=False),
                await c.call_tool("get_section", {"chunk_id": "nope"}, raise_on_error=False),
                await c.call_tool(
                    "get_section", {"chunk_id": str(uuid.uuid4())}, raise_on_error=False
                ),
            ]

    results = run(go())
    assert all(r.is_error for r in results)
    assert "no guide chunk" in results[3].content[0].text


def test_default_filter_is_the_clock_tax_year() -> None:
    assert default_filters(FixedClock(date(2026, 10, 1))).tax_year == 2026
