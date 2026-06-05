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

    @plot_callback('Image')
    def load_image_plotly(self):
        info, arr = _load_czi_xy_proj(self.path)
        return _synaptogram_to_bokeh(arr, info.get('channels', []), scatter_data=[])

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


def _array_to_bokeh_rgba(arr, channels=None, percentiles=(0.1, 99.9)):
    """Composite (X, Y, n_ch) into (Y, X) uint32 RGBA for Bokeh image_rgba.

    Each channel is additively blended using its display color after
    per-channel contrast stretching between the given percentiles.
    """
    img = np.transpose(arr, (1, 0, 2)).astype(np.float32)
    H, W, n_c = img.shape
    lo_p, hi_p = percentiles

    composite = np.zeros((H, W, 3), dtype=np.float64)
    for c in range(n_c):
        ch_info = (channels[c] if channels and c < len(channels) else {})
        color = (
            _parse_channel_color(ch_info.get('display_color', ''))
            or _CHANNEL_DEFAULT_COLORS[c % len(_CHANNEL_DEFAULT_COLORS)]
        )
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        ch = img[..., c]
        lo, hi = np.percentile(ch, [lo_p, hi_p])
        scaled = np.clip((ch - lo) / (hi - lo), 0, 1) if hi > lo else np.zeros_like(ch)
        composite[..., 0] += scaled * r
        composite[..., 1] += scaled * g
        composite[..., 2] += scaled * b

    composite = np.clip(composite, 0, 255).astype(np.uint8)
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[..., :3] = composite
    rgba[..., 3] = 255
    # Little-endian uint32: R in low byte, A in high byte — matches Bokeh's
    # expected pixel layout (R=bits 0-7, G=8-15, B=16-23, A=24-31).
    return np.ascontiguousarray(rgba.view(np.uint32).reshape(H, W))


