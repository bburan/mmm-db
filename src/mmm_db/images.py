import hashlib
import io
import json
import os
import re
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from psiaudio.util import nearest_octave

from colony_manager.datatypes import (
    DataTypeDescription, plot_callback, image_callback, cache_root,
)


def _load_czi_xy_proj(path):
    """Return ``(info, xy_proj)`` for a CZI, caching both to disk.

    ``info`` is a dict with ``voxel_size`` and ``lower`` (both lists of
    floats in μm), taken from the CZI stage metadata.  ``xy_proj`` is the
    XY max-projection as a ``(X, Y, C)`` uint8 array.

    The cache key folds in the source's path + mtime + size, so any
    in-place modification invalidates automatically. Cached arrays are
    written atomically via tempfile + ``os.replace``. Both the Plotly
    and JPEG confocal callbacks share this cache, which lives under the
    shared ``COLONY_MANAGER_CACHE_DIR`` root (``czi-maxproj``
    subnamespace).
    """
    path = Path(path)
    stat = path.stat()
    key = hashlib.sha1(
        f'{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}'.encode('utf-8'),
    ).hexdigest()
    cache_dir = cache_root('czi-maxproj') / key[:2]
    cache_npy = cache_dir / f'{key[2:]}.npy'
    cache_json = cache_dir / f'{key[2:]}.json'

    if cache_npy.exists() and cache_json.exists():
        info = json.loads(cache_json.read_text())
        return info, np.load(cache_npy, allow_pickle=False)

    from cochleogram.util import load_czi
    raw_info, img = load_czi(path)
    xy_proj = img.max(axis=-2)

    cache_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix='.npy', dir=cache_dir)
    os.close(fd)
    try:
        np.save(tmp, xy_proj, allow_pickle=False)
        os.replace(tmp, cache_npy)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    channels = [
        {'name': str(ch.get('name', '')),
         'display_color': str(ch.get('display_color', ''))}
        for ch in raw_info.get('channels', [])
    ]
    info = {
        'voxel_size': list(raw_info['voxel_size']),
        'lower': list(raw_info['lower']),
        'channels': channels,
    }
    cache_json.write_text(json.dumps(info))
    return info, xy_proj


P_IMAGE_FILENAME = re.compile(
    r'(?P<animal_id>[-\w]+)'
    r'(?P<ear>L|R)-63x-[-\w]+[_-](?P<image>IHC|IHC-OHC)[_-]'
    r'(?P<frequency>[p\d]+)_kHz\w?[_-]?'
    # Allow for notes at end after the kHz. The negative lookahead makes sure
    # that the replicate doesn't try to consume the number of IHCs instead.
    r'(?:(?P<replicate>[\w\d-]+)_(?!IHC))?'
    r'(?:(?P<IHCs>\d+)_IHC)?'
)
EAR_MAP = {'L': 'Left', 'R': 'Right'}


def pfreq_to_freq(x, octave_step=0.5):
    a, b = x.split('p')
    freq = int(a) + int(b) / 10
    if octave_step is not None:
        freq = nearest_octave(freq, octave_step, si_prefix='k').round(1)
    return float(freq)


def parse_filename(path):
    def to_replicate(x):
        if x is None:
            return 'a'
        x = x.lower()
        replicate_map = {
            'a': 'a', 'b': 'b', 'l': 'b', 'b2': 'b',
            'a2': 'a', 'l2': 'b', 'h': 'b',
        }
        return replicate_map.get(x, 'b')

    try:
        info = P_IMAGE_FILENAME.match(path.stem).groupdict()
    except AttributeError:
        return None

    info['ear'] = EAR_MAP[info['ear']]
    info['frequency'] = pfreq_to_freq(info['frequency'])
    info['IHCs'] = int(info['IHCs']) if info['IHCs'] else None
    info['r'] = to_replicate(info.pop('replicate'))
    image_type = info.pop('image')

    if image_type == 'IHC':
        info['image_type'] = 'IHC (synapses)'
    elif image_type == 'IHC-OHC':
        info['image_type'] = 'IHC and OHC (counts)'
    else:
        return None
    return info


