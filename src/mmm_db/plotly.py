from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from cftsdata.summarize_abr import load_abr_waveforms


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


def get_abr_pdf(data_file):
    full_path = Path(data_file.location.base_path) / data_file.relative_path
    return full_path / f'{full_path.name} ABR waveforms.pdf'


def load_abr(data_file):
    full_path = Path(data_file.location.base_path) / data_file.relative_path
    filename = full_path / f'{full_path.name} ABR average waveforms.csv'
    df = load_abr_waveforms(filename)

    fig = go.Figure()
    buttons = []
    
    grouping = list(df.groupby('frequency')) # Cast to list so we can iterate twice safely
    
    # Trackers for our dropdown menus
    all_annots = []
    all_shapes = []
    freq_trace_indices = []
    total_traces = 0

    # --- FIRST PASS: Add all traces to the figure and save layout elements ---
    for i, (frequency, df_freq) in enumerate(grouping):
        is_first = (i == 0)
        traces, annots, shapes = plotly_waterfall(df_freq, is_visible=is_first)
        
        # Record which trace indices belong to this frequency
        indices = list(range(total_traces, total_traces + len(traces)))
        freq_trace_indices.append(indices)
        total_traces += len(traces)
        
        for t in traces:
            fig.add_trace(t)
            
        all_annots.append(annots)
        all_shapes.append(shapes)

        # Apply the layout elements for the first frequency so it looks right on load
        if is_first:
            fig.update_layout(annotations=annots, shapes=shapes)

    # --- SECOND PASS: Build the dropdown buttons ---
    for i, (frequency, _) in enumerate(grouping):
        
        # Create a boolean array perfectly matching the total number of traces
        visible = [False] * total_traces
        for idx in freq_trace_indices[i]:
            visible[idx] = True

        buttons.append(dict(
            label=f"{frequency} Hz",
            method="update",
            args=[
                {"visible": visible}, # Updates the traces
                {
                    "annotations": all_annots[i], # Swaps in the correct labels
                    "shapes": all_shapes[i],      # Swaps in the correct scale bar
                }
            ]
        ))

    # --- Final Layout ---
    fig.update_layout(
        template="plotly_white",
        showlegend=False,
        margin=dict(l=120, r=40, t=20, b=40),
        yaxis=dict(fixedrange=True, showticklabels=False, zeroline=False, showgrid=False),
        xaxis=dict(fixedrange=True, title="Time", showgrid=True, zeroline=False),
        updatemenus=[dict(
            active=0,
            buttons=buttons,
            x=0.0,
            y=1.15,
            xanchor="left",
            yanchor="top",
            direction="down",
            showactive=True,
        )]
    )

    return fig
