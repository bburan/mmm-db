"""CFTS folder names suggest event tags for their session label.

Pure functions, no DB or real files needed. Run in an env where
``mmm_db`` is importable (e.g. the ``colony-manager`` conda env)::

    pytest tests/test_cfts_session_tags.py
"""
from pathlib import Path

import pytest

from mmm_db.cftsdata import ABRIO, DPOAEIO


@pytest.mark.parametrize('folder, tags', [
    ('20250101-120000 Brad G001-1 left pre-histology abr_io', ['pre-histology']),
    ('20250101-120000 Brad G001-1 left 1d post-exposure abr_io', ['1d post-exposure']),
    ('20250101-120000 Brad G001-1 right exposure 2w post-exposure 16 kHz abr_io',
     ['2w post-exposure']),
    ('20250101-120000 Brad G001-1 left 2 week post-exposure abr_io', ['2w post-exposure']),
    ('20250101-120000 Brad G001-1 left 2nd 1d post-exposure abr_io', ['1d post-exposure']),
    ('20250101-120000 Brad G001-1 left 1h post-surgery abr_io', None),
    ('20250101-120000 Brad G001-1 left baseline abr_io', None),
])
def test_abr_session_tags(folder, tags):
    parsed = ABRIO(Path('/data') / folder).parse()
    assert parsed['animal_id'] == 'G001-1'
    assert parsed.get('tags') == tags


def test_tags_on_other_cfts_types():
    folder = '20250101-120000 Brad G001-1 right pre-histology head-fixed dpoae_io'
    assert DPOAEIO(Path('/data') / folder).parse()['tags'] == ['pre-histology']
