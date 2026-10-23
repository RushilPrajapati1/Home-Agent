"""HOUSING_USE_MOCKS=true: answer FRED and RentCast from fixtures/mocks, never the network.

The mock sits under SafeClient as its transport, so the allowlist still applies.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

FIXTURES = {
    ("api.stlouisfed.org", "/fred/series/observations"): "fred_mortgage30us.json",
    ("api.rentcast.io", "/v1/properties"): "rentcast_property.json",
    ("api.rentcast.io", "/v1/avm/value"): "rentcast_value.json",
}


def fixture_transport(mocks_dir: Path) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        name = FIXTURES.get((request.url.host, request.url.path))
        if name is None:
            return httpx.Response(404, json={"error": "no fixture"})
        return httpx.Response(200, json=json.loads((mocks_dir / name).read_text()))

    return httpx.MockTransport(handler)
