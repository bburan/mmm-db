from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from cftsdata.dataset import parse_psi_filename
from cftsdata.summarize_abr import load_abr_waveforms

from colony_manager.datatypes import (
    plot_callback, pdf_callback, dict_callback,
)

from .psidata import PSIDataTypeDescription


def _load_all_analyzed(path):
    """Return ``{rater: {freq_hz: {'threshold': float|None, 'data': DataFrame}}}``
    for all *-{freq}kHz-{rater}-analyzed.txt files found under ``path``.
    Frequency is taken from the filename (more precise than the file header).
    """
    import re
    from abr.parsers import load_analysis
    result = {}
    pat = re.compile(r'-([\d.]+)kHz-([^-]+)-analyzed\.txt$', re.IGNORECASE)
    for fname in sorted(path.glob('*-analyzed.txt')):
        m = pat.search(fname.name)
        if not m:
            continue
        freq_hz = float(m.group(1)) * 1000
        rater = m.group(2)
        try:
            _, threshold, df = load_analysis(fname)
        except Exception:
            continue
        result.setdefault(rater, {})[freq_hz] = {'threshold': threshold, 'data': df}
    return result


def _wave_colors():
    """Return the 5-wave CSS hex colors from abr's color scheme."""
    from abr.abrpanel import PointPlot
    return [
        '#{:02x}{:02x}{:02x}'.format(int(r * 255), int(g * 255), int(b * 255))
        for r, g, b in PointPlot.COLORS
    ]


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
        from bokeh.models import (
            ColumnDataSource, CustomJS, Select, LabelSet, Slider,
            WheelZoomTool, PanTool, BoxZoomTool, ResetTool, SaveTool, Range1d,
        )
        from bokeh.layouts import column as bk_column, row as bk_row
        from bokeh.resources import CDN

        filename = self.path / f'{self.path.name} ABR average waveforms.csv'
        df = load_abr_waveforms(filename)
        grouping = list(df.groupby('frequency'))
        picks = _load_all_analyzed(self.path)  # {rater: {freq_hz: {...}}}
        raters = sorted(picks.keys())
        wave_colors = _wave_colors() if raters else []

        first_t = grouping[0][1].columns.values * 1000  # s → ms

        p = figure(
            height=500, sizing_mode='stretch_width',
            x_range=(float(first_t[0]), float(first_t[-1])),
            tools='',
            toolbar_location='above',
            min_border_left=55,
        )
        global_y_min = float('inf')
        global_y_max = float('-inf')
        p.add_tools(WheelZoomTool(dimensions='width'))
        p.add_tools(PanTool(dimensions='width'))
        p.add_tools(BoxZoomTool(dimensions='width'))
        p.add_tools(ResetTool())
        p.add_tools(SaveTool())
        p.xaxis.axis_label = 'Time (ms)'
        p.yaxis.visible = False
        p.ygrid.grid_line_color = None

        all_label_renderers = []
        all_seg_renderers = []
        all_seg_sources = []
        freq_options = []

        freq_sources = []
        freq_offsets_list = []
        freq_offset_steps = []
        freq_n_list = []
        flat_renderers = []
        renderer_freq_idx = []
        # peak_sources_2d[rater_idx][freq_idx] = ColumnDataSource
        peak_sources_2d = [[] for _ in raters]
        flat_peak_renderers = []
        peak_rater_idx = []
        peak_freq_idx_list = []

        def _pick_point(df_picks, level, lat_col, amp_col, base_scale,
                        offset_step, offset):
            """Return (latency_ms, wn, y) for one peak, or (nan, nan, nan)."""
            nan = float('nan')
            try:
                row = df_picks.loc[level]
            except KeyError:
                return nan, nan, nan
            if isinstance(row, pd.DataFrame):
                return nan, nan, nan
            lat = row.get(lat_col, nan)
            if pd.isna(lat) or float(lat) < 0:
                return nan, nan, nan
            lat = float(lat)
            amp = row.get(amp_col, nan)
            if pd.isna(amp):
                return lat, nan, nan
            wn = float(amp) / base_scale
            y = ((wn + 1.0) / 2.0) * offset_step + offset
            return lat, wn, y

        freq_idx = 0
        for freq, df_freq in grouping:
            levels = df_freq.index.get_level_values('level')
            t = df_freq.columns.values
            w_vals = df_freq.values
            offset_step = 1.0 / (len(w_vals) + 1)

            valid_pairs = [(lv, w) for lv, w in zip(levels, w_vals)
                           if not np.isnan(w).all()]
            if not valid_pairs:
                continue

            is_first = (freq_idx == 0)
            freq_options.append(f'{freq} Hz')

            base_scale = np.mean(
                np.abs(np.array([(w.min(), w.max()) for _, w in valid_pairs]))
            ) or 1.0

            t_ms = t * 1000
            src_data = {'x': t_ms.tolist()}
            offsets = []
            lbl_x, lbl_y, lbl_text = [], [], []
            max_y = 0.0

            for k, (level, w) in enumerate(valid_pairs):
                offset = offset_step * k + offset_step * 0.5
                offsets.append(offset)
                wn = w / base_scale
                y = ((wn + 1.0) / 2.0) * offset_step + offset
                src_data[f'wn{k}'] = wn.tolist()
                src_data[f'y{k}'] = y.tolist()
                lbl_x.append(float(t_ms[0]))
                lbl_y.append(offset)
                lbl_text.append(str(int(level)))
                max_y = max(max_y, float(y.max()))
                global_y_min = min(global_y_min, float(y.min()))
                global_y_max = max(global_y_max, float(y.max()))

            # Build one peak ColumnDataSource per rater for this frequency.
            for rater_idx, rater in enumerate(raters):
                rater_picks = picks[rater]
                freq_picks = rater_picks.get(freq)
                if freq_picks is None:
                    freq_picks = next(
                        (v for f, v in rater_picks.items() if abs(f - freq) < 10.0),
                        None,
                    )
                wave_nums = []
                peak_src_data = {}
                if freq_picks is not None:
                    df_picks = freq_picks['data']
                    wave_nums = [i for i in range(1, 6)
                                 if f'P{i} Latency' in df_picks.columns]
                    for wi in wave_nums:
                        p_lats, p_wns, p_ys = [], [], []
                        n_lats, n_wns, n_ys = [], [], []
                        for k, (level, _) in enumerate(valid_pairs):
                            pl, pwn, py = _pick_point(
                                df_picks, level,
                                f'P{wi} Latency', f'P{wi} Amplitude',
                                base_scale, offset_step, offsets[k],
                            )
                            nl, nwn, ny = _pick_point(
                                df_picks, level,
                                f'N{wi} Latency', f'N{wi} Amplitude',
                                base_scale, offset_step, offsets[k],
                            )
                            p_lats.append(pl); p_wns.append(pwn); p_ys.append(py)
                            n_lats.append(nl); n_wns.append(nwn); n_ys.append(ny)
                        peak_src_data[f'p{wi}_x'] = p_lats
                        peak_src_data[f'p{wi}_wn'] = p_wns
                        peak_src_data[f'p{wi}_y'] = p_ys
                        peak_src_data[f'n{wi}_x'] = n_lats
                        peak_src_data[f'n{wi}_wn'] = n_wns
                        peak_src_data[f'n{wi}_y'] = n_ys

                peak_src = ColumnDataSource(peak_src_data)
                peak_sources_2d[rater_idx].append(peak_src)

                is_visible = is_first and (rater_idx == 0)
                for wi in wave_nums:
                    color = wave_colors[wi - 1]
                    rp = p.scatter(
                        x=f'p{wi}_x', y=f'p{wi}_y', source=peak_src,
                        marker='circle', size=8, color=color, line_color='black',
                        line_width=1, visible=is_visible,
                    )
                    rn = p.scatter(
                        x=f'n{wi}_x', y=f'n{wi}_y', source=peak_src,
                        marker='triangle', size=9, color=color, line_color='black',
                        line_width=1, visible=is_visible,
                    )
                    flat_peak_renderers.extend([rp, rn])
                    peak_rater_idx.extend([rater_idx, rater_idx])
                    peak_freq_idx_list.extend([freq_idx, freq_idx])

            n_valid = len(valid_pairs)
            src = ColumnDataSource(src_data)

            for k in range(n_valid):
                r = p.line('x', f'y{k}', source=src, line_color='black',
                           line_width=1, visible=is_first)
                flat_renderers.append(r)
                renderer_freq_idx.append(freq_idx)

            bar_y0 = min(max_y + offset_step * 0.2, 0.97)
            seg_src = ColumnDataSource({
                'x0': [float(t_ms[-1])], 'y0': [bar_y0],
                'x1': [float(t_ms[-1])], 'y1': [bar_y0 + offset_step / 2],
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

            freq_sources.append(src)
            freq_offsets_list.append(offsets)
            freq_offset_steps.append(offset_step)
            freq_n_list.append(n_valid)
            all_label_renderers.append(lbl_r)
            all_seg_renderers.append(seg_r)
            all_seg_sources.append(seg_src)
            freq_idx += 1

        pad = (global_y_max - global_y_min) * 0.05
        p.y_range = Range1d(global_y_min - pad, global_y_max + pad)

        freq_select = Select(title='Frequency', value=freq_options[0],
                             options=freq_options, width=180)
        amp_slider = Slider(start=0.1, end=10.0, value=1.0, step=0.1,
                            title='Amplitude scale', width=280)

        rater_options = raters if raters else ['(none)']
        if not peak_sources_2d:
            peak_sources_2d = [[ColumnDataSource({}) for _ in freq_options]]
        rater_select = Select(title='Rater', value=rater_options[0],
                              options=rater_options, width=140,
                              disabled=(len(rater_options) == 1))

        recompute_js = """
const fi = freq_options.indexOf(freq_select.value);
const ri = Math.max(0, raters.indexOf(rater_select.value));
const scale = amp_slider.value;
const src = freq_sources[fi];
const n = freq_n[fi];
const os = freq_os[fi];
const offs = freq_offsets[fi];
const nd = Object.assign({}, src.data);
for (let k = 0; k < n; k++) {
    const wn = src.data['wn' + k];
    const off = offs[k];
    nd['y' + k] = wn.map(v => ((v * scale + 1) / 2) * os + off);
}
src.data = nd;
if (peak_sources.length > 0) {
    const peak_src = peak_sources[ri][fi];
    const pd = Object.assign({}, peak_src.data);
    for (let wi = 1; wi <= 5; wi++) {
        for (const pt of ['p', 'n']) {
            const wn_key = pt + wi + '_wn';
            const y_key  = pt + wi + '_y';
            if (!(wn_key in peak_src.data)) continue;
            pd[y_key] = peak_src.data[wn_key].map((wn_val, k) =>
                isNaN(wn_val) ? NaN : ((wn_val * scale + 1) / 2) * os + offs[k]
            );
        }
    }
    peak_src.data = pd;
}
const ss = seg_sources[fi];
const sd = Object.assign({}, ss.data);
sd['y1'] = [sd['y0'][0] + scale * os / 2];
ss.data = sd;
"""

        visibility_js = """
flat_renderers.forEach((r, i) => { r.visible = (renderer_freq_idx[i] === fi); });
label_renderers.forEach((r, i) => { r.visible = (i === fi); });
seg_renderers.forEach((r, i) => { r.visible = (i === fi); });
flat_peak_renderers.forEach((r, i) => {
    r.visible = (peak_rater_idx[i] === ri && peak_freq_idx[i] === fi);
});
"""

        cb_args = {
            'freq_sources': freq_sources,
            'peak_sources': peak_sources_2d,
            'freq_offsets': freq_offsets_list,
            'freq_os': freq_offset_steps,
            'freq_n': freq_n_list,
            'seg_sources': all_seg_sources,
            'freq_select': freq_select,
            'freq_options': freq_options,
            'rater_select': rater_select,
            'raters': rater_options,
            'amp_slider': amp_slider,
        }
        visibility_args = {
            **cb_args,
            'flat_renderers': flat_renderers,
            'renderer_freq_idx': renderer_freq_idx,
            'label_renderers': all_label_renderers,
            'seg_renderers': all_seg_renderers,
            'flat_peak_renderers': flat_peak_renderers,
            'peak_rater_idx': peak_rater_idx,
            'peak_freq_idx': peak_freq_idx_list,
        }

        amp_slider.js_on_change('value', CustomJS(args=cb_args, code=recompute_js))
        freq_select.js_on_change('value', CustomJS(
            args=visibility_args, code=recompute_js + visibility_js))
        rater_select.js_on_change('value', CustomJS(
            args=visibility_args, code=recompute_js + visibility_js))

        layout = bk_column(
            bk_row(freq_select, rater_select, amp_slider), p,
            sizing_mode='stretch_width',
        )
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
        return self._get_pdf('ABR waveforms.pdf')

    @pdf_callback('EEG Spectrum PDF')
    def get_eeg_spectrum_pdf(self):
        return self._get_pdf('ABR eeg spectrum.pdf')

    @pdf_callback('ECG PDF')
    def get_ecg_pdf(self):
        return self._get_pdf('ECG.pdf')

    @pdf_callback('ABRpresto Diagnostics')
    def get_abr_presto_diagnostics_pdf(self):
        return self._get_pdf('ABRpresto diagnostics.pdf')

    @dict_callback('Thresholds', 'fa-arrows-down-to-line')
    def get_thresholds(self):
        picks = _load_all_analyzed(self.path)
        result = {}
        for rater, rater_picks in sorted(picks.items()):
            for freq_hz, info in sorted(rater_picks.items()):
                th = info['threshold']
                result[f'{rater} — {freq_hz / 1000:g} kHz'] = (
                    f'{th:.1f} dB SPL' if th is not None else 'Not set'
                )
        return result


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


class NoiseExposure(CFTSDataTypeDescription):

    experiment = 'noise_exposure'

    @pdf_callback('Noise Exposure PDF')
    def get_noise_exposure_pdf(self):
        return self._get_pdf('noise exposure.pdf')

    @dict_callback('Parameters', 'fa-sliders')
    def get_parameters(self):
        import json
        info = json.loads(self.get_file('noise exposure.json').read_text())
        return {
            'Freq lower bound (Hz)': f'{info["freq_lb"]:.0f}',
            'Freq upper bound (Hz)': f'{info["freq_ub"]:.0f}',
            'Requested noise level (dB SPL)': f'{info["requested_noise_level"]:.1f}',
            'Correction factor (dB)': f'{info["correction_factor"]:.1f}',
            'Expected spectrum level (dB SPL/Hz)': f'{info["expected_spectrum_level"]:.2f}',
            'Measured noise level (dB SPL)': f'{info["measured_noise_level"]:.2f}',
            'Measured noise band level (dB SPL)': f'{info["measured_noise_band_level"]:.2f}',
        }
