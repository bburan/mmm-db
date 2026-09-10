"""Unit tests for images._analysts_from_meta.

Covers the ``meta.history`` extraction that feeds the colony-manager
Analysis Scoreboard's ``analyzed_by`` / ``analyzed_at`` for IHC/OHC counts
and napari synaptograms. Pure function, no DB or image files required.

Run in an env where ``mmm_db`` is importable (e.g. the ``colony-manager``
conda env)::

    pytest tests/test_analysts_meta.py
"""
from datetime import datetime

from mmm_db.images import _analysts_from_meta


def test_extracts_distinct_users_and_latest_time():
    meta = {'meta': {'history': [
        {'user': 'mmm', 'host': 'bobcat', 'modified': '2026-07-29T21:30:04.021537+00:00'},
        {'user': 'buran', 'host': 'sable', 'modified': '2026-09-01T21:30:43.093903+00:00'},
    ]}}
    by, at = _analysts_from_meta(meta)
    assert by == ['buran', 'mmm']                       # sorted, distinct
    assert at == datetime(2026, 9, 1, 21, 30, 43, 93903)  # latest, naive UTC


def test_dedupes_repeat_users():
    meta = {'meta': {'history': [
        {'user': 'mmm', 'modified': '2026-01-01T00:00:00+00:00'},
        {'user': 'mmm', 'modified': '2026-02-01T00:00:00+00:00'},
    ]}}
    by, at = _analysts_from_meta(meta)
    assert by == ['mmm']
    assert at == datetime(2026, 2, 1, 0, 0, 0)


def test_naive_timestamp_passes_through():
    """A ``modified`` without tz info is kept as-is (no shift)."""
    meta = {'meta': {'history': [{'user': 'x', 'modified': '2026-03-04T05:06:07'}]}}
    _, at = _analysts_from_meta(meta)
    assert at == datetime(2026, 3, 4, 5, 6, 7)


def test_missing_or_empty_meta_returns_none():
    assert _analysts_from_meta({}) == (None, None)
    assert _analysts_from_meta({'data': {}}) == (None, None)
    assert _analysts_from_meta({'meta': {}}) == (None, None)
    assert _analysts_from_meta({'meta': {'history': []}}) == (None, None)


def test_malformed_entries_fail_soft():
    # Missing/unparseable ``modified`` -> user still captured, no timestamp.
    assert _analysts_from_meta(
        {'meta': {'history': [{'user': 'x'}]}}) == (['x'], None)
    assert _analysts_from_meta(
        {'meta': {'history': [{'user': 'x', 'modified': 'nope'}]}}) == (['x'], None)
    # Non-dict entries are ignored entirely.
    assert _analysts_from_meta({'meta': {'history': ['oops']}}) == (None, None)


def test_non_mapping_input_returns_none():
    assert _analysts_from_meta(None) == (None, None)
    assert _analysts_from_meta('not a dict') == (None, None)
