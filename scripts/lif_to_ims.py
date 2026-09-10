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
    python lif_to_ims.py --repair-origin        # dry run the origin repair
    python lif_to_ims.py --repair-origin --apply

``--repair-origin`` is a one-off pass for files converted before the origin
was stamped at conversion time. The converter zeroes the stage position, but
the ``_analysis.json`` sidecars hold absolute stage coordinates, so those
files draw their cell overlays far outside the image. It rewrites the six
extent attributes in place; the image data is untouched and no reconversion
or re-analysis is needed. It needs no converter installed.
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

# How far the stored origin may sit from the LIF's before --repair-origin
# considers a file to need rewriting. Anything genuinely unrepaired is out
# by the stage coordinate itself (tens of thousands of um), so this only has
# to clear floating-point noise in the round trip through decimal text.
ORIGIN_TOLERANCE_UM = 0.01

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


def lif_xml_root(lif):
    """Return the parsed XML header of *lif* (one open, no image decode)."""
    from readlif.utilities import get_xml

    root, _ = get_xml(lif)
    return root


def lif_series_origin(root, name):
    """Return the ``(x, y, z)`` stage origin of series *name*, in um.

    Mirrors the origin half of ``cochleogram.util.load_lif``, including its
    deliberate XPos/YPos swap (the note in that function reads "XY position
    from stage coords seem to be swapped"). Reading the header rather than
    calling ``load_lif`` keeps this to a file open instead of a full image
    decode, and the values still agree with the frame the ``_analysis.json``
    sidecars were recorded in, which is the whole point of the exercise.

    A series whose stage was never initialised has no XPos/YPos record; it
    comes back as 0 on that axis, exactly as ``load_lif`` reports it.
    Returns ``None`` when the LIF has no such series.
    """
    node = root.find(f'.//Element[@Name="{name}"]')
    if node is None:
        return None

    def _stage(attribute):
        found = node.find(f'.//FilterSettingRecord[@Attribute="{attribute}"]')
        if found is None:
            return 0.0
        return float(found.attrib['Variant'])

    # The swap is load_lif's, not a typo: it reads YPos into x, XPos into y.
    x_pos, y_pos = _stage('YPos'), _stage('XPos')
    z_node = node.find('.//DimensionDescription[@DimID="3"]')
    z_pos = float(z_node.attrib['Origin']) if z_node is not None else 0.0
    return tuple(v * 1e6 for v in (x_pos, y_pos, z_pos))


def origin_shift(ims, origin):
    """Return ``(new_min, new_max, shift)`` to put *ims* at *origin*.

    ImarisConvertBioformats writes a zero-based frame (``ExtMin`` is
    ``-voxel/2``) and drops the stage position entirely, so an image whose
    analysis holds absolute stage coordinates draws its overlays tens of
    thousands of pixels off the canvas.

    Only the frame's *origin* moves: the extent's size, and the converter's
    half-voxel offset within it, are both preserved, so this is a pure
    translation of the same grid. The target is computed from *origin*
    rather than added to what is already stored, which makes a second run a
    no-op instead of a second shift.

    Read-only, so the dry run and the real pass agree by construction.
    """
    with h5py.File(ims, 'r') as fh:
        attrs = _attrs(fh['DataSetInfo/Image'])
    n = [int(float(attrs[axis])) for axis in ('X', 'Y', 'Z')]
    old_min = [float(attrs[f'ExtMin{i}']) for i in range(3)]
    old_max = [float(attrs[f'ExtMax{i}']) for i in range(3)]
    voxel = [(old_max[i] - old_min[i]) / n[i] for i in range(3)]
    new_min = [origin[i] - voxel[i] / 2 for i in range(3)]
    new_max = [origin[i] + (n[i] - 0.5) * voxel[i] for i in range(3)]
    return new_min, new_max, [new_min[i] - old_min[i] for i in range(3)]


def stamp_origin(ims, new_min, new_max):
    """Write the six extent attributes computed by :func:`origin_shift`."""
    with h5py.File(ims, 'r+') as fh:
        group = fh['DataSetInfo/Image']
        for i in range(3):
            _set_str(group, f'ExtMin{i}', f'{new_min[i]:.9f}')
            _set_str(group, f'ExtMax{i}', f'{new_max[i]:.9f}')