def _synaptogram_to_bokeh(xy_proj, channels, scatter_data, overlay_fn=None):
    """Return a Bokeh synaptogram as a JSON-serialisable dict.

    Each channel is stored as a raw uint8 array in the ColumnDataSource so
    that per-channel visibility toggles and min/max RangeSliders can
    recomposite the image entirely client-side via CustomJS.

    Parameters
    ----------
    xy_proj : ndarray, shape (X, Y, n_ch)
    channels : list of dicts with 'name' and 'display_color'
    scatter_data : list of (name, xi, yi) — pixel-space coordinates
    """
    from bokeh.plotting import figure
    from bokeh.embed import components
    from bokeh.models import ColumnDataSource, CustomJS, Toggle, RangeSlider
    from bokeh.layouts import column as bk_column, row as bk_row
    from bokeh.resources import CDN

    img = np.transpose(xy_proj, (1, 0, 2)).astype(np.float32)
    H, W, n_c = img.shape

    # Per-channel: normalise to uint8 and record display colour.
    ch_raws = []
    ch_colors = []
    ch_names = []
    for c in range(n_c):
        ch_info = (channels[c] if channels and c < len(channels) else {})
        ch_names.append(ch_info.get('name') or f'Channel {c + 1}')
        color = (
            _parse_channel_color(ch_info.get('display_color', ''))
            or _CHANNEL_DEFAULT_COLORS[c % len(_CHANNEL_DEFAULT_COLORS)]
        )
        r_c, g_c, b_c = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        ch_colors.append([r_c, g_c, b_c])
        ch = img[..., c]
        lo, hi = np.percentile(ch, [0.1, 99.9])
        scaled = np.clip((ch - lo) / (hi - lo), 0, 1) if hi > lo else np.zeros_like(ch)
        ch_raws.append((scaled * 255).astype(np.uint8).flatten())

    # Build initial composite RGBA (H, W) uint32.
    composite = np.zeros((H, W, 3), dtype=np.float64)
    for raw, (r_c, g_c, b_c) in zip(ch_raws, ch_colors):
        f = raw.reshape(H, W).astype(np.float64) / 255.0
        composite[..., 0] += f * r_c
        composite[..., 1] += f * g_c
        composite[..., 2] += f * b_c
    composite = np.clip(composite, 0, 255).astype(np.uint8)
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[..., :3] = composite
    rgba[..., 3] = 255
    composite_rgba = np.ascontiguousarray(rgba.view(np.uint32).reshape(H, W))

    # Two separate ColumnDataSources avoid the "inconsistent lengths" warning:
    #   img_source  — one column 'image' with a single 2D uint32 array (length 1)
    #   ch_source   — one column per channel, each a flat uint8 array (length H*W)
    img_source = ColumnDataSource({'image': [composite_rgba]})
    ch_source = ColumnDataSource({f'ch{c}': raw for c, raw in enumerate(ch_raws)})

    # y_range=(H, 0) reverses the y-axis so y=0 is at the top, matching
    # image convention without needing to flip the array.
    # sizing_mode='stretch_both' lets the figure fill whatever container the
    # browser gives it; the container's aspect-ratio CSS property (set in JS)
    # is what enforces square pixels — pure CSS, works on every resize.
    p = figure(
        sizing_mode='stretch_both',
        x_range=(0, W),
        y_range=(H, 0),
        tools='pan,wheel_zoom,box_zoom,reset,save',
        toolbar_location='above',
        background_fill_color='black',
        border_fill_color='black',
    )
    p.grid.visible = False
    p.axis.visible = False
    p.image_rgba(image='image', source=img_source, x=0, y=0, dw=W, dh=H)

    if overlay_fn is not None:
        overlay_fn(p)

    # Per-channel controls: Toggle (on/off) + RangeSlider (black/white point).
    toggles = [Toggle(label=name, active=True, button_type='light', width=150)
               for name in ch_names]
    sliders = [RangeSlider(start=0, end=255, value=(0, 255), step=1,
                           title=name, width=280)
               for name in ch_names]

    # CustomJS: recomposite all channels whenever any toggle or slider changes.
    # img_source.data['image'] is a 1-element JS array containing a Bokeh NDArray.
    # We reach the underlying ArrayBuffer via ndarray.buffer and create a mutable
    # Uint32Array view so we can write pixels in-place without touching the NDArray
    # object that Bokeh validates on every change.emit().
    recomposite_code = f"""
const H = {H}, W = {W}, n_c = {n_c};
const colors = {json.dumps(ch_colors)};
const flat_img = new Uint32Array(img_source.data['image'][0].buffer);
for (let i = 0; i < H * W; i++) {{
    let rr = 0, gg = 0, bb = 0;
    for (let c = 0; c < n_c; c++) {{
        if (!toggles[c].active) continue;
        const [lo, hi] = sliders[c].value;
        const v = ch_source.data['ch' + c][i];
        const s = (hi > lo) ? Math.max(0, Math.min(1, (v - lo) / (hi - lo))) : 0;
        rr += colors[c][0] * s;
        gg += colors[c][1] * s;
        bb += colors[c][2] * s;
    }}
    const r = Math.min(255, Math.round(rr));
    const g = Math.min(255, Math.round(gg));
    const b = Math.min(255, Math.round(bb));
    const a = (r | g | b) ? 255 : 0;
    flat_img[i] = ((a << 24) | (b << 16) | (g << 8) | r) >>> 0;
}}
img_source.change.emit();
"""
    recomposite_cb = CustomJS(
        args={'img_source': img_source, 'ch_source': ch_source,
              'toggles': toggles, 'sliders': sliders},
        code=recomposite_code,
    )
    for t in toggles:
        t.js_on_change('active', recomposite_cb)
    for s in sliders:
        s.js_on_change('value', recomposite_cb)

    _SCATTER_STYLES = {
        'IHCs': dict(size=8, fill_color='#0dcaf0', line_color='#0dcaf0', line_width=1),
    }
    _SCATTER_DEFAULT = dict(size=10, fill_color=None, line_color='white', line_width=2.5)

    # Scatter layers — one renderer + one toggle per named layer.
    ch_rows = [bk_row(t, s) for t, s in zip(toggles, sliders)]
    for name, xi, yi in scatter_data:
        pt_src = ColumnDataSource({
            'x': np.asarray(xi, dtype=float).tolist(),
            'y': np.asarray(yi, dtype=float).tolist(),
        })
        style = _SCATTER_STYLES.get(name, _SCATTER_DEFAULT)
        r = p.scatter('x', 'y', source=pt_src, **style)
        tog = Toggle(label=name, active=True, button_type='light', width=200)
        tog.js_on_change('active', CustomJS(
            args={'renderer': r},
            code='renderer.visible = cb_obj.active;',
        ))
        ch_rows.append(tog)

    # Render figure and controls as two separate divs sharing one document so
    # that CustomJS cross-references (img_source, toggles, etc.) still work.
    # The JS side wraps figure_div in a CSS aspect-ratio container and appends
    # controls_div below it, giving pure-CSS square-pixel enforcement on resize.
    controls = bk_column(*ch_rows, sizing_mode='stretch_width')
    script, (fig_div, ctrl_div) = components([p, controls])
    return {
        'type': 'bokeh',
        'script': script,
        'figure_div': fig_div,
        'controls_div': ctrl_div,
        'image_width': W,
        'image_height': H,
        'js_urls': list(CDN.js_files),
        'css_urls': list(CDN.css_files),
    }


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
        if self.path.suffix == '.syn':
            return self._load_syn_plot()
        if self.path.suffix == '.ims':
            return self._load_ims_plot()

    def _load_syn_plot(self):
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

        scatter_data = []
        for layer_name, points_md in metadata.get('points', {}).items():
            df = pd.read_csv(StringIO(points_md['data']))
            scatter_data.append((layer_name, df['x'].values, df['y'].values))

        return _synaptogram_to_bokeh(xy_proj, channels, scatter_data)

    def _load_ims_plot(self):
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
        scatter_data = [
            (marker, xi, yi) for marker, (xi, yi) in points_by_marker.items()
        ]
        return _synaptogram_to_bokeh(xy_proj, channels, scatter_data)


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


