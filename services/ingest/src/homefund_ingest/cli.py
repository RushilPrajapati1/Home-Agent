"""`make ingest`: fetch (only what is missing), chunk, embed, write guide_chunks.

    homefund-ingest fetch [--refresh] [--only ID,...]   download into data/guides/
    homefund-ingest chunk [--only ID,...]               offline dry run: chunk stats
    homefund-ingest run   [--only ID,...] [--no-prune]  chunk + embed + write (app_rw)

Settings from the environment: CONTEXT_HEADER=on|off (default on), CHUNK_TOKENS (500),
CHUNK_OVERLAP (50), PARENT_MAX_TOKENS (1500), EMBED_URL, DATABASE_URL_APP.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from homefund_contracts.clock import clock_from_env
from homefund_ingest.chunker import ChunkSettings
from homefund_ingest.fetch import fetch_all
from homefund_ingest.pipeline import Row, build_rows, extract
from homefund_ingest.sources import (
    DEFAULT_DATA_DIR,
    DEFAULT_SOURCES,
    SourceDoc,
    Sources,
    load_sources,
    save_sources,
)

log = logging.getLogger("homefund_ingest")


def settings_from_env(env: Mapping[str, str] | None = None) -> ChunkSettings:
    e = os.environ if env is None else env
    flag = e.get("CONTEXT_HEADER", "on").strip().lower()
    if flag not in {"on", "off", "true", "false", "1", "0"}:
        raise ValueError(f"CONTEXT_HEADER must be on or off, not {flag!r}")
    return ChunkSettings(
        child_tokens=int(e.get("CHUNK_TOKENS", "500")),
        overlap=int(e.get("CHUNK_OVERLAP", "50")),
        parent_max=int(e.get("PARENT_MAX_TOKENS", "1500")),
        context_header=flag in {"on", "true", "1"},
    )


def selected(sources: Sources, only: str | None) -> list[SourceDoc]:
    if not only:
        return list(sources.documents)
    wanted = {s.strip() for s in only.split(",") if s.strip()}
    unknown = wanted - {d.id for d in sources.documents}
    if unknown:
        raise SystemExit(f"unknown document ids: {', '.join(sorted(unknown))}")
    return [d for d in sources.documents if d.id in wanted]


def rows_for(
    docs: list[SourceDoc], sources: Sources, data_dir: Path, settings: ChunkSettings, model: str
) -> dict[str, list[Row]]:
    return {
        d.id: build_rows(d, extract(d, data_dir, sources.drop_sections), settings, model)
        for d in docs
    }


def cmd_fetch(args: argparse.Namespace) -> None:
    sources = load_sources(args.sources)
    only = {d.id for d in selected(sources, args.only)} if args.only else None
    results = fetch_all(sources, args.data_dir, clock_from_env(), refresh=args.refresh, only=only)
    save_sources(sources, args.sources)
    for r in results:
        print(f"{'fetched' if r.downloaded else 'present':8} {r.doc_id}")


def cmd_chunk(args: argparse.Namespace) -> None:
    sources = load_sources(args.sources)
    settings = settings_from_env()
    all_rows = rows_for(selected(sources, args.only), sources, args.data_dir, settings, "dry-run")
    print(f"{'document':28} {'parents':>7} {'children':>8} {'glossary':>8} {'max tok':>7}")
    for doc_id, rows in all_rows.items():
        roles = [r.metadata["role"] for r in rows]
        tokens = [r.metadata.get("tokens", 0) for r in rows]
        print(
            f"{doc_id:28} {roles.count('parent'):7} {roles.count('child'):8} "
            f"{roles.count('glossary'):8} {max(tokens, default=0):7}"
        )


async def _run(args: argparse.Namespace) -> None:
    from homefund_embed.client import EmbedClient

    from homefund_db.config import APP_URL_VAR, make_engine
    from homefund_ingest import store

    sources = load_sources(args.sources)
    docs = selected(sources, args.only)
    settings = settings_from_env()
    engine = make_engine(APP_URL_VAR)
    async with EmbedClient(batch_size=16) as embedder:
        model = (await embedder.health()).embed_model
        log.info("embedding with %s, context header %s", model, settings.context_header)
        for doc_id, rows in rows_for(docs, sources, args.data_dir, settings, model).items():
            with engine.begin() as conn:
                have = store.existing_ids(conn, doc_id)
                new = [r for r in rows if r.id not in have]
                to_embed = [r for r in new if r.embed_text is not None]
                vectors: dict = {}
                if to_embed:
                    out = await embedder.embed([r.embed_text or "" for r in to_embed], sparse=True)
                    assert out.sparse is not None
                    vectors = {
                        r.id: store.Embedded(d, s)
                        for r, d, s in zip(to_embed, out.dense, out.sparse, strict=True)
                    }
                store.insert_rows(conn, new, vectors)
                deleted = store.delete_stale(conn, doc_id, {r.id for r in rows})
            print(
                f"{doc_id:28} inserted {len(new):4}  unchanged {len(rows) - len(new):4}  "
                f"deleted {deleted:4}"
            )
        if not args.only and not args.no_prune:
            with engine.begin() as conn:
                gone = store.delete_documents_except(conn, {d.id for d in sources.documents})
            if gone:
                print(f"removed {gone} rows of documents no longer in sources.yaml")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="homefund-ingest", description=__doc__.splitlines()[0])
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    p_fetch = sub.add_parser("fetch", help="download missing source files")
    p_fetch.add_argument("--refresh", action="store_true", help="re-download every file")
    p_chunk = sub.add_parser("chunk", help="offline dry run: chunk and print stats")
    p_run = sub.add_parser("run", help="chunk, embed and write guide_chunks")
    p_run.add_argument("--no-prune", action="store_true", help="keep documents not in sources")
    for p in (p_fetch, p_chunk, p_run):
        p.add_argument("--only", help="comma-separated document ids")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), stream=sys.stderr)
    if args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "chunk":
        cmd_chunk(args)
    else:
        asyncio.run(_run(args))


if __name__ == "__main__":
    main()
