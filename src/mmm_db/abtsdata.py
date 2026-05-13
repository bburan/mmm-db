from colony_manager.datatypes import (
    dict_callback, pdf_callback,
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

    @pdf_callback('Performance')
    def get_performance_pdf(self):
        return self._get_pdf('performance.pdf')

    @dict_callback('Settings')
    def get_settings_modal(self):
        fh = Recording(self.path)
        tl = fh.trial_log
        cols = sorted(c for c in tl if (c not in self.settings_exclude) and (f'{c}_list' not in tl))
        return {c: summarize_stretches(tl[c]) for c in cols}


class ModulationGoNogo(ABTSDataTypeDescription):
    experiment = 'modulation-gonogo'


class GapDetectionGoNogo(ABTSDataTypeDescription):
    experiment = 'gap-detection'