def array_to_image(arr, format='JPEG', percentiles=(0.1, 99.9)):
    """Convert a 3D XY x color numpy array to an in-memory image buffer.

    First two dims are treated as (X, Y) and transposed to PIL's (Y, X, C).
    Each channel is independently contrast-stretched between the given
    percentiles, then clipped and cast to uint8. Channel counts of 1, 3,
    or 4 are supported.

    Returns a BytesIO positioned at 0, ready to hand to send_file.
    """
    if arr.ndim != 3:
        raise ValueError(f"Expected 3D array, got shape {arr.shape}")

    img = np.transpose(arr, (1, 0, 2)).astype(np.float32)

    lo_p, hi_p = percentiles
    out = np.empty(img.shape, dtype=np.uint8)
    for c in range(img.shape[2]):
        lo, hi = np.percentile(img[:, :, c], [lo_p, hi_p])
        if hi > lo:
            scaled = (img[:, :, c] - lo) / (hi - lo) * 255
        else:
            scaled = np.zeros_like(img[:, :, c])
        out[:, :, c] = np.clip(scaled, 0, 255).astype(np.uint8)

    channels = out.shape[2]
    if channels == 1:
        pil = Image.fromarray(out[:, :, 0], mode='L')
    elif channels == 3:
        pil = Image.fromarray(out, mode='RGB')
    elif channels == 4:
        pil = Image.fromarray(out, mode='RGBA')
        if format.upper() in ('JPEG', 'JPG'):
            pil = pil.convert('RGB')
    else:
        raise ValueError(f"Unsupported channel count: {channels}")

    buf = io.BytesIO()
    pil.save(buf, format=format)
    buf.seek(0)
    return buf


def array_to_plotly(arr, percentiles=(0.1, 99.9)):
    """Convert a 3D XY x color numpy array to a zoomable Plotly figure.

    First two dims are treated as (X, Y) and transposed to (Y, X, C) for
    display. Each channel is independently contrast-stretched between the
    given percentiles, then cast to uint8. Returns a plotly Figure ready
    to be returned from a plot callback.
    """
    import plotly.express as px

    if arr.ndim != 3:
        raise ValueError(f"Expected 3D array, got shape {arr.shape}")

    img = np.transpose(arr, (1, 0, 2)).astype(np.float32)

    lo_p, hi_p = percentiles
    out = np.empty(img.shape, dtype=np.uint8)
    for c in range(img.shape[2]):
        lo, hi = np.percentile(img[:, :, c], [lo_p, hi_p])
        if hi > lo:
            scaled = (img[:, :, c] - lo) / (hi - lo) * 255
        else:
            scaled = np.zeros_like(img[:, :, c])
        out[:, :, c] = np.clip(scaled, 0, 255).astype(np.uint8)

    if out.shape[2] == 1:
        fig = px.imshow(out[:, :, 0], color_continuous_scale='gray')
        fig.update_layout(coloraxis_showscale=False)
    else:
        fig = px.imshow(out)

    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        dragmode='zoom',
    )
    fig.update_xaxes(showticklabels=False, constrain='domain')
    fig.update_yaxes(showticklabels=False, scaleanchor='x', constrain='domain')
    return fig


class CZIDataTypeDescription(DataTypeDescription):
    """Description for confocal CZI images.
    """
    def hash_files(self):
        """Return the CZI file itself for hashing.

        Returns
        -------
        list of Path
        """
        if self.path.exists():
            return [self.path]
        return []

    @plot_callback('Confocal (zoomable)')
    def load_image_plotly(self):
        """Load the CZI and return a zoomable Plotly max-projection.

        Returns
        -------
        plotly.graph_objects.Figure
        """
        _, arr = _load_czi_xy_proj(self.path)
        return array_to_plotly(arr)

    @image_callback('Confocal (JPEG)')
    def load_image(self):
        """Load the CZI and return a JPEG BytesIO of the max-projection.

        Returns
        -------
        io.BytesIO
        """
        _, arr = _load_czi_xy_proj(self.path)
        return array_to_image(arr)

    def parse(self):
        """Parse the image filename for metadata.

        Returns
        -------
        dict or None
            Keys: ``animal_id``, ``ear``, ``frequency``, ``image_type``,
            and optionally ``IHCs`` and ``r`` (replicate).
        """
        if 'imaris' in str(self.path):
            return None
        if 'napari' in str(self.path):
            return None
        if '_exclude' in str(self.path):
            return
        if self.path.suffix != '.czi':
            return None
        return parse_filename(self.path)


class Synaptogram(CZIDataTypeDescription):
    pass


_MARKER_COLORS = {
    'CtBP2': '#ff0000',
    'MyosinVIIa': '#0000ff',
    'GluR2': '#00ff00',
}

