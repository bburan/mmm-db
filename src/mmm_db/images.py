import io
import re
from pathlib import Path

import numpy as np
from PIL import Image

from colony_manager.datatypes import (
    DataTypeDescription, plot_callback, image_callback,
)


P_SYNAPTOGRAM_FILENAME = re.compile(
    r'(?P<animal_id>[-\w]+)'
    r'(?P<ear>L|R)-63x-[-\w]+[_-]IHC[_-]'
    r'(?P<frequency>[p\d]+)_kHz\w?[_-]?'
    # Allow for notes at end after the kHz. The negative lookahead makes sure
    # that the replicate doesn't try to consume the number of IHCs instead.
    r'(?:(?P<replicate>[\w\d-]+)_(?!IHC))?'
    r'(?:(?P<IHCs>\d+)_IHC)?'
)
EAR_MAP = {'L': 'Left', 'R': 'Right'}


def pfreq_to_freq(x):
    a, b = x.split('p')
    return int(a) + int(b) / 10


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


class Synaptogram(DataTypeDescription):
    """Description for confocal synaptogram CZI images.

    Parses filenames following the convention::

        <animal_id><ear>-63x-..._IHC_<frequency>_kHz...
    """

    def parse(self):
        """Parse the synaptogram filename for metadata.

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
            info = P_SYNAPTOGRAM_FILENAME.match(self.path.stem).groupdict()
        except AttributeError:
            return None

        info['ear'] = EAR_MAP[info['ear']]
        info['frequency'] = pfreq_to_freq(info['frequency'])
        info['IHCs'] = int(info['IHCs']) if info['IHCs'] else None
        info['r'] = to_replicate(info.pop('replicate'))
        if '63x' in str(self.path) and 'IHC' in str(self.path):
            info['image_type'] = 'IHC (synapses)'
        return info

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
        from cochleogram.util import load_czi
        info, img = load_czi(self.path)
        xy_proj = img.max(axis=-2)
        return array_to_plotly(xy_proj)

    @image_callback('Confocal (JPEG)')
    def load_image(self):
        """Load the CZI and return a JPEG BytesIO of the max-projection.

        Returns
        -------
        io.BytesIO
        """
        from cochleogram.util import load_czi
        info, img = load_czi(self.path)
        xy_proj = img.max(axis=-2)
        return array_to_image(xy_proj)