_CELL_COLORS = {
    'IHC': '#0dcaf0',
    'OHC1': '#198754',
    'OHC2': '#ffc107',
    'OHC3': '#fd7e14',
    'Extra': '#6f42c1',
}


def _add_bokeh_overlays(p, info, data):
    """Overlay spline paths and cell markers onto Bokeh figure *p* (in-place)."""
    from cochleogram.model import Points

    vx, vy = info['voxel_size'][0], info['voxel_size'][1]
    lx, ly = info['lower'][0], info['lower'][1]

    def to_px(xs, ys):
        return [(x - lx) / vx for x in xs], [(y - ly) / vy for y in ys]

    for cell_type, color in _CELL_COLORS.items():
        spiral_state = data.get('spirals', {}).get(cell_type, {})
        if spiral_state.get('x'):
            pt = Points(x=spiral_state['x'], y=spiral_state['y'],
                        origin=spiral_state.get('origin', 0))
            xi, yi = pt.interpolate()
            if len(xi):
                px_x, px_y = to_px(xi, yi)
                p.line(x=px_x, y=px_y, line_color=color, line_width=1.5)

    for cell_type, color in _CELL_COLORS.items():
        cells = data.get('cells', {}).get(cell_type, {})
        xc, yc = cells.get('x', []), cells.get('y', [])
        if xc:
            px_x, px_y = to_px(xc, yc)
            p.scatter(x=px_x, y=px_y, fill_color=color, size=8,
                      line_color='white', line_width=0.5)


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
        return _synaptogram_to_bokeh(
            arr, info.get('channels', []), scatter_data=[],
            overlay_fn=lambda p: _add_bokeh_overlays(p, info, data),
        )

    @plot_callback('IHC and OHC counts (channels)')
    def load_count_plot_channels(self):
        info, arr, data = self._load_base()
        return _synaptogram_to_bokeh(
            arr, info.get('channels', []), scatter_data=[],
            overlay_fn=lambda p: _add_bokeh_overlays(p, info, data),
        )
