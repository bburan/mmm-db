"""Break Leica ``.lif`` archives out into one ``.ims`` file per image series.

Why
---
``sync`` creates one ``Data`` row per file on disk, but a ``.lif`` is an
archive holding every ROI for an ear (one series per frequency). Until each
series exists as its own file, the images in it are invisible to the
database. The ``.czi`` workflow gets this for free (Zen writes one file per
image); the Leica workflow needs this pass.

The output file is named ``<lif stem>_<series name>.ims``, which is exactly
the name ``cochleogram.readers.LIFTileReader.state_filename`` already uses
for that series' ``_analysis.json`` sidecar. Existing analyses therefore
pair up with the new files with no renaming, and ``mmm_db.images``'
``P_IMAGE_FILENAME`` parses the animal/ear/frequency straight out of it.

Conversion is done by Imaris File Converter's CLI (``-ii`` selects one
series of a multi-image file), which ships with the free download:

    C:\\Program Files\\Bitplane\\ImarisConvertBioformats <version>\\
        ImarisConvertBioformats.exe

That converter does not write the per-channel ``Name`` /
``LSMEmissionWavelength`` attributes ``cochleogram.util.load_ims`` needs, so
this script stamps them on afterwards, reading the dye and detection band
out of the Leica metadata the converter *does* preserve (under
``DataSetInfo/Series Metadata``).

Usage
-----
    python lif_to_ims.py                        # dry run over the ROI tree
    python lif_to_ims.py --apply                # convert
    python lif_to_ims.py <path> ... --apply     # limit to files/folders
"""
import argparse
import logging
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import h5py
import numpy as np

log = logging.getLogger('lif_to_ims')

DEFAULT_ROOT = Path(r'M:\confocal\cochleograms (ROI)')

CONVERTER_GLOB = 'ImarisConvertBioformats */ImarisConvertBioformats.exe'
CONVERTER_ROOTS = [Path(r'C:\Program Files\Bitplane')]

# Only count images are wanted. This is the same pattern
# ``cochleogram.readers.LIFTileReader`` uses to pick the series it will
# analyze, so the two agree on what is a count image.
P_SERIES = re.compile(r'.*OHC.*')

# Emission maxima (nm) for the dyes in use, matching the values Zen writes
# into the ``.czi``-derived ``.ims`` files so that both eras sort the same
# way. Only the *ordering* matters downstream: ``load_ims`` sorts channels by
# emission and zips them against the marker names in the filename.
DYE_EMISSION = {
    'DAPI': 465,
    'AF405': 421,
    'AF488': 519,
    'AF546': 573,
    'AF555': 565,
    'AF568': 603,
    'AF594': 617,
    'AF647': 668,
}


def find_converter():
    """Return the path to ImarisConvertBioformats.exe, else ``None``."""
    for root in CONVERTER_ROOTS:
        matches = sorted(root.glob(CONVERTER_GLOB), reverse=True)
        if matches:
            return matches[0]
    return None


def list_series(converter, lif, scratch):
    """Return ``[(index, series name), ...]`` for every image in *lif*.

    The index is the one ``-ii`` expects, so this has to come from the
    converter's own metadata dump rather than from ``readlif``.
    """
    meta = scratch / f'{lif.stem}.meta.xml'
    subprocess.run([str(converter), '-i', str(lif), '-m', str(meta)],
                   check=True, capture_output=True)
    series = []
    for image in ET.parse(meta).getroot().findall('Image'):
        params = image.findtext('ImplParameters') or ''
        names = re.findall(r'^Name = (.+)$', params, re.M)
        if names:
            series.append((int(image.get('mIndex')), names[0].strip()))
    meta.unlink()
    return series


def wanted(name):
    """Whether the series *name* should be broken out.

    Skips previews/overviews (no ``OHC`` in the name) and anything whose
    name is underscore-prefixed — the convention used in these files to
    park a bad acquisition (e.g. ``_ wrong freq map _ IHC_OHC_11p3_kHz``),
    and the same one ``LIFCochleaReader.list_pieces`` skips on.
    """
    return P_SERIES.match(name) is not None and not name.startswith('_')


def _attrs(group):
    """Return an Imaris attribute group as a plain ``{key: str}`` dict."""
    out = {}
    for key, value in group.attrs.items():
        try:
            out[key] = ''.join(value.astype('U'))
        except (AttributeError, ValueError):
            out[key] = str(value)
    return out


def _set_str(group, key, value):
    """Write *value* as Imaris writes strings: an array of one-char bytes."""
    group.attrs[key] = np.frombuffer(str(value).encode('ascii'), dtype='S1')


def leica_channel_info(fh):
    """Return ``[(dye, emission), ...]`` in acquisition-channel order.

    Reads the Leica hardware settings the converter copies verbatim into
    ``DataSetInfo/Series Metadata``: the detectors say which acquisition
    channels were active, and the spectrophotometer ("SP Mirror") records
    give each of those a stain and a detection band. Imaris channel *i* is
    the *i*-th active detector.
    """
    meta = _attrs(fh['DataSetInfo/Series Metadata'])

    detectors = {}
    for key, value in meta.items():
        m = re.search(r'Detector #(\d+)\|(Channel|IsActive)$', key)
        if m:
            detectors.setdefault(int(m.group(1)), {})[m.group(2)] = value
    active = [d['Channel'] for _, d in sorted(detectors.items())
              if d.get('IsActive') == '1' and 'Channel' in d]

    bands = {}
    for key, value in meta.items():
        m = re.search(r'SP Mirror Channel (\d+) \((left|right|stain)\)$', key)
        if m:
            bands.setdefault(m.group(1), {})[m.group(2)] = value

    info = []
    for channel in active:
        band = bands.get(channel, {})
        stain = band.get('stain', '')
        # 'Leica/ALEXA 488' -> 'AF488'; anything unrecognized stays as-is.
        m = re.search(r'ALEXA\s*(\d+)', stain, re.I)
        dye = f'AF{m.group(1)}' if m else (stain.split('/')[-1] or None)
        emission = DYE_EMISSION.get(dye)
        if emission is None:
            try:
                # Fall back on the middle of the detection band.
                emission = int(round((float(band['left'])
                                      + float(band['right'])) / 2))
            except (KeyError, ValueError):
                emission = None
        info.append((dye, emission))
    return info


