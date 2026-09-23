"""Rename animal photos uploaded under the old, unparseable name. ONE-OFF.

Why
---
``AnimalPhoto.upload_filename`` used to build a name its own ``parse()``
could not read back, in two ways:

* the animal ID and the date were transposed --
  ``A001/20260415 - A001 - cage change.jpg``, where ``P_ANIMAL_PHOTO``
  wants ``<animal_id> - <YYYYMMDD> - <note>``;
* multiple IDs were joined with a space, but ``parse()`` splits them on
  ``,+&|``, so a litter portrait read back as one bogus ID.

Both are fixed going forward, but every photo uploaded before the fix
still carries the old name. Nothing is broken today -- the ``Data`` row
was written directly at upload time and the viewer reads the row, not the
name -- but the file is invisible to a re-parse: a ``flask data sync``
will not re-ingest it, and it would drop out if a row were ever rebuilt
from disk. This script renames those files and repoints their rows.

It is a one-off. Once every photo parses, it has nothing left to do and
can be deleted.

What it does
------------
For each ``Data`` row whose datatype is backed by ``AnimalPhoto``:

``ok``
    The current name already parses. Left alone -- this is also what a
    second run reports for everything the first run fixed.

``rename``
    The name matches the old upload shape and the IDs and date in it
    agree with the row. Rebuilt via ``AnimalPhoto.upload_filename`` (so
    the script cannot drift from the class), verified to parse back into
    the same animals and date, and applied.

    A file uploaded without a note has no ``<note>`` segment to carry
    over, and the regex requires one. It gets ``image 1`` -- the same
    fallback the upload flow now uses -- counting up until the name is
    free, so no existing file is displaced.

``missing`` / ``mismatch`` / ``unreadable``
    Reported, never touched. ``mismatch`` means the IDs or date in the
    name disagree with the row's own linked animals and date; renaming
    on a guess would file the photo under the wrong animal, which is
    worse than leaving it unparseable.

Usage
-----
Dry run first -- this is the default, and it prints every rename it would
make::

    python scripts/fix_animal_photo_names.py

Then, to actually rename::

    python scripts/fix_animal_photo_names.py --apply

On the server::

    ssh mmm 'cd /volume2/docker/flask && /usr/local/bin/docker-compose \\
        exec -T web python /app/mmm-db/scripts/fix_animal_photo_names.py'

Either form takes::

    A001 A002        # limit to these animals
    --limit 20       # stop after N renames (dry-run spot check)
    --csv report.csv # write every row's outcome to a CSV

The tree comes from the ``DataLocation`` rows attached to those
datatypes, via ``DATABASE_URL``, so it needs no path arguments.

Exits 1 if anything was reported as ``missing``, ``mismatch`` or
``unreadable`` -- those need a human.
"""
import argparse
import csv
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from mmm_db.photos import AnimalPhoto
from mmm_db.registry import DESCRIPTION_CLASSES

log = logging.getLogger('fix_animal_photo_names')

# The shape the old ``upload_filename`` produced, as a basename stem:
#   <YYYYMMDD> - <space-joined ids>[ - <note>]
# The ids group is non-greedy so a note containing ' - ' stays whole.
P_OLD_UPLOAD = re.compile(
    r'^(?P<date>\d{8})\s+-\s+(?P<ids>.+?)(?:\s+-\s+(?P<note>.+))?$'
)

# ``_resolve_relative_path`` suffixes a colliding stem with _1, _2, ...
P_COLLISION_SUFFIX = re.compile(r'^(?P<stem>.*)_\d+$')

# Fallback label for a photo uploaded with no note, matching what the
# upload flow now does for a file the user did not name.
AUTO_LABEL_PREFIX = 'image'
AUTO_LABEL_MAX = 1000

OK = 'ok'
RENAME = 'rename'
MISSING = 'missing'
MISMATCH = 'mismatch'
UNREADABLE = 'unreadable'

NEEDS_A_HUMAN = (MISSING, MISMATCH, UNREADABLE)


def photo_rows(session, animals=None):
    """Return the ``Data`` rows backed by ``AnimalPhoto``, oldest first.

    Selected by description class rather than by datatype name: the name
    is editable from the settings page, the class key is what actually
    decides how a file is parsed.
    """
    from colony_manager import models

    keys = [
        key for key, cls in DESCRIPTION_CLASSES.items()
        if isinstance(cls, type) and issubclass(cls, AnimalPhoto)
    ]
    if not keys:
        raise SystemExit(
            'No registry key maps to AnimalPhoto, so there is nothing to '
            'scan. Is this running against the right mmm_db?')

    rows = (
        session.query(models.AnimalData)
        .join(models.DataType, models.AnimalData.datatype_id == models.DataType.id)
        .filter(models.DataType.description_class.in_(keys))
        .order_by(models.AnimalData.id)
        .all()
    )
    if animals:
        wanted = set(animals)
        rows = [
            r for r in rows
            if wanted & {a.custom_id for a in r.animals}
        ]
    return rows


