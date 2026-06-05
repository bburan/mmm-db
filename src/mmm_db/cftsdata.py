import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from cftsdata.dataset import parse_psi_filename
from cftsdata.summarize_abr import load_abr_waveforms

from colony_manager.datatypes import (
    plot_callback, pdf_callback,
)

from .psidata import PSIDataTypeDescription


def plotly_waterfall(waveforms, waterfall_level='level', scale_method='mean', 
                     base_scale_multiplier=1, y_scale_bar_size=1, 
                     label_offset_x=-0.05, is_visible=True):
    """
    Generates the pre-computed Plotly traces, annotations, and shapes for a single waterfall.
    """
    levels = waveforms.index.get_level_values(waterfall_level)
    t = waveforms.columns.values
    w_vals = waveforms.values
    n = len(w_vals)
    offset_step = 1 / (n + 1)

    limits = [(w.min(), w.max()) for w in w_vals if not np.isnan(w).all()]

    if scale_method == 'mean':
        base_scale = np.mean(np.abs(np.array(limits))) * base_scale_multiplier
    elif scale_method == 'max':
        base_scale = np.max(np.abs(np.array(limits))) * base_scale_multiplier
    else:
        raise ValueError(f'Unsupported scale_method "{scale_method}"')

    traces = []
    annotations = []
    shapes = []

    for i, (l, w) in enumerate(zip(levels, w_vals)):
        if np.isnan(w).all():
            continue

        offset = offset_step * i + offset_step * 0.5
        w_norm = w / base_scale
        w_scaled = ((w_norm + 1) / 2) * offset_step
        w_final = w_scaled + offset

        # 1. Store the Trace
        traces.append(go.Scatter(
            x=t,
            y=w_final,
            mode='lines',
            line=dict(color='black'),
            name=str(l),
            hoverinfo='skip',
            visible=is_visible # Set visibility during creation!
        ))

        # 2. Store the Annotation dict
        annotations.append(dict(
            x=label_offset_x,
            y=offset + (offset_step / 2),
            xref="x domain",
            yref="y",
            text=str(l),
            showarrow=False,
            xanchor="right"
        ))

    # 3. Store the Scale Bar dict
    if y_scale_bar_size is not None:
        scale_height = (y_scale_bar_size / base_scale) * (offset_step / 2)
        shapes.append(dict(
            type="line",
            x0=1, x1=1,
            y0=1, y1=1 + scale_height,
            xref="x domain",
            yref="y domain",
            line=dict(color="red", width=2)
        ))

    return traces, annotations, shapes


class CFTSDataTypeDescription(PSIDataTypeDescription):

    def _parse(self, filename):
        return parse_psi_filename(filename)


