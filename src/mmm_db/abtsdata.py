import pandas as pd

from colony_manager.datatypes import (
    dict_callback, pdf_callback, video_callback,
)

from psidata.api import Recording
from .psidata import PSIDataTypeDescription, summarize_stretches
from abtsdata.dataset import parse_abts_filename


class ABTSDataTypeDescription(PSIDataTypeDescription):

    inline_settings = []
    settings_exclude = [
        'response_start',
        'response_ts',
        'np_start',
        'np_end',
        'trial_start',
        'response_side',
        'response',
        'score',
        'correct',
        'response_time',
        'reaction_time',
        'np_actual_duration',
        'speaker_1',
        'microphone_1_input',
        'microphone_1_input_gain',
        'manual_control',
        #'frequency',
        #'level',
        'trial_type',
        'trial_subtype',
        'np_duration',
        'psivideo_frames_written',
        'psivideo_frame_ts',
    ]

    def _parse(self, filename):
        return parse_abts_filename(filename)

    @pdf_callback('Performance', 'fa-chart-line')
    def get_performance_pdf(self):
        return self._get_pdf('performance.pdf')

    @dict_callback('Settings', 'fa-gear')
    def get_settings_modal(self):
        fh = Recording(self.path)
        tl = fh.trial_log
        cols = sorted(c for c in tl if (c not in self.settings_exclude) and (f'{c}_list' not in tl))
        return {c: summarize_stretches(tl[c]) for c in cols}

    @video_callback('Video')
    def get_behavior_video(self):
        return self.get_file('top_recording_comp.mp4')

    def _get_threshold_modal(self, unit, transform=None):
        file = self.get_file('threshold.csv')
        df = pd.read_csv(file)
        ix_cols = list(df.columns[:-3])
        df = df.set_index(ix_cols)

        if transform is not None:
            df = transform(df)

        result = {}
        for key, r in df.iterrows():
            s = f'{r["mean"]} ({r["lb"]} to {r["ub"]}) {unit}'
            l = ', '.join(f'{l}: {k}' for l, k in zip(ix_cols, key))
            result[l] = s
        return result


class ModulationGoNogo(ABTSDataTypeDescription):
    experiment = 'modulation-gonogo'


class GapDetectionGoNogo(ABTSDataTypeDescription):
    experiment = 'gap-detection'

    @dict_callback('Threshold', 'fa-arrows-down-to-line')
    def get_threshold_modal(self):
        return self._get_threshold_modal('ms', lambda x: (x*1e3).round(2))
