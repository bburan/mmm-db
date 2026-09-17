"""Report which machine each IHC/OHC cell-count analysis was done on.

Why
---
Each counted image carries a ``<stem>_analysis.json`` sidecar. Newer ones
hold a ``meta.history`` block -- a chronological list of
``{'user', 'host', 'modified'}`` entries, one per save -- so the analysis
records the machine it was worked on. Useful for tracing a machine-specific
problem (a mis-calibrated display, a bad cochleogram build) back to the
analyses it could have touched.

Older sidecars predate that block entirely and record nothing. They are
reported as ``-``, not skipped: "we don't know" is a different answer from
"no analyses from that machine", and at the time of writing most files are
in that state.

A single analysis can list several hosts when it was edited on more than one
machine. Every distinct host is shown, oldest first, so a file edited on two
machines is visible as such rather than collapsed to whichever won.

The tree to scan comes from the ``DataLocation`` rows attached to the IHC/OHC
datatype, reached via ``DATABASE_URL`` -- the same mechanism as
``check_psi_filenames.py``, so it needs no arguments on either the dev
machine or the server. Pass ``--root`` to scan a tree directly.

Usage
-----
    python list_analysis_hosts.py                 # one line per analysis
    python list_analysis_hosts.py --summary       # just the per-host tally
    python list_analysis_hosts.py --host coati    # only analyses touching a host
    python list_analysis_hosts.py --csv hosts.csv
    python list_analysis_hosts.py --root "M:\\confocal\\cochleograms (ROI)"
"""
import argparse
import csv
import json
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from mmm_db.registry import DESCRIPTION_CLASSES

log = logging.getLogger('list_analysis_hosts')

NO_HOST = '-'


def resolve_roots():
    """Return the trees to scan, from the ``DataLocation`` table.

    Selects the locations attached to a datatype backed by
    ``images.IHCOHCCount`` -- the description class whose sidecar is the
    ``_analysis.json`` this script reads. Doing it by class rather than by
    datatype name survives the datatype being renamed in the UI.
    """
    from colony_manager import models
    from colony_manager.db import get_session
    from mmm_db.images import IHCOHCCount

    try:
        session = get_session()
    except KeyError:
        raise SystemExit(
            'DATABASE_URL is not set, so the image tree cannot be looked up.\n'
            'Set it, or pass --root to scan a tree directly.')

    roots = set()
    for loc in session.query(models.DataLocation).all():
        cls = DESCRIPTION_CLASSES.get(loc.datatype.description_class)
        if cls is not None and issubclass(cls, IHCOHCCount):
            roots.add(loc.base_path)

    if not roots:
        raise SystemExit(
            'No DataLocation is attached to an IHC/OHC count datatype.\n'
            'Pass --root to scan a tree directly.')
    return [Path(r) for r in sorted(roots)]


def read_history(path):
    """Return this analysis's history entries, oldest first.

    Fails soft, matching ``images._analysts_from_meta``: a malformed sidecar
    reports no history rather than stopping the scan. ``meta.history`` is
    the current location; a few files carry a bare top-level ``history``.
    """
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(obj, dict):
        return []
    meta = obj.get('meta')
    history = (meta.get('history') if isinstance(meta, dict) else None)
    if history is None:
        history = obj.get('history')
    if not isinstance(history, list):
        return []

    entries = []
    for e in history:
        if not isinstance(e, dict):
            continue
        when = None
        if e.get('modified'):
            try:
                when = datetime.fromisoformat(e['modified'])
                if when.tzinfo is not None:
                    when = when.astimezone(tz=None).replace(tzinfo=None)
            except (TypeError, ValueError):
                when = None
        entries.append({
            'host': e.get('host') or None,
            'user': e.get('user') or None,
            'modified': when,
        })
    # datetime.min for undated entries keeps the sort total without
    # promoting them above entries that do carry a timestamp.
    entries.sort(key=lambda e: e['modified'] or datetime.min)
    return entries


def hosts_for(entries):
    """Distinct hosts in first-seen order (the sort above makes that oldest
    first), so a file edited on two machines shows both."""
    seen, ordered = set(), []
    for e in entries:
        h = e['host']
        if h and h not in seen:
            seen.add(h)
            ordered.append(h)
    return ordered


def main():
    parser = argparse.ArgumentParser(
        description='Report the machine each IHC/OHC analysis was done on.')
    parser.add_argument('--root', type=Path,
                        help='tree to scan (default: every DataLocation '
                             'attached to an IHC/OHC count datatype, read '
                             'from the database via DATABASE_URL)')
    parser.add_argument('--host', metavar='NAME',
                        help='only analyses whose history includes this host')
    parser.add_argument('--summary', action='store_true',
                        help='print only the per-host tally')
    parser.add_argument('--csv', type=Path,
                        help='also write one row per analysis to this CSV')
    args = parser.parse_args()

    # Not basicConfig: importing colony_manager configures the root logger,
    # which would leave the report wearing a level prefix.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(message)s'))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False

    roots = [args.root] if args.root else resolve_roots()

    rows = []
    for root in roots:
        if not root.is_dir():
            raise SystemExit(
                f'cannot read {root}\n'
                'If this is a server-side path, pass --root to scan the '
                'equivalent tree here.')
        for path in sorted(root.rglob('*_analysis.json')):
            entries = read_history(path)
            rows.append({
                'path': path,
                'root': root,
                'hosts': hosts_for(entries),
                'users': sorted({e['user'] for e in entries if e['user']}),
                'last': entries[-1] if entries else None,
            })

    if args.host:
        rows = [r for r in rows if args.host in r['hosts']]

    log.info('scanned %d analyses under %d root(s) (%s):',
             len(rows), len(roots), 'given' if args.root else 'from DataLocation')
    for root in roots:
        log.info('  %s', root)
    if args.host:
        log.info('filtered to host: %s', args.host)
    log.info('')

    if not args.summary:
        for r in rows:
            rel = r['path'].relative_to(r['root'])
            hosts = ', '.join(r['hosts']) or NO_HOST
            log.info('%-14s %s', hosts, rel)
        log.info('')

    tally = Counter()
    for r in rows:
        if r['hosts']:
            for h in r['hosts']:
                tally[h] += 1
        else:
            tally[NO_HOST] += 1
    with_host = sum(1 for r in rows if r['hosts'])
    log.info('%d analyses: %d with a recorded host, %d without',
             len(rows), with_host, len(rows) - with_host)
    # An analysis edited on two machines counts under both, so the column
    # can exceed the number of analyses.
    for host, n in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])):
        log.info('  %5d  %s', n, host)

    if args.csv:
        with open(args.csv, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(['hosts', 'users', 'last_host', 'last_user',
                             'last_modified', 'analysis', 'path'])
            for r in rows:
                last = r['last'] or {}
                writer.writerow([
                    ' '.join(r['hosts']),
                    ' '.join(r['users']),
                    last.get('host') or '',
                    last.get('user') or '',
                    last['modified'].isoformat() if last.get('modified') else '',
                    r['path'].name,
                    str(r['path']),
                ])
        log.info('')
        log.info('wrote %s', args.csv)

    return 0


if __name__ == '__main__':
    sys.exit(main())