class ABRIO(CFTSDataTypeDescription):

    experiment = 'abr_io'

    @plot_callback('Waveforms')
    def load_waveforms(self):
        from bokeh.plotting import figure
        from bokeh.embed import components
        from bokeh.models import ColumnDataSource, CustomJS, Select, LabelSet
        from bokeh.layouts import column as bk_column
        from bokeh.resources import CDN

        filename = self.path / f'{self.path.name} ABR average waveforms.csv'
        df = load_abr_waveforms(filename)
        grouping = list(df.groupby('frequency'))

        first_t = grouping[0][1].columns.values
        t_span = float(first_t[-1] - first_t[0])

        p = figure(
            height=500, sizing_mode='stretch_width',
            x_range=(first_t[0] - t_span * 0.12, first_t[-1]),
            tools='pan,wheel_zoom,box_zoom,reset,save',
            toolbar_location='above',
        )
        p.xaxis.axis_label = 'Time (ms)'
        p.yaxis.visible = False
        p.ygrid.grid_line_color = None

        all_line_renderers = []
        all_label_renderers = []
        all_seg_renderers = []
        freq_options = []
        freq_idx = 0

        for freq, df_freq in grouping:
            levels = df_freq.index.get_level_values('level')
            t = df_freq.columns.values
            w_vals = df_freq.values
            n = len(w_vals)
            offset_step = 1.0 / (n + 1)

            valid_w = [w for w in w_vals if not np.isnan(w).all()]
            if not valid_w:
                continue

            is_first = (freq_idx == 0)
            freq_options.append(f'{freq} Hz')

            limits = [(w.min(), w.max()) for w in valid_w]
            base_scale = np.mean(np.abs(np.array(limits))) or 1.0

            line_renderers = []
            lbl_x, lbl_y, lbl_text = [], [], []
            max_y = 0.0

            for j, (level, w) in enumerate(zip(levels, w_vals)):
                if np.isnan(w).all():
                    continue
                offset = offset_step * j + offset_step * 0.5
                w_norm = w / base_scale
                w_scaled = ((w_norm + 1) / 2) * offset_step
                w_final = w_scaled + offset

                src = ColumnDataSource({'x': t.tolist(), 'y': w_final.tolist()})
                r = p.line('x', 'y', source=src, line_color='black',
                           line_width=1, visible=is_first)
                line_renderers.append(r)

                lbl_x.append(float(t[0]))
                lbl_y.append(offset + offset_step / 2)
                lbl_text.append(str(int(level)))
                max_y = max(max_y, float(w_final.max()))

            # Scale bar: represents 1 µV, placed above topmost waveform.
            scale_height = (1.0 / base_scale) * (offset_step / 2)
            bar_y0 = max_y + offset_step * 0.15
            seg_src = ColumnDataSource({
                'x0': [float(t[-1])], 'y0': [bar_y0],
                'x1': [float(t[-1])], 'y1': [bar_y0 + scale_height],
            })
            seg_r = p.segment('x0', 'y0', 'x1', 'y1', source=seg_src,
                              line_color='red', line_width=2, visible=is_first)

            lbl_src = ColumnDataSource({'x': lbl_x, 'y': lbl_y, 'text': lbl_text})
            lbl_r = LabelSet(
                x='x', y='y', text='text', source=lbl_src,
                x_offset=-5, text_align='right', text_baseline='middle',
                visible=is_first, text_font_size='11px',
            )
            p.add_layout(lbl_r)

            all_line_renderers.append(line_renderers)
            all_label_renderers.append(lbl_r)
            all_seg_renderers.append(seg_r)
            freq_idx += 1

        flat_renderers = []
        renderer_freq_idx = []
        for fi, rlist in enumerate(all_line_renderers):
            for r in rlist:
                flat_renderers.append(r)
                renderer_freq_idx.append(fi)

        select = Select(
            title='Frequency', value=freq_options[0],
            options=freq_options, width=200,
        )
        select.js_on_change('value', CustomJS(
            args={
                'flat_renderers': flat_renderers,
                'renderer_freq_idx': renderer_freq_idx,
                'label_renderers': all_label_renderers,
                'seg_renderers': all_seg_renderers,
                'freq_options': freq_options,
            },
            code="""
const fi = freq_options.indexOf(cb_obj.value);
flat_renderers.forEach((r, i) => { r.visible = (renderer_freq_idx[i] === fi); });
label_renderers.forEach((r, i) => { r.visible = (i === fi); });
seg_renderers.forEach((r, i) => { r.visible = (i === fi); });
""",
        ))

        layout = bk_column(select, p, sizing_mode='stretch_width')
        script, div = components(layout)
        return {
            'type': 'bokeh',
            'script': script,
            'div': div,
            'js_urls': list(CDN.js_files),
            'css_urls': list(CDN.css_files),
        }

    @pdf_callback('Waveforms PDF')
    def get_waveforms_pdf(self):
        """Return the path to the pre-generated waveform PDF.

        Returns
        -------
        Path
        """
        return self._get_pdf('ABR waveforms.pdf')


class DPOAEIO(CFTSDataTypeDescription):

    experiment = 'dpoae_io'

    @pdf_callback('IO PDF')
    def get_io_pdf(self):
        return self._get_pdf('io.pdf')

    @pdf_callback('Thresholds PDF')
    def get_th_pdf(self):
        return self._get_pdf('th.pdf')


class IEC(CFTSDataTypeDescription):

    experiment = 'inear_speaker_calibration_chirp'

    @pdf_callback('Calibration PDF')
    def get_calibration_pdf(self):
        return self._get_pdf('calibration.pdf')