_NAPARI_COLORMAP_TO_HEX = {
    'red': '#ff0000',
    'green': '#00ff00',
    'blue': '#0000ff',
    'cyan': '#00ffff',
    'magenta': '#ff00ff',
    'yellow': '#ffff00',
    'white': '#ffffff',
    'gray': '#808080',
    'grey': '#808080',
}


def _add_synapse_toggle(fig, n_channel_traces, n_point_traces):
    """Append a Synapses on/off button group to *fig* (in-place)."""
    if not n_point_traces:
        return
    indices = list(range(n_channel_traces, n_channel_traces + n_point_traces))
    fig.update_layout(updatemenus=list(fig.layout.updatemenus) + [dict(
        type='buttons',
        buttons=[
            dict(label='Synapses on', method='restyle',
                 args=[{'visible': True}, indices]),
            dict(label='Synapses off', method='restyle',
                 args=[{'visible': False}, indices]),
        ],
        active=0,
        x=1.0, y=1.0,
        xanchor='right', yanchor='bottom',
        showactive=True,
        bgcolor='rgba(60,60,60,0.9)',
        bordercolor='rgba(180,180,180,0.4)',
        font=dict(color='white', size=11),
        pad=dict(r=4, t=4),
    )])


def _scatter_synapses(fig, name, xi, yi):
    """Add a synapse scatter trace to *fig* (in-place)."""
    import plotly.graph_objects as go
    fig.add_trace(go.Scatter(
        x=xi, y=yi,
        mode='markers',
        name=name,
        marker=dict(size=8, color='white', symbol='circle-open',
                    line=dict(width=2)),
    ))


class SynaptogramAnalysis(DataTypeDescription):

    def hash_files(self):
        if self.path.exists():
            return [self.path]
        return []

    def parse(self):
        if '_exclude' in str(self.path):
            return
        if self.path.suffix not in ('.syn', '.ims'):
            return None
        if self.path.suffix == '.ims':
            if not self.path.name.endswith('_IHC.ims'):
                return None
        return parse_filename(self.path)

    @plot_callback('Synaptogram')
    def load_synaptogram_plot(self):
        import pandas as pd
        import tifffile
        from io import StringIO

        with tifffile.TiffFile(str(self.path)) as fh:
            metadata = json.loads(fh.pages[0].description)
            image = fh.asarray()  # (X, Y, Z, n_channels)

        xy_proj = image.max(axis=2)  # (X, Y, n_channels)

        names = metadata.get('name', [])
        colormaps = metadata.get('colormap', [])

        # Prefer masked layers; fall back to all layers if none exist.
        indices = [i for i, n in enumerate(names) if 'masked' in n.lower()]
        if not indices:
            indices = list(range(len(names)))

        xy_proj = xy_proj[..., indices]
        channels = [
            {'name': names[i],
             'display_color': _NAPARI_COLORMAP_TO_HEX.get(colormaps[i], '#ffffff')}
            for i in indices
        ]

        fig = _channels_to_plotly(xy_proj, channels)

        n_point_traces = 0
        for layer_name, points_md in metadata.get('points', {}).items():
            df = pd.read_csv(StringIO(points_md['data']))
            _scatter_synapses(fig, layer_name, df['x'], df['y'])
            n_point_traces += 1

        _add_synapse_toggle(fig, len(channels), n_point_traces)
        return fig

    @plot_callback('Synaptogram (IMS)')
    def load_ims_plot(self):
        import h5py

        def _str(attrs, key):
            return ''.join(attrs[key].astype('U'))

        def _val(attrs, key):
            return float(_str(attrs, key))

        with h5py.File(str(self.path), 'r') as fh:
            img_attrs = fh['DataSetInfo/Image'].attrs
            xlb = _val(img_attrs, 'ExtMin0'); xub = _val(img_attrs, 'ExtMax0')
            ylb = _val(img_attrs, 'ExtMin1'); yub = _val(img_attrs, 'ExtMax1')
            nx = int(_val(img_attrs, 'X'))
            ny = int(_val(img_attrs, 'Y'))
            nz = int(_val(img_attrs, 'Z'))
            vx = abs(xub - xlb) / nx
            vy = abs(yub - ylb) / ny

            # Image: one HDF5 node per channel under ResolutionLevel 0 / TimePoint 0
            raw, emission, ch_names, ch_colors = [], [], [], []
            tp = fh['DataSet/ResolutionLevel 0/TimePoint 0']
            for i, ch_node in enumerate(tp.values()):
                raw.append(ch_node['Data'][:][..., np.newaxis])
                c_attrs = fh[f'DataSetInfo/Channel {i}'].attrs
                e = _str(c_attrs, 'LSMEmissionWavelength')
                emission.append(float(e.split('-')[0]))
                try:
                    ch_names.append(_str(c_attrs, 'Name'))
                except KeyError:
                    ch_names.append(f'Channel {i + 1}')
                try:
                    # Imaris stores Color as space-separated RGB floats 0–1
                    rgb = [int(float(v) * 255)
                           for v in _str(c_attrs, 'Color').split()]
                    ch_colors.append(f'#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}')
                except Exception:
                    ch_colors.append(None)

            i_sort = np.argsort(emission)
            data = np.concatenate(raw, axis=-1)          # (z, y, x, n_ch)
            data = data[:nz, :ny, :nx, :][:, :, :, i_sort]
            data = data.swapaxes(0, 2)                   # (x, y, z, n_ch)

            channels = []
            for i_c in i_sort:
                name = ch_names[i_c]
                color = (ch_colors[i_c]
                         or _MARKER_COLORS.get(name, '#ffffff'))
                channels.append({'name': name, 'display_color': color})

            # Points: physical μm → pixel indices
            points_by_marker = {}
            for node_name, node in fh['Scene/Content'].items():
                if not node_name.startswith('Points'):
                    continue
                if 'CoordsXYZR' not in node:
                    continue
                marker = node.attrs['Name'][0].decode('utf')
                coords = node['CoordsXYZR'][:]          # (n, 4): x, y, z, r
                xi = np.round((coords[:, 0] - xlb) / vx).astype(int)
                yi = np.round((coords[:, 1] - ylb) / vy).astype(int)
                points_by_marker[marker] = (xi, yi)

        xy_proj = data.max(axis=2)                      # (x, y, n_ch)
        fig = _channels_to_plotly(xy_proj, channels)

        for marker, (xi, yi) in points_by_marker.items():
            _scatter_synapses(fig, marker, xi, yi)

        _add_synapse_toggle(fig, len(channels), len(points_by_marker))
        return fig


