from __future__ import annotations

import hashlib
import re
from datetime import date
from urllib.parse import urlsplit

import httpx
import pytest
from homefund_ingest.fetch import ALLOWED_HOSTS, FetchError, fetch_all, sha256_file, verify
from homefund_ingest.sources import DEFAULT_DATA_DIR, Sources, load_sources, save_sources

from homefund_contracts.clock import FixedClock


def test_every_source_is_official_fetched_and_on_disk(sources) -> None:
    assert len(sources.documents) >= 20
    for doc in sources.documents:
        assert urlsplit(doc.url).hostname in ALLOWED_HOSTS
        assert doc.fetched is not None and doc.sha256, doc.id
        assert verify(doc, DEFAULT_DATA_DIR).exists()
    kinds = {d.kind for d in sources.documents}
    assert kinds == {"guide", "glossary"}
    assert {d.publisher for d in sources.documents} == {"cfpb", "hud"}


def test_every_guide_page_is_the_page_its_title_names(sources) -> None:
    """Catches a URL that now serves a different page (Ask CFPB ids get reused)."""
    from homefund_ingest.pipeline import extract

    words = lambda t: set(re.findall(r"[a-z0-9]+", t.casefold().replace("\u2019", "'")))  # noqa: E731
    for doc in sources.documents:
        if doc.kind != "guide" or doc.format != "html":
            continue
        blocks = extract(doc, DEFAULT_DATA_DIR, sources.drop_sections).blocks
        heading = next(b.text for b in blocks if b.kind == "heading")
        overlap = len(words(heading) & words(doc.title)) / len(words(heading))
        assert overlap >= 0.6, (doc.id, heading, doc.title)


def test_sources_round_trip(tmp_path, sources) -> None:
    path = tmp_path / "sources.yaml"
    save_sources(sources, path)
    assert load_sources(path) == sources
    assert path.read_text().startswith("# Guides corpus")


def _sources(*urls: str, fmt: str = "html") -> Sources:
    return Sources(
        documents=[
            {
                "id": f"d{i}",
                "source": "cfpb",
                "kind": "guide",
                "publisher": "cfpb",
                "title": "T",
                "url": u,
                "format": fmt,
            }
            for i, u in enumerate(urls)
        ]
    )


def test_fetch_downloads_only_missing_files_and_records_date_and_hash(tmp_path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>hi</p>")

    src = _sources("https://www.consumerfinance.gov/a/", "https://www.hud.gov/b")
    (tmp_path / "d1.html").write_bytes(b"already here")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = fetch_all(src, tmp_path, FixedClock(date(2026, 10, 1)), client=client)
    assert [(r.doc_id, r.downloaded) for r in results] == [("d0", True), ("d1", False)]
    assert calls == ["https://www.consumerfinance.gov/a/"]
    d0 = src.documents[0]
    assert d0.fetched == date(2026, 10, 1)
    assert (
        d0.sha256 == hashlib.sha256(b"<p>hi</p>").hexdigest() == sha256_file(tmp_path / "d0.html")
    )
    assert src.documents[1].fetched is None


def test_fetch_refuses_hosts_off_the_allowlist(tmp_path) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(FetchError, match="allowlist"):
        fetch_all(
            _sources("https://example.com/x"),
            tmp_path,
            FixedClock(date(2026, 10, 1)),
            client=client,
        )


def test_fetch_refuses_a_redirect_off_the_allowlist(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/x"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError, match="allowlist"):
        fetch_all(
            _sources("https://www.hud.gov/x"),
            tmp_path,
            FixedClock(date(2026, 10, 1)),
            client=client,
        )


def test_fetch_checks_the_content_type(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(FetchError, match="application/pdf"):
        fetch_all(
            _sources("https://www.hud.gov/x.pdf", fmt="pdf"),
            tmp_path,
            FixedClock(date(2026, 10, 1)),
            client=client,
        )


def test_verify_detects_a_changed_file(tmp_path, sources) -> None:
    doc = sources.documents[0]
    (tmp_path / doc.filename).write_bytes(b"tampered")
    with pytest.raises(FetchError, match="sha256"):
        verify(doc, tmp_path)
