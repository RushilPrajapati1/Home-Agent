from __future__ import annotations

import pytest
from homefund_ingest.cli import main, settings_from_env


def test_settings_from_env() -> None:
    s = settings_from_env({})
    assert (s.child_tokens, s.overlap, s.parent_max, s.context_header) == (500, 50, 1500, True)
    assert settings_from_env({"CONTEXT_HEADER": "off"}).context_header is False
    with pytest.raises(ValueError):
        settings_from_env({"CONTEXT_HEADER": "maybe"})


def test_chunk_dry_run_covers_every_source_offline(capsys) -> None:
    main(["chunk"])
    out = capsys.readouterr().out.splitlines()
    rows = {line.split()[0]: line.split()[1:] for line in out[1:]}
    assert len(rows) >= 20
    assert rows["cfpb-key-terms"][2] == "106"
    assert rows["hud-ml-2023-17"][2] == "1"
    for doc_id, (parents, kids, glossary, max_tokens) in rows.items():
        if int(glossary) == 0:
            assert int(parents) >= 1 and int(kids) >= 1, doc_id
            assert int(max_tokens) <= 500, doc_id
