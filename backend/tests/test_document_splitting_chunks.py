"""generate_candidates() over a document longer than one LLM window."""

from unittest.mock import patch

import pytest

from services.competitors import competitor_document_articles
from services.projects import project_document_articles

MODULES = [project_document_articles, competitor_document_articles]


def _long_text(parts: int, module) -> str:
    return "\n\n".join("x" * (module.MAX_INPUT_CHARS - 10) for _ in range(parts))


def _items(n: int) -> list[dict]:
    return [{"title": f"t{i}", "summary": None, "body": f"b{i}"} for i in range(n)]


def _run(module, text, ask_side_effect):
    inserted = []

    def insert(document_id, project_id, items):
        inserted.extend(items)
        return list(items)

    with patch.object(module, "_ask_llm", side_effect=ask_side_effect), \
         patch.object(module, "_insert_candidates", side_effect=insert):
        return module.generate_candidates(1, 1, text, "f.txt"), inserted


@pytest.mark.parametrize("module", MODULES)
def test_every_chunk_is_read(module):
    result, inserted = _run(module, _long_text(3, module), [_items(2)] * 3)
    assert result["total_chunks"] == 3
    assert result["chunks_processed"] == 3
    assert result["truncated"] is False
    assert len(inserted) == 6


@pytest.mark.parametrize("module", MODULES)
def test_cap_hit_before_last_chunk_leaves_parts_unread(module):
    cap = module.MAX_CANDIDATES
    result, _ = _run(module, _long_text(3, module), [_items(cap), _items(5), _items(5)])
    assert result["truncated"] is True
    assert result["cap_reached"] is True
    assert result["chunks_processed"] == 1 < result["total_chunks"]
    assert len(result["candidates"]) == cap


@pytest.mark.parametrize("module", MODULES)
def test_cap_hit_inside_last_chunk_is_not_reported_as_unread_parts(module):
    cap = module.MAX_CANDIDATES
    result, _ = _run(module, _long_text(2, module), [_items(cap - 1), _items(5)])
    assert result["truncated"] is True
    assert result["cap_reached"] is True
    assert result["chunks_processed"] == result["total_chunks"] == 2
    assert len(result["candidates"]) == cap


@pytest.mark.parametrize("module", MODULES)
def test_later_chunk_failure_keeps_earlier_candidates(module):
    result, inserted = _run(module, _long_text(3, module), [_items(2), RuntimeError("timeout")])
    assert len(inserted) == 2
    assert result["error"] == "timeout"
    assert result["chunks_processed"] == 1
    assert result["truncated"] is True


@pytest.mark.parametrize("module", MODULES)
def test_first_chunk_failure_still_raises(module):
    with pytest.raises(RuntimeError):
        _run(module, _long_text(3, module), [RuntimeError("down")])