def stamp_channel_metadata(ims):
    """Add the ``Name`` / ``LSMEmissionWavelength`` channel attributes.

    ``cochleogram.util.load_ims`` needs an emission wavelength on every
    channel to sort them, and ImarisConvertBioformats writes neither it nor
    a usable channel name for a ``.lif`` source. Returns a description of
    what was written, or a reason it was skipped.
    """
    with h5py.File(ims, 'r+') as fh:
        channels = [k for k in fh['DataSetInfo'] if k.startswith('Channel ')]
        channels.sort(key=lambda k: int(k.split()[-1]))
        info = leica_channel_info(fh)
        if len(info) != len(channels):
            return (f'channel metadata skipped: {len(channels)} channels but '
                    f'{len(info)} active Leica detector(s)')
        if any(emission is None for _, emission in info):
            return 'channel metadata skipped: no emission wavelength in file'
        written = []
        for key, (dye, emission) in zip(channels, info):
            group = fh[f'DataSetInfo/{key}']
            if dye:
                _set_str(group, 'Name', dye)
            _set_str(group, 'LSMEmissionWavelength', emission)
            written.append(f'{dye or key}@{emission}')
        return 'channels: ' + ', '.join(written)


def convert(converter, lif, index, dest):
    """Convert one series of *lif* to *dest*, then stamp its metadata."""
    subprocess.run([str(converter), '-i', str(lif), '-ii', str(index),
                    '-o', str(dest)], check=True, capture_output=True)
    if not dest.exists():
        raise RuntimeError(f'converter wrote nothing for index {index}')
    return stamp_channel_metadata(dest)


def find_lif_files(paths):
    """Expand *paths* (files or folders) into the ``.lif`` files to process."""
    found = []
    for path in paths:
        if path.is_dir():
            found.extend(path.rglob('*.lif'))
        elif path.suffix.lower() == '.lif':
            found.append(path)
        else:
            log.warning('not a .lif file or folder, ignoring: %s', path)
    # ``_exclude`` folders are skipped by the ingestion side too, so there is
    # nothing to gain from converting them.
    return sorted(p for p in set(found) if '_exclude' not in str(p))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('path', nargs='*', type=Path, default=[DEFAULT_ROOT],
                        help=f'.lif files or folders to scan (default: {DEFAULT_ROOT})')
    parser.add_argument('--apply', action='store_true',
                        help='actually convert (default: report what would be done)')
    parser.add_argument('--overwrite', action='store_true',
                        help='reconvert series whose .ims already exists')
    parser.add_argument('--converter', type=Path, default=None,
                        help='path to ImarisConvertBioformats.exe')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    converter = args.converter or find_converter()
    if converter is None or not converter.exists():
        parser.error('ImarisConvertBioformats.exe not found — install Imaris '
                     'File Converter or pass --converter')
    log.info('converter: %s', converter)

    lif_files = find_lif_files(args.path)
    if not lif_files:
        parser.error(f'no .lif files found under {", ".join(map(str, args.path))}')
    log.info('%d .lif file(s)\n', len(lif_files))

    scratch = Path(__file__).parent
    todo = skipped = done = failed = 0
    for lif in lif_files:
        log.info('%s', lif)
        try:
            series = list_series(converter, lif, scratch)
        except (subprocess.CalledProcessError, ET.ParseError) as exc:
            log.error('  ERR  cannot read series list: %s', exc)
            failed += 1
            continue

        for index, name in series:
            if not wanted(name):
                log.info('  --   %s (not a count image)', name)
                continue
            dest = lif.with_name(f'{lif.stem}_{name}.ims')
            if dest.exists() and not args.overwrite:
                log.info('  ==   %s (exists)', dest.name)
                skipped += 1
                continue
            analysis = lif.with_name(f'{lif.stem}_{name}_analysis.json')
            tag = 'analyzed' if analysis.exists() else 'not analyzed'
            if not args.apply:
                log.info('  +    %s (%s)', dest.name, tag)
                todo += 1
                continue
            try:
                note = convert(converter, lif, index, dest)
            except (subprocess.CalledProcessError, RuntimeError, OSError) as exc:
                log.error('  ERR  %s: %s', dest.name, exc)
                failed += 1
                continue
            log.info('  OK   %s (%s; %s)', dest.name, tag, note)
            done += 1
        log.info('')

    if args.apply:
        log.info('converted %d, skipped %d existing, %d failed',
                 done, skipped, failed)
        log.info('run `flask --app colony_manager_gui:create_app data refresh '
                 '--datatype "IHC and OHC (counts)"` to ingest them')
    else:
        log.info('would convert %d series (%d already exist, %d unreadable); '
                 'rerun with --apply', todo, skipped, failed)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