def parses(relative_path):
    """Return what ``AnimalPhoto.parse()`` makes of this path, or None.

    ``parse()`` only reads ``self.path``, so no file needs to exist.
    """
    description = AnimalPhoto.__new__(AnimalPhoto)
    description.path = Path(relative_path)
    try:
        return description.parse()
    except Exception:
        return None


def read_old_name(relative_path, row_ids):
    """Interpret an old-style name. Returns ``(ids, date_str, note)``.

    ``ids`` comes from the filename rather than from the row so that the
    two can be compared -- the filename is an independent copy of the
    same fact, and a disagreement is exactly what we refuse to guess at.
    Pass ``row_ids=None`` to read the name without requiring it to agree,
    which is how the caller tells "unreadable" from "names someone else".
    Returns ``None`` if the name does not match the old shape at all.

    A stem ending in ``_1`` / ``_2`` is a collision suffix the old upload
    path appended; it is stripped only when doing so is what makes the
    IDs line up, so a note genuinely ending in ``_1`` is left alone.
    """
    stem = Path(relative_path).stem

    for candidate in (stem, None):
        if candidate is None:
            suffix_match = P_COLLISION_SUFFIX.match(stem)
            if suffix_match is None:
                return None
            candidate = suffix_match.group('stem')

        match = P_OLD_UPLOAD.match(candidate)
        if match is None:
            continue
        ids = match.group('ids').split()
        if row_ids is None or set(ids) == row_ids:
            return ids, match.group('date'), match.group('note')

    return None


def build_new_path(ids, date, original_filename, label, taken):
    """Return a free relative path for ``label``, or count past it.

    Composed by ``AnimalPhoto.upload_filename`` itself so the script
    cannot drift from the convention it is migrating to. ``taken(path)``
    decides whether a candidate is already spoken for -- by a file on
    disk, by another row, or by an earlier rename in this same run.

    ``label`` of None means the photo carried no note, so there is
    nothing to name it after: fall back to ``image 1``, ``image 2``, ...
    """
    targets = [SimpleNamespace(custom_id=i) for i in ids]

    def compose(text):
        return AnimalPhoto.upload_filename(
            targets, original_filename, date=date, label=text,
        )

    if label is not None:
        candidate = compose(label)
        if not taken(candidate):
            return candidate
        # A reused note, or a file whose collision suffix we stripped.
        # Fall through to numbering rather than clobbering.

    for n in range(1, AUTO_LABEL_MAX + 1):
        candidate = compose(f'{AUTO_LABEL_PREFIX} {n}')
        if not taken(candidate):
            return candidate
    return None


def classify(row, claimed, base_paths):
    """Decide what to do with one row.

    Returns ``(kind, detail, new_relative_path_or_None)``. Nothing is
    written here -- ``main`` owns the filesystem and the session, so a
    dry run and a real run take exactly the same decisions.
    """
    old_relative = row.relative_path or ''
    row_ids = {a.custom_id for a in row.animals}

    if parses(old_relative) is not None:
        return OK, 'already parses', None

    if not row_ids:
        return MISMATCH, 'row is linked to no animal', None

    base = base_paths.get(row.location_id)
    if base is None:
        return UNREADABLE, 'row has no usable DataLocation', None

    old_full = os.path.join(base, *old_relative.split('/'))
    if not os.path.isfile(old_full):
        return MISSING, f'no file at {old_full}', None

    read = read_old_name(old_relative, row_ids)
    if read is None:
        # Separate "I cannot read this name at all" from "I can read it
        # and it names someone else" -- the second is a real data problem
        # worth a person's attention, the first is just a hand-named file.
        loose = read_old_name(old_relative, None)
        if loose is not None:
            return (
                MISMATCH,
                f'name says {sorted(set(loose[0]))}, '
                f'row has {sorted(row_ids)}',
                None,
            )
        return (
            UNREADABLE,
            'does not match the old upload shape '
            '(<YYYYMMDD> - <ids>[ - <note>])',
            None,
        )
    ids, date_str, note = read

    if row.date is not None and row.date.strftime('%Y%m%d') != date_str:
        return (
            MISMATCH,
            f'name says {date_str}, row says {row.date:%Y%m%d}',
            None,
        )

    from datetime import datetime
    try:
        file_date = datetime.strptime(date_str, '%Y%m%d').date()
    except ValueError:
        return MISMATCH, f'name carries an impossible date {date_str}', None

    def taken(candidate):
        if candidate == old_relative:
            return False  # renaming a file onto itself is a no-op, not a clash
        if candidate in claimed:
            return True
        return os.path.exists(os.path.join(base, *candidate.split('/')))

    new_relative = build_new_path(
        ids, file_date, Path(old_relative).name, note, taken,
    )
    if new_relative is None:
        return UNREADABLE, 'could not find a free name', None

    # Never rename into a name that does not parse -- that would move the
    # problem rather than fix it.
    parsed = parses(new_relative)
    if parsed is None:
        return UNREADABLE, f'{new_relative!r} still would not parse', None
    if set(parsed['animal_id']) != row_ids:
        return (
            MISMATCH,
            f'{new_relative!r} parses to {parsed["animal_id"]}, '
            f'row has {sorted(row_ids)}',
            None,
        )
    if parsed['date'] != file_date:
        return (
            MISMATCH,
            f'{new_relative!r} parses to {parsed["date"]}, '
            f'name said {date_str}',
            None,
        )

    if new_relative == old_relative:
        return OK, 'already correct', None
    return RENAME, f'{old_relative}  ->  {new_relative}', new_relative