class IHCOHCCount(CZIDataTypeDescription):
    pass


def _parse_channel_color(display_color):
    """Return '#RRGGBB' from a CZI display_color string.

    Zeiss stores colors as '#AARRGGBB' (ARGB); standard '#RRGGBB' is also
    accepted.  Returns None if the string can't be parsed.
    """
    if not display_color or not display_color.startswith('#'):
        return None
    h = display_color.lstrip('#')
    if len(h) == 8:
        return f'#{h[2:]}'
    if len(h) == 6:
        return f'#{h}'
    return None


_CHANNEL_DEFAULT_COLORS = ['#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff']


def _channels_to_plotly(arr, channels=None):
    """Convert an (X, Y, C) uint8 array to a Plotly figure with one toggleable
    heatmap trace per channel.

    Each channel uses a transparent-to-color colorscale so that low-intensity
    regions are see-through and the black background shows through.  Traces
    are named from the CZI metadata when available and can be toggled via the
    Plotly legend.
    """
    import plotly.graph_objects as go

    img = np.transpose(arr, (1, 0, 2)).astype(np.float32)
    n_c = img.shape[2]
    fig = go.Figure()

    lo_p, hi_p = 0.1, 99.9
    for c in range(n_c):
        ch_info = channels[c] if channels and c < len(channels) else {}
        name = ch_info.get('name') or f'Channel {c + 1}'
        color = (_parse_channel_color(ch_info.get('display_color', ''))
                 or _CHANNEL_DEFAULT_COLORS[c % len(_CHANNEL_DEFAULT_COLORS)])
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

        ch = img[:, :, c]
        lo, hi = np.percentile(ch, [lo_p, hi_p])
        scaled = (ch - lo) / (hi - lo) if hi > lo else np.zeros_like(ch)
        z = np.clip(scaled, 0, 1)

        fig.add_trace(go.Heatmap(
            z=z,
            colorscale=[[0, f'rgba({r},{g},{b},0)'], [1, f'rgba({r},{g},{b},1)']],
            zmin=0, zmax=1,
            showscale=False,
            name=name,
        ))

    trace_indices = list(range(n_c))
    buttons = [dict(
        label='All',
        method='restyle',
        args=[{'visible': [True] * n_c}, trace_indices],
    )]
    for i in range(n_c):
        ch_info_i = channels[i] if channels and i < len(channels) else {}
        label = ch_info_i.get('name') or f'Channel {i + 1}'
        buttons.append(dict(
            label=label,
            method='restyle',
            args=[{'visible': [j == i for j in range(n_c)]}, trace_indices],
        ))

    fig.update_layout(
        margin=dict(l=0, r=0, t=36, b=0),
        dragmode='zoom',
        paper_bgcolor='black',
        plot_bgcolor='black',
        showlegend=False,
        updatemenus=[dict(
            type='buttons',
            direction='right',
            buttons=buttons,
            active=0,
            x=0.0,
            y=1.0,
            xanchor='left',
            yanchor='bottom',
            showactive=True,
            bgcolor='rgba(60,60,60,0.9)',
            bordercolor='rgba(180,180,180,0.4)',
            font=dict(color='white', size=11),
            pad=dict(r=4, t=4),
        )],
    )
    fig.update_xaxes(showticklabels=False, showgrid=False, constrain='domain')
    fig.update_yaxes(showticklabels=False, showgrid=False, scaleanchor='x',
                     constrain='domain', autorange='reversed')
    return fig


