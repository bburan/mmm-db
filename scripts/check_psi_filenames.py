"""Flag data folders whose name the CFTS filename parser cannot read.

Why
---
Every run folder in the physiology tree is named by the CFTS launcher, but
the name is editable afterwards and gets hand-typed often enough that typos
land in the tree. A typo is silent: ``sync`` creates the ``Data`` row either
way, and the folder simply never shows up under its datatype in the viewer.
These are the ways a name goes wrong, in the order this script checks them:

``unparseable``
    ``cftsdata.dataset.parse_psi_filename`` raises. Nothing downstream can
    read the folder at all -- no animal, no date, no experiment type. A
    doubled space is the usual cause, because ``experimenter`` and
    ``animal_id`` are both single ``\\s``-separated tokens.

``trailing-text``
    The name parses, but does not *end* at the experiment type -- someone
    appended a note (``... efr_sam_epoch PASSED DURING``). The parser's
    trailing ``.*`` swallows it, so this looks fine to ``parse_psi_filename``
    and still matches nothing: ``PSIDataTypeDescription.parse`` selects a
    description class with ``stem.endswith(self.experiment)``. Notes belong
    before the experiment type, where the ``note`` group picks them up.

``animal-mismatch`` / ``date-mismatch``
    The name parses, but disagrees with the ``<animal>/<date>/`` folders it
    sits in. The parse wins downstream, so the row is filed under whatever
    was typed. This is the check that catches a transposed animal ID, since
    the surrounding tree is an independent copy of the same fact.

``unregistered-type``
    Parses and ends cleanly, but no class in ``mmm_db.registry`` claims that
    experiment type. Not a typo -- a coverage gap in this repo.

``no-ear``
    No ``left``/``right`` token, so ``side`` is null. Legitimate for some
    types (e.g. ``noise_exposure``), which is why it is informational.

Nothing here is rewritten: renaming a folder changes the ``relative_path``
of every row under it and wants a ``flask data sync`` plus an orphan check
afterwards. Suggested names are printed for the whitespace cases only, where
the fix is unambiguous.

The tree to scan comes from the ``DataLocation`` rows attached to CFTS
datatypes, reached via ``DATABASE_URL`` -- see ``resolve_roots``. On the
server that resolves itself; off it, pass ``--root``.

Usage
-----
On the server, where DATABASE_URL is already set::

    docker-compose exec -T web \\
        python /app/mmm-db/scripts/check_psi_filenames.py --quiet

Anywhere, against a tree given directly::

    python check_psi_filenames.py --root M:\\physiology\\animals

Either form takes::

    G025-2 G023-3     # limit to these animals
    --since 20260101  # recent dates only
    --csv report.csv  # also write every problem to a CSV
    --quiet           # problems only, no info section

Exits 1 if any error- or warning-level problem was found, so it can run as a
scheduled check.
"""
import argparse
import csv
import difflib
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path

from cftsdata.dataset import parse_psi_filename

from mmm_db.registry import DESCRIPTION_CLASSES

log = logging.getLogger('check_psi_filenames')

# Runs live at <root>/<animal>/<date>/<run>; the date folder is 8 digits.
P_DATE_DIR = re.compile(r'^\d{8}$')

# An experimenter seen this many times or fewer is treated as suspicious and
# checked against the common spellings. Two is deliberate: a genuine new
# person shows up in a whole session's worth of folders at once, while a
# typo usually rides along on one or two.
RARE_EXPERIMENTER_MAX = 2

# Severity drives both the grouping in the report and the exit code.
ERROR = 'error'
WARNING = 'warning'
INFO = 'info'

SEVERITY = {
    'unparseable': ERROR,
    'trailing-text': ERROR,
    'animal-mismatch': WARNING,
    'date-mismatch': WARNING,
    'rare-experimenter': WARNING,
    'unregistered-type': INFO,
    'no-ear': INFO,
}

# (registry key, experiment type) for every class that matches by name.
# Tested with endswith, not equality, because that is what
# PSIDataTypeDescription.parse does -- and the difference is load-bearing:
# 'dual_dpoae_io' ends with 'dpoae_io', so DPOAEIO claims it. An equality
# test would report such a folder as unregistered when it is in fact
# already (perhaps wrongly) absorbed by a shorter type.
REGISTERED_TYPES = [
    (key, cls.experiment) for key, cls in DESCRIPTION_CLASSES.items()
    if getattr(cls, 'experiment', None)
]