def apply_rename(base, old_relative, new_relative):
    """Move the file. Raises rather than overwriting anything."""
    old_full = os.path.join(base, *old_relative.split('/'))
    new_full = os.path.join(base, *new_relative.split('/'))
    if os.path.exists(new_full):
        raise FileExistsError(new_full)
    os.makedirs(os.path.dirname(new_full), exist_ok=True)
    os.rename(old_full, new_full)

    # A multi-animal photo moves out of its old ' '-joined directory into
    # a ' + '-joined one, leaving the old one empty. Tidy it, but never
    # insist -- anything else in there is someone's file, not ours.
    old_dir = os.path.dirname(old_full)
    if old_dir and os.path.normpath(old_dir) != os.path.normpath(base):
        try:
            os.rmdir(old_dir)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.split('\n\n')[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('animals', nargs='*',
                        help='limit to photos of these animals (custom_id)')
    parser.add_argument('--apply', action='store_true',
                        help='actually rename; without it, report only')
    parser.add_argument('--limit', type=int,
                        help='stop after this many renames')
    parser.add_argument('--csv', help='write every row outcome here')
    parser.add_argument('--quiet', action='store_true',
                        help='skip the per-row ok lines')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    from colony_manager import models
    from colony_manager.db import get_session

    try:
        session = get_session()
    except KeyError:
        raise SystemExit(
            'DATABASE_URL is not set, so the photo rows cannot be looked up.')

    base_paths = {
        loc.id: loc.base_path
        for loc in session.query(models.DataLocation).all()
    }

    rows = photo_rows(session, args.animals or None)
    log.info('%d animal-photo row%s to check%s',
             len(rows), '' if len(rows) == 1 else 's',
             '' if not args.animals else
             f' (limited to {", ".join(sorted(args.animals))})')
    if not args.apply:
        log.info('DRY RUN -- nothing will be renamed. Re-run with --apply.')
    log.info('')

    claimed = set()
    counts = Counter()
    results = []
    renamed = 0

    for row in rows:
        old_relative = row.relative_path
        kind, detail, new_relative = classify(row, claimed, base_paths)
        counts[kind] += 1
        results.append((row, kind, detail, old_relative, new_relative))

        if kind == RENAME:
            claimed.add(new_relative)

        if kind == OK:
            if not args.quiet:
                log.info('  %-10s %s', kind, old_relative)
        else:
            log.info('  %-10s %s', kind, detail)

        if kind == RENAME and args.apply:
            base = base_paths[row.location_id]
            try:
                apply_rename(base, old_relative, new_relative)
            except OSError as exc:
                log.error('    FAILED to rename: %s', exc)
                counts[RENAME] -= 1
                counts['failed'] += 1
                claimed.discard(new_relative)
                continue
            row.relative_path = new_relative
            row.name = new_relative.rsplit('/', 1)[-1]
            renamed += 1

        if args.limit and counts[RENAME] >= args.limit:
            log.info('  ... stopping at --limit %d', args.limit)
            break

    if args.apply and renamed:
        session.commit()
        log.info('')
        log.info('committed %d renamed row%s',
                 renamed, '' if renamed == 1 else 's')
    elif args.apply:
        log.info('')
        log.info('nothing to rename')

    log.info('')
    for kind in (OK, RENAME, MISSING, MISMATCH, UNREADABLE, 'failed'):
        if counts[kind]:
            log.info('%-10s %d', kind, counts[kind])

    if args.csv:
        with open(args.csv, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(['data_id', 'outcome', 'animals',
                             'old_relative_path', 'new_relative_path',
                             'detail'])
            for row, kind, detail, old_relative, new_relative in results:
                writer.writerow([
                    row.id, kind,
                    ' '.join(sorted(a.custom_id for a in row.animals)),
                    old_relative,
                    new_relative or '',
                    detail,
                ])
        log.info('wrote %s', args.csv)

    return 1 if any(counts[k] for k in NEEDS_A_HUMAN) else 0


if __name__ == '__main__':
    sys.exit(main())
