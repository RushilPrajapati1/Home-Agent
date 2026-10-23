"""Download each source once into data/guides/. The only network step in ingest.

Hosts are allowlisted to match the egress policy in docs/ARCHITECTURE.md, and a redirect
off the allowlist is refused rather than followed.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from homefund_contracts.clock import Clock
from homefund_ingest.sources import SourceDoc, Sources

log = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset({"www.consumerfinance.gov", "files.consumerfinance.gov", "www.hud.gov"})
USER_AGENT = "HomeFund-ingest/0.1 (+public CFPB and HUD guides; one fetch per document)"


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class FetchResult:
    doc_id: str
    downloaded: bool
    path: Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_host(url: str) -> None:
    host = urlsplit(url).hostname or ""
    if urlsplit(url).scheme != "https" or host not in ALLOWED_HOSTS:
        raise FetchError(
            f"{url} is not on the ingest allowlist ({', '.join(sorted(ALLOWED_HOSTS))})"
        )


def fetch_one(doc: SourceDoc, data_dir: Path, client: httpx.Client) -> bytes:
    check_host(doc.url)
    url = doc.url
    for _ in range(5):
        resp = client.get(url)
        if resp.is_redirect:
            url = str(resp.next_request.url) if resp.next_request else ""
            check_host(url)
            continue
        resp.raise_for_status()
        expected = "application/pdf" if doc.format == "pdf" else "text/html"
        ctype = resp.headers.get("content-type", "")
        if expected not in ctype:
            raise FetchError(f"{doc.id}: expected {expected}, got {ctype!r} from {url}")
        return resp.content
    raise FetchError(f"{doc.id}: too many redirects from {doc.url}")


def fetch_all(
    sources: Sources,
    data_dir: Path,
    clock: Clock,
    *,
    refresh: bool = False,
    only: set[str] | None = None,
    client: httpx.Client | None = None,
) -> list[FetchResult]:
    """Fetch missing files (all of them with ``refresh``), updating fetched/sha256 in place."""
    data_dir.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    http = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=60.0, follow_redirects=False
    )
    results = []
    try:
        for i, doc in enumerate(sources.documents):
            if only and doc.id not in only:
                continue
            path = data_dir / doc.filename
            if path.exists() and not refresh:
                results.append(FetchResult(doc.id, downloaded=False, path=path))
                continue
            log.info("fetching %s", doc.url)
            path.write_bytes(fetch_one(doc, data_dir, http))
            sources.documents[i] = doc.model_copy(
                update={"fetched": clock.today(), "sha256": sha256_file(path)}
            )
            results.append(FetchResult(doc.id, downloaded=True, path=path))
    finally:
        if own_client:
            http.close()
    return results


def verify(doc: SourceDoc, data_dir: Path) -> Path:
    """The raw file for ``doc``; fails if it is missing or differs from sources.yaml."""
    path = data_dir / doc.filename
    if not path.exists():
        raise FetchError(f"{path} is missing; run `make ingest-fetch`")
    if doc.sha256 and sha256_file(path) != doc.sha256:
        raise FetchError(f"{path} does not match its sha256 in sources.yaml; re-fetch it")
    return path