def resolve_roots():
    """Return the data roots to scan, read from the ``DataLocation`` table.

    The path is not in the environment because it is not environment-shaped:
    it is per-datatype, editable from the settings page, and differs between
    the container (``/volume1/data/...``) and a dev checkout (``M:\\...``).
    ``DATABASE_URL`` -- already set for ``web`` and ``worker`` in
    ``docker-compose.yml`` -- is the env var that points here, so the check
    follows a location repointed in the UI with no redeploy.

    Only datatypes backed by a ``CFTSDataTypeDescription`` count. That is
    exactly the set whose folder names ``parse_psi_filename`` reads:
    ``ABTSDataTypeDescription`` also derives from ``PSIDataTypeDescription``
    but parses with ``parse_abts_filename``, and running the behaviour tree
    through the wrong parser would report every folder in it as broken.
    """
    from colony_manager import models
    from colony_manager.db import get_session
    from mmm_db.cftsdata import CFTSDataTypeDescription

    try:
        session = get_session()
    except KeyError:
        raise SystemExit(
            'DATABASE_URL is not set, so the data root cannot be looked up.\n'
            'Set it, or pass --root to scan a tree directly.')

    roots = set()
    for loc in session.query(models.DataLocation).all():
        cls = DESCRIPTION_CLASSES.get(loc.datatype.description_class)
        if cls is not None and issubclass(cls, CFTSDataTypeDescription):
            roots.add(loc.base_path)

    if not roots:
        raise SystemExit(
            'No DataLocation is attached to a CFTS datatype, so there is\n'
            'nothing to scan. Pass --root to scan a tree directly.')
    return [Path(r) for r in sorted(roots)]


def find_run_folders(root, animals=None, since=None):
    """Yield ``(animal_dir_name, date_dir_name, run_path)`` for every run.

    Walks exactly three levels with ``os.scandir`` rather than ``Path.glob``
    -- the tree lives on a slow SMB share and a recursive walk of 6k+ folders
    costs minutes.
    """
    try:
        animal_entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError as exc:
        # The usual cause is running off the server: the database records
        # container-side paths, which do not exist on a dev machine.
        raise SystemExit(
            f'cannot read {root}: {exc}\n'
            'If this is a server-side path, pass --root to scan the '
            'equivalent tree here.')

    for animal in animal_entries:
        if not animal.is_dir() or animal.name.startswith('_'):
            continue
        if animals and animal.name not in animals:
            continue
        for date in sorted(os.scandir(animal.path), key=lambda e: e.name):
            if not date.is_dir() or not P_DATE_DIR.match(date.name):
                continue
            if since and date.name < since:
                continue
            for run in sorted(os.scandir(date.path), key=lambda e: e.name):
                # _exclude holds deliberately parked files and is skipped by
                # PSIDataTypeDescription.parse too.
                if not run.is_dir() or run.name.startswith('_'):
                    continue
                yield animal.name, date.name, Path(run.path)


def suggest(name):
    """Return a corrected name for the mechanical whitespace slips, else None."""
    fixed = re.sub(r'\s+', ' ', name).strip()
    return fixed if fixed != name else None


def check_run(animal_dir, date_dir, path):
    """Return a list of ``(kind, detail)`` problems for one run folder."""
    problems = []
    name = path.name

    try:
        info = parse_psi_filename(path)
    except ValueError:
        detail = 'parse_psi_filename could not read it'
        fix = suggest(name)
        if fix:
            detail += f'; suggest "{fix}"'
        return [('unparseable', detail)], None

    etype = info['experiment_type']

    if not path.stem.endswith(etype):
        trailing = path.stem[path.stem.index(etype) + len(etype):]
        problems.append((
            'trailing-text',
            f'name continues past "{etype}" with "{trailing.strip()}" -- '
            f'no description class matches',
        ))
    elif not any(path.stem.endswith(exp) for _, exp in REGISTERED_TYPES):
        problems.append((
            'unregistered-type',
            f'"{etype}" has no class in mmm_db.registry',
        ))

    if info['animal_id'] != animal_dir:
        problems.append((
            'animal-mismatch',
            f'name says "{info["animal_id"]}", folder says "{animal_dir}"',
        ))

    parsed_date = info['datetime'].strftime('%Y%m%d')
    if parsed_date != date_dir:
        problems.append((
            'date-mismatch',
            f'name says "{parsed_date}", folder says "{date_dir}"',
        ))

    if not info['ear']:
        problems.append(('no-ear', 'no left/right token, so side is null'))

    return problems, info