_CELL_COLORS = {
    'IHC': '#0dcaf0',
    'OHC1': '#198754',
    'OHC2': '#ffc107',
    'OHC3': '#fd7e14',
    'Extra': '#6f42c1',
}


class IHCOHCCountAnalysis(DataTypeDescription):

    def hash_files(self):
        """Return the analysis JSON and associated CZI for hashing.

        Returns
        -------
        list of Path
        """
        paths = []
        if self.path.exists():
            paths.append(self.path)
        czi = self.path.parent / self.path.name.replace('_analysis.json', '.czi')
        if czi.exists():
            paths.append(czi)
        return paths

    def parse(self):
        if '_exclude' in str(self.path):
            return
        if not self.path.name.endswith('_analysis.json'):
            return None
        return parse_filename(self.path)

    def _load_base(self):
        czi_path = self.path.parent / self.path.name.replace('_analysis.json', '.czi')
        info, arr = _load_czi_xy_proj(czi_path)
        analysis = json.loads(self.path.read_text())
        data = analysis.get('data', analysis)
        return info, arr, data

    def _add_overlays(self, fig, info, data):
        """Overlay spline paths and cell markers onto *fig* (in-place)."""
        import plotly.graph_objects as go
        from cochleogram.model import Points

        vx, vy = info['voxel_size'][0], info['voxel_size'][1]
        lx, ly = info['lower'][0], info['lower'][1]

        def to_px(xs, ys):
            return [(x - lx) / vx for x in xs], [(y - ly) / vy for y in ys]

        for cell_type, color in _CELL_COLORS.items():
            spiral_state = data.get('spirals', {}).get(cell_type, {})
            if spiral_state.get('x'):
                p = Points(x=spiral_state['x'], y=spiral_state['y'],
                           origin=spiral_state.get('origin', 0))
                xi, yi = p.interpolate()
                if len(xi):
                    px_x, px_y = to_px(xi, yi)
                    fig.add_trace(go.Scatter(
                        x=px_x, y=px_y,
                        mode='lines',
                        name=f'{cell_type} path',
                        line=dict(color=color, width=1.5),
                    ))

        for cell_type, color in _CELL_COLORS.items():
            cells = data.get('cells', {}).get(cell_type, {})
            xc, yc = cells.get('x', []), cells.get('y', [])
            if xc:
                px_x, px_y = to_px(xc, yc)
                fig.add_trace(go.Scatter(
                    x=px_x, y=px_y,
                    mode='markers',
                    name=cell_type,
                    marker=dict(color=color, size=8,
                                line=dict(color='white', width=0.5)),
                ))

    @plot_callback('IHC and OHC counts')
    def load_count_plot(self):
        info, arr, data = self._load_base()
        fig = array_to_plotly(arr)
        self._add_overlays(fig, info, data)
        return fig

    @plot_callback('IHC and OHC counts (channels)')
    def load_count_plot_channels(self):
        info, arr, data = self._load_base()
        fig = _channels_to_plotly(arr, info.get('channels'))
        self._add_overlays(fig, info, data)
        return fig