def convert(converter, lif, index, dest, origin=None):
    """Convert one series of *lif* to *dest*, then stamp its metadata."""
    subprocess.run([str(converter), '-i', str(lif), '-ii', str(index),
                    '-o', str(dest)], check=True, capture_output=True)
    if not dest.exists():
        raise RuntimeError(f'converter wrote nothing for index {index}')
    note = stamp_channel_metadata(dest)
    if origin is not None:
        new_min, new_max, _ = origin_shift(dest, origin)
        stamp_origin(dest, new_min, new_max)
        note += f'; origin {new_min[0]:.1f}, {new_min[1]:.1f} um'
    return note


def repair_origins(lif_files, apply):
    """Put already-converted .ims files back into their LIF's stage frame.

    The counterpart to the origin stamping :func:`convert` now does: files
    written before that existed carry a zero-based frame, which is what makes
    their cell overlays invisible in the viewer. Rewrites six HDF5 attributes
    per file, so there is no reconversion, no re-analysis, and not a byte of
    image data is touched.
    """
    fixed = current = missing = failed = 0
    for lif in lif_files:
        log.info('%s', lif)
        try:
            root = lif_xml_root(lif)
        except Exception as exc:
            log.error('  ERR  cannot read LIF metadata: %s', exc)
            failed += 1
            continue

        for ims in sorted(lif.parent.glob(f'{lif.stem}_*.ims')):
            name = ims.stem[len(lif.stem) + 1:]
            if not wanted(name):
                continue
            origin = lif_series_origin(root, name)
            if origin is None:
                log.warning('  ??   %s (no matching series in the .lif)',
                            ims.name)
                missing += 1
                continue
            try:
                new_min, new_max, shift = origin_shift(ims, origin)
            except (OSError, KeyError, ValueError) as exc:
                log.error('  ERR  %s: %s', ims.name, exc)
                failed += 1
                continue
            if max(abs(s) for s in shift) < ORIGIN_TOLERANCE_UM:
                log.info('  ==   %s (already in the stage frame)', ims.name)
                current += 1
                continue
            desc = (f'{ims.name}: origin -> {new_min[0]:.1f}, '
                    f'{new_min[1]:.1f} um (shift {shift[0]:+.1f}, '
                    f'{shift[1]:+.1f})')
            if not apply:
                log.info('  +    %s', desc)
                fixed += 1
                continue
            try:
                stamp_origin(ims, new_min, new_max)
            except OSError as exc:
                log.error('  ERR  %s: %s', ims.name, exc)
                failed += 1
                continue
            log.info('  OK   %s', desc)
            fixed += 1
        log.info('')

    if apply:
        log.info('repaired %d, %d already correct, %d unmatched, %d failed',
                 fixed, current, missing, failed)
        if fixed:
            log.info('the max-projection cache keys on mtime, so the viewer '
                     'picks these up with no cache clear')
    else:
        log.info('would repair %d (%d already correct, %d unmatched, '
                 '%d unreadable); rerun with --apply', fixed, current,
                 missing, failed)
    return 1 if failed else 0


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
    parser.add_argument('--repair-origin', action='store_true',
                        help='rewrite existing .ims extents onto the .lif '
                             'stage origin instead of converting')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    lif_files = find_lif_files(args.path)
    if not lif_files:
        parser.error(f'no .lif files found under {", ".join(map(str, args.path))}')
    log.info('%d .lif file(s)\n', len(lif_files))

    # The repair pass reads the LIF header and rewrites HDF5 attributes, so
    # it deliberately runs before the converter lookup: no Imaris needed.
    if args.repair_origin:
        return repair_origins(lif_files, args.apply)

    converter = args.converter or find_converter()
    if converter is None or not converter.exists():
        parser.error('ImarisConvertBioformats.exe not found — install Imaris '
                     'File Converter or pass --converter')
    log.info('converter: %s', converter)

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
        try:
            root = lif_xml_root(lif)
        except Exception as exc:
            # Non-fatal: the images still convert, they just land in a
            # zero-based frame and need --repair-origin later.
            log.warning('  ??   no stage origin available: %s', exc)
            root = None

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
            origin = None if root is None else lif_series_origin(root, name)
            try:
                note = convert(converter, lif, index, dest, origin)
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