def check_experimenters(rows):
    """Flag rare experimenter spellings that look like a common one.

    Runs after the whole tree is read, because "rare" is only meaningful
    against the full census.
    """
    census = Counter(info['experimenter'] for _, _, _, info in rows if info)
    common = [n for n, c in census.items() if c > RARE_EXPERIMENTER_MAX]
    extra = []
    for animal_dir, date_dir, path, info in rows:
        if not info:
            continue
        name = info['experimenter']
        if census[name] > RARE_EXPERIMENTER_MAX:
            continue
        near = difflib.get_close_matches(name, common, n=1, cutoff=0.7)
        detail = f'"{name}" seen {census[name]}x'
        if near:
            detail += f'; did you mean "{near[0]}" ({census[near[0]]}x)?'
        extra.append((animal_dir, date_dir, path, 'rare-experimenter', detail))
    return extra


def main():
    parser = argparse.ArgumentParser(
        description='Flag run folders the CFTS filename parser cannot read.')
    parser.add_argument('animals', nargs='*',
                        help='limit to these animal folders (default: all)')
    parser.add_argument('--root', type=Path,
                        help='tree to scan (default: every DataLocation '
                             'attached to a CFTS datatype, read from the '
                             'database via DATABASE_URL)')
    parser.add_argument('--since', metavar='YYYYMMDD',
                        help='skip date folders before this one')
    parser.add_argument('--csv', type=Path,
                        help='also write every problem to this CSV')
    parser.add_argument('--quiet', action='store_true',
                        help='suppress the info-level section')
    args = parser.parse_args()

    # Not basicConfig: importing cftsdata configures the root logger, which
    # makes basicConfig a no-op and leaves the report wearing a level prefix.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(message)s'))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False

    if args.since and not P_DATE_DIR.match(args.since):
        parser.error('--since wants a YYYYMMDD date')

    roots = [args.root] if args.root else resolve_roots()

    rows = []
    found = []
    n_runs = 0
    for root in roots:
        for animal_dir, date_dir, path in find_run_folders(
                root, set(args.animals), args.since):
            n_runs += 1
            problems, info = check_run(animal_dir, date_dir, path)
            rows.append((animal_dir, date_dir, path, info))
            for kind, detail in problems:
                found.append((animal_dir, date_dir, path, kind, detail))

    # Deliberately across all roots: the experimenter census is only
    # meaningful against every folder the check can see.
    found.extend(check_experimenters(rows))

    by_severity = {ERROR: [], WARNING: [], INFO: []}
    for item in found:
        by_severity[SEVERITY[item[3]]].append(item)

    source = 'given' if args.root else 'from DataLocation'
    log.info('scanned %d run folders under %d root(s) (%s):',
             n_runs, len(roots), source)
    for root in roots:
        log.info('  %s', root)
    if args.animals:
        log.info('limited to: %s', ', '.join(sorted(args.animals)))

    shown = [ERROR, WARNING] if args.quiet else [ERROR, WARNING, INFO]
    for severity in shown:
        items = by_severity[severity]
        if not items:
            continue
        log.info('')
        log.info('%s (%d)', severity.upper(), len(items))
        by_kind = {}
        for item in items:
            by_kind.setdefault(item[3], []).append(item)
        for kind, kind_items in sorted(by_kind.items()):
            log.info('  %s -- %d', kind, len(kind_items))
            for animal_dir, date_dir, path, _, detail in kind_items:
                log.info('    %s/%s/%s', animal_dir, date_dir, path.name)
                log.info('        %s', detail)

    n_error = len(by_severity[ERROR])
    n_warning = len(by_severity[WARNING])
    log.info('')
    log.info('%d error, %d warning, %d info',
             n_error, n_warning, len(by_severity[INFO]))

    if args.csv:
        with open(args.csv, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(['severity', 'kind', 'animal_folder',
                             'date_folder', 'run_folder', 'detail', 'path'])
            for animal_dir, date_dir, path, kind, detail in found:
                writer.writerow([SEVERITY[kind], kind, animal_dir, date_dir,
                                 path.name, detail, str(path)])
        log.info('wrote %s', args.csv)

    return 1 if (n_error or n_warning) else 0


if __name__ == '__main__':
    sys.exit(main())
