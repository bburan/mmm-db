"""Upload names must parse back into the metadata they were built from.

``upload_filename`` exists so a UI-uploaded file is indistinguishable
from one sync discovered on disk. That only holds if the name it builds
matches the class's own ``parse()`` convention — otherwise a later
re-sync (or a ``flask data prune``) sees a file it cannot read, and the
mismatch is silent: the upload itself still succeeds, because the row is
inserted directly rather than parsed.

These tests close that loop. Pure functions, no DB or real files needed.

Run in an env where ``mmm_db`` is importable (e.g. the ``colony-manager``
conda env)::

    pytest tests/test_upload_filename_roundtrip.py
"""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from mmm_db.photos import AnimalPhoto, EarDissectionNotes


UPLOAD_DATE = date(2026, 4, 15)


def _animal(custom_id):
    return SimpleNamespace(custom_id=custom_id)


def _ear(custom_id, side):
    return SimpleNamespace(animal=_animal(custom_id), side=side)


def _roundtrip(cls, targets, original_filename, label):
    """Build the upload name, then parse it as sync would.

    ``parse()`` only reads ``self.path``, so the description can be
    instantiated without touching disk.
    """
    relative_path = cls.upload_filename(
        targets, original_filename, date=UPLOAD_DATE, label=label,
    )
    description = cls.__new__(cls)
    # sync parses the basename; the leading directory is part of the
    # location layout, not the convention.
    description.path = Path(relative_path)
    return relative_path, description.parse()


# ---------------------------------------------------------------------------
# AnimalPhoto
# ---------------------------------------------------------------------------

def test_animal_photo_single_target_roundtrips():
    relative_path, parsed = _roundtrip(
        AnimalPhoto, [_animal('A001')], 'snap.JPG', 'cage change',
    )
    assert relative_path == 'A001/A001 - 20260415 - cage change.jpg'
    assert parsed == {
        'animal_id': ['A001'],
        'date': UPLOAD_DATE,
        'note': 'cage change',
    }


def test_animal_photo_multi_target_roundtrips():
    """A litter portrait names several animals, and every one of them
    must come back out. ``parse()`` splits on ``,+&|`` — a space-joined
    list reads back as one bogus ID."""
    relative_path, parsed = _roundtrip(
        AnimalPhoto,
        [_animal('A001'), _animal('A002')],
        'snap.jpg',
        'litter portrait',
    )
    assert parsed is not None
    assert parsed['animal_id'] == ['A001', 'A002']
    assert parsed['date'] == UPLOAD_DATE
    assert parsed['note'] == 'litter portrait'


def test_animal_photo_auto_numbered_label_roundtrips():
    """colony-manager substitutes ``image 1`` when the user names
    nothing; the regex requires that trailing segment to be present."""
    _, parsed = _roundtrip(
        AnimalPhoto, [_animal('A001')], 'snap.jpg', 'image 1',
    )
    assert parsed is not None
    assert parsed['note'] == 'image 1'


def test_animal_photo_keeps_pdf_extension():
    relative_path, parsed = _roundtrip(
        AnimalPhoto, [_animal('A001')], 'scan.PDF', 'necropsy',
    )
    assert relative_path.endswith('.pdf')
    assert parsed is not None


def test_animal_photo_files_land_in_a_per_animal_directory():
    relative_path, _ = _roundtrip(
        AnimalPhoto, [_animal('A001')], 'snap.jpg', 'image 1',
    )
    assert relative_path.split('/')[0] == 'A001'


# ---------------------------------------------------------------------------
# EarDissectionNotes
# ---------------------------------------------------------------------------

def test_ear_dissection_single_target_roundtrips():
    relative_path, parsed = _roundtrip(
        EarDissectionNotes, [_ear('G014-4', 'Left')], 'snap.jpg',
        'dissection notes',
    )
    assert relative_path == 'G014-4L - dissection notes.jpg'
    assert parsed is not None
    assert parsed['animal_id'] == ['G014-4']
    assert parsed['side'] == ['Left']


def test_ear_dissection_multi_target_roundtrips():
    _, parsed = _roundtrip(
        EarDissectionNotes,
        [_ear('G014-4', 'Left'), _ear('G018-3', 'Right')],
        'snap.jpg',
        'image 1',
    )
    assert parsed is not None
    assert parsed['animal_id'] == ['G014-4', 'G018-3']
    assert parsed['side'] == ['Left', 'Right']


# ---------------------------------------------------------------------------
# The note stays out of the filename
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('cls, targets', [
    (AnimalPhoto, [_animal('A001')]),
    (EarDissectionNotes, [_ear('G014-4', 'Left')]),
])
def test_upload_filename_takes_no_notes_keyword(cls, targets):
    """The note is commentary stored on the row, not part of the name —
    so ``upload_filename`` must not accept it. Guards against a revert to
    the pre-split signature, which colony-manager calls with ``label=``
    and would fail on at runtime."""
    with pytest.raises(TypeError):
        cls.upload_filename(
            targets, 'snap.jpg', date=UPLOAD_DATE, notes='a note',
        )
