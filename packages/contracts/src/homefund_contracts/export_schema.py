"""Export JSON Schema for the API and SSE models to web/src/api/schema/.

uv run homefund-export-schema            # write
uv run homefund-export-schema --check    # fail if the committed files are stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from homefund_contracts import api, events

API_MODELS: tuple[type[BaseModel], ...] = (
    api.CreateImportForm,
    api.CreateImportResponse,
    api.ImportResponse,
    api.CreatePlanRequest,
    api.CreatePlanResponse,
    api.ReviewRequest,
    api.ReviewResponse,
    api.AnswerRequest,
    api.AnswerResponse,
    api.PlanResponse,
    api.ErrorResponse,
)

DEFAULT_OUT = Path("web/src/api/schema")


def _api_schema() -> dict[str, Any]:
    pairs = [(model, "serialization") for model in API_MODELS]
    _, schema = models_json_schema(pairs, title="Home Fund API")  # type: ignore[arg-type]
    return schema


def _events_schema() -> dict[str, Any]:
    schema = events.PlanEventAdapter.json_schema(mode="serialization")
    schema["title"] = "Home Fund plan events (SSE)"
    return schema


def render() -> dict[str, str]:
    return {
        "api.schema.json": json.dumps(_api_schema(), indent=2, sort_keys=True) + "\n",
        "events.schema.json": json.dumps(_events_schema(), indent=2, sort_keys=True) + "\n",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="exit 1 if files are out of date")
    args = parser.parse_args(argv)

    stale: list[str] = []
    for name, text in render().items():
        path: Path = args.out / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path}")
    if stale:
        print("stale schema, run `make schema`: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
