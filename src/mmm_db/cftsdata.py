import re
from datetime import datetime

import pandas as pd

from cftsdata.dataset import parse_psi_filename
from cftsdata.summarize_abr import load_abr_waveforms

from colony_manager.datatypes import pdf_callback, dict_callback

from .psidata import PSIDataTypeDescription


# Sentinel frequency used by cftsdata/abr (``abr.ABRStim.CLICK.value``) for
# click-evoked ABR data in place of a tone frequency.
CLICK_FREQ_HZ = -1.0


def _load_all_analyzed(path):
    """Return ``{rater: {freq_hz: {'threshold': float|None, 'data': DataFrame}}}``
    for all *-{freq}kHz-{rater}-analyzed.txt or *-click-{rater}-analyzed.txt
    files found under ``path``. Frequency is taken from the filename (more
    precise than the file header); click files map to ``CLICK_FREQ_HZ`` to
    match the sentinel used elsewhere for click stimuli.
    """
    import re
    from abr.parsers import load_analysis
    result = {}
    pat = re.compile(r'-(?:([\d.]+)kHz|click)-([^-]+)-analyzed\.txt$', re.IGNORECASE)
    for fname in sorted(path.glob('*-analyzed.txt')):
        m = pat.search(fname.name)
        if not m:
            continue
        freq_hz = float(m.group(1)) * 1000 if m.group(1) else CLICK_FREQ_HZ
        rater = m.group(2)
        try:
            _, threshold, df = load_analysis(fname)
        except Exception:
            continue
        result.setdefault(rater, {})[freq_hz] = {'threshold': threshold, 'data': df}
    return result


def _format_freq_label(freq_hz):
    """Format a frequency in Hz for display, special-casing the click sentinel."""
    if freq_hz == CLICK_FREQ_HZ:
        return 'click'
    return f'{freq_hz / 1000:g} kHz'


class CFTSDataTypeDescription(PSIDataTypeDescription):

    def _parse(self, filename):
        return parse_psi_filename(filename)


class ERPIO(CFTSDataTypeDescription):
    """Shared waveform PDF for evoked-response I/O experiments.

    ``waveforms_pdf_suffix`` is overridable per subclass because
    ``abr.py``'s ``summarize_abr`` and ``summarize_mlr_llr`` give the
    waveform PDF different names (see ``MLRLLRIOBase`` below).
    """

    waveforms_pdf_suffix = 'ABR waveforms.pdf'

    @pdf_callback('Waveforms PDF')
    def get_waveforms_pdf(self):
        return self._get_pdf(self.waveforms_pdf_suffix)


class ABRIO(ERPIO):

    experiment = 'abr_io'
    supports_rating = True

    def get_rating_status(self):
        picks = _load_all_analyzed(self.path)

        try:
            filename = self.path / f'{self.path.name} ABR average waveforms.csv'
            df = load_abr_waveforms(filename)
            all_freqs = set(df.index.get_level_values('frequency').unique())
        except Exception:
            return {'is_rated': False, 'note': 'Could not load waveforms'}

        n_total = len(all_freqs)
        if n_total == 0:
            return {'is_rated': False, 'note': 'No frequencies found'}

        if not picks:
            return {'is_rated': False,
                    'note': f'0 of {n_total} frequencies rated', 'raters': []}

        # Surface how many people have rated (and who) so single- vs
        # multi-rater coverage is visible at a glance — useful for deciding
        # whether a second rater is still needed. ``raters`` is also
        # persisted by the sync-rating job so the review page can filter on
        # rater count and identity.
        raters = sorted(picks.keys())
        rater_summary = (
            f"{len(raters)} rater{'s' if len(raters) != 1 else ''}: "
            f"{', '.join(raters)}"
        )

        # The pick files carry no timestamp of their own, so approximate
        # "when analyzed" with the most recent ``*-analyzed.txt`` mtime. The
        # named raters double as the scoreboard's ``analyzed_by`` so ABR
        # shows up in the by-analyst rollup alongside the histology types.
        analyzed_at = None
        try:
            mtimes = [f.stat().st_mtime for f in self.path.glob('*-analyzed.txt')]
            if mtimes:
                analyzed_at = datetime.fromtimestamp(max(mtimes))
        except OSError:
            pass
        attr = {'analyzed_by': raters}
        if analyzed_at is not None:
            attr['analyzed_at'] = analyzed_at

        # A waveform frequency is considered rated when any rater has analyzed it.
        rated_freqs = set()
        for rater_picks in picks.values():
            rated_freqs |= set(rater_picks.keys())

        n_rated = sum(
            1 for wf in all_freqs
            if any(abs(rf - wf) < 10.0 for rf in rated_freqs)
        )

        if n_rated == n_total:
            return {'is_rated': True, 'raters': raters,
                    'note': f'All {n_total} frequencies rated — {rater_summary}',
                    **attr}
        return {
            'is_rated': False, 'raters': raters,
            'note': f'{n_rated} of {n_total} frequencies rated — {rater_summary}',
            **attr,
        }

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
                result[f'{rater} — {_format_freq_label(freq_hz)}'] = (
                    f'{th:.1f} dB SPL' if th is not None else 'Not set'
                )
        return result


class ABRIOClick(ABRIO):
    """Click-evoked ABR I/O; identical output layout to :class:`ABRIO`."""

    experiment = 'abr_io_click'


class MLRLLRIOBase(ERPIO):
    """Common output layout for every ``mlr_llr_io`` variant (booth and
    freefield, tone and click), produced by ``cftsdata.summarize_mlr_llr``.

    That module saves a single ``waveforms.pdf`` covering all three bands,
    rather than ``summarize_abr``'s ``ABR waveforms.pdf``.
    """

    experiment = None
    waveforms_pdf_suffix = 'waveforms.pdf'


class MLRLLRIO(MLRLLRIOBase):

    experiment = 'mlr_llr_io'


class MLRLLRIOClick(MLRLLRIOBase):

    experiment = 'mlr_llr_io_click'


class MLRLLRIOFreeField(MLRLLRIOBase):

    experiment = 'mlr_llr_io_tone_freefield'


class MLRLLRIOClickFreeField(MLRLLRIOBase):

    experiment = 'mlr_llr_io_click_freefield'


class DPOAEIO(CFTSDataTypeDescription):

    experiment = 'dpoae_io'

    @pdf_callback('IO PDF')
    def get_io_pdf(self):
        return self._get_pdf('io.pdf')

    @pdf_callback('Thresholds PDF')
    def get_th_pdf(self):
        return self._get_pdf('th.pdf')


class DPGram(CFTSDataTypeDescription):

    experiment = 'dpgram'

    @pdf_callback('DPgram PDF')
    def get_dpgram_pdf(self):
        return self._get_pdf('dpgram.pdf')

    @pdf_callback('Mic Spectrum PDF')
    def get_mic_spectrum_pdf(self):
        return self._get_pdf('mic spectrum.pdf')


class IEC(CFTSDataTypeDescription):

    experiment = 'inear_speaker_calibration_chirp'

    @pdf_callback('Calibration PDF')
    def get_calibration_pdf(self):
        return self._get_pdf('calibration.pdf')


class EFR(CFTSDataTypeDescription):
    """Common outputs shared by the SAM and RAM EFR paradigms, produced by
    ``cftsdata.summarize_efr`` (EEG spectrum/harmonics, stimulus level) and
    ``cftsdata.summarize_ecg`` (heart rate, run on every ``efr_*``
    experiment alongside ``abr_io``)."""

    experiment = None

    @pdf_callback('EEG Spectrum PDF')
    def get_eeg_spectrum_pdf(self):
        return self._get_pdf('EEG spectrum.pdf')

    @pdf_callback('Stimulus SPL PDF')
    def get_stimulus_spl_pdf(self):
        return self._get_pdf('stimulus SPL.pdf')

    @pdf_callback('ECG PDF')
    def get_ecg_pdf(self):
        return self._get_pdf('ECG.pdf')

    @dict_callback('EFR Response', 'fa-wave-square')
    def get_efr_response(self):
        # ``psd_norm`` is already ``psd - psd_nf`` (dB re: noise floor),
        # computed by cftsdata.summarize_efr.extract_harmonics.
        df = pd.read_csv(self.get_file('EFR harmonics.csv'))
        fundamental = df[df['harmonic'] == 0].sort_values(['fc', 'fm'])
        return {
            f'{row.fm:.0f} Hz / {row.fc / 1000:g} kHz':
                f'{row.psd:.1f} dB (SNR {row.psd_norm:.1f} dB), PLV {row.plv:.2f}'
            for row in fundamental.itertuples()
        }

    @dict_callback('Processing Settings', 'fa-sliders')
    def get_processing_settings(self):
        import json
        info = json.loads(self.get_file('EFR processing settings.json').read_text())
        return {
            'Segment duration (s)': f'{info["segment_duration"]:.2f}',
            'Draws per bootstrap': f'{info["n_draw"]}',
            'Bootstrap iterations': f'{info["n_bootstrap"]}',
            'Harmonics analyzed': f'{info["n_harmonics"]}',
            'Target sampling rate (Hz)': f'{info["target_fs"]:.0f}',
        }


class EFRRAM(EFR):

    experiment = 'efr_ram_epoch'


class EFRSAM(EFR):

    experiment = 'efr_sam_epoch'


class EFRSAMFreeField(EFR):
    """SAM EFR run in the freefield rig; same outputs as :class:`EFRSAM`."""

    experiment = 'efr_sam_epoch_freefield'


class EFRRAMFreeField(EFR):
    """RAM EFR run in the freefield rig; same outputs as :class:`EFRRAM`."""

    experiment = 'efr_ram_epoch_freefield'


# A single animal ID token, e.g. ``B028-1`` or ``G011-2``. Used to pull every
# animal out of a multi-animal noise-exposure folder name.
P_NOISE_EXPOSURE_ANIMAL = re.compile(r'^[A-Za-z]+\d+-\d+$')


class NoiseExposure(CFTSDataTypeDescription):

    experiment = 'noise_exposure'

    def parse(self):
        """Parse a (possibly multi-animal) noise-exposure folder name.

        Noise exposures are frequently run on several animals at once, so a
        folder name may list multiple animal IDs — separated by whitespace or
        commas, and not necessarily right after the experimenter, e.g.::

            20230613-083735 Sean B028-1 B028-4 B029-1 B029-2 exposure noise_exposure
            20250819-091648 Sean G011-1,G011-2 103 dB SPL noise_exposure
            20250916-125017 B123-1,B123-2 Sean 97 dB SPL 2h noise_exposure

        so ``cftsdata``'s single-animal ``parse_psi_filename`` cannot handle
        them (it raises outright). Scan the whole folder name for animal-ID
        tokens instead; a single-animal folder simply yields a one-element
        list. The framework already links one ``Data`` row to every matched
        animal's event, so returning the full list is all that's needed.

        Returns
        -------
        dict or None
            ``{'animal_id': [...], 'date': date, 'experiment_type':
            'noise_exposure'}`` when at least one animal ID is found, else
            ``None``.
        """
        if '_exclude' in str(self.path):
            return None
        stem = self.path.stem
        if not stem.endswith(self.experiment):
            return None

        m = re.match(r'(\d{8}-\d{6})', stem)
        date = datetime.strptime(m.group(1), '%Y%m%d-%H%M%S').date() if m else None

        animal_ids, seen = [], set()
        for token in re.split(r'[\s,]+', stem):
            if P_NOISE_EXPOSURE_ANIMAL.match(token) and token not in seen:
                seen.add(token)
                animal_ids.append(token)
        if not animal_ids:
            return None

        return {
            'animal_id': animal_ids,
            'date': date,
            'experiment_type': self.experiment,
        }

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


class MEMR(CFTSDataTypeDescription):
    """Common outputs shared by all three MEMR (middle-ear muscle reflex)
    experiment types. See ``cftsdata.summarize_memr`` for how these files
    are generated."""

    experiment = None

    @pdf_callback('MEMR PDF')
    def get_memr_pdf(self):
        return self._get_pdf('MEMR.pdf')

    @pdf_callback('MEMR Total PDF')
    def get_memr_total_pdf(self):
        return self._get_pdf('MEMR_total.pdf')

    @pdf_callback('Probe PDF')
    def get_probe_pdf(self):
        return self._get_pdf('probe.pdf')

    @pdf_callback('Elicitor PDF')
    def get_elicitor_pdf(self):
        return self._get_pdf('elicitor.pdf')


class MEMRInterleavedClick(MEMR):
    """Adds the epoch-waveform and HT2-threshold outputs produced by the
    interleaved-click paradigm (see ``cftsdata.summarize_memr_th``)."""

    experiment = 'memr_interleaved_click'

    @pdf_callback('Epoch Waveform PDF')
    def get_epoch_waveform_pdf(self):
        return self._get_pdf('epoch waveform.pdf')

    @pdf_callback('HT2 Threshold Diagnostics PDF')
    def get_ht2_threshold_diagnostics_pdf(self):
        return self._get_pdf('HT2 threshold diagnostics.pdf')

    @dict_callback('HT2 Threshold', 'fa-arrows-down-to-line')
    def get_ht2_threshold(self):
        import json
        info = json.loads(self.get_file('HT2 threshold.json').read_text())
        return {
            'Mean threshold (dB SPL)': f'{info["mean_threshold"]:.1f}',
            'Max threshold (dB SPL)': f'{info["max_threshold"]:.1f}',
            'Mean asymptote (dB)': f'{info["mean_asymptote"]:.2f}',
            'Max asymptote (dB)': f'{info["max_asymptote"]:.2f}',
            'HT2 2-sample threshold (dB SPL)': f'{info["t2_2samp_threshold"]:.1f}',
        }


class MEMRSimultaneousChirp(MEMRInterleavedClick):
    """Same output layout as :class:`MEMRInterleavedClick`."""

    experiment = 'memr_simultaneous_chirp'


class MEMRSweepClick(MEMR):

    experiment = 'memr_sweep_click'

    @pdf_callback('MEMR Block PDF')
    def get_memr_block_pdf(self):
        return self._get_pdf('MEMR_block.pdf')

    @pdf_callback('Diagnostics PDF')
    def get_diagnostics_pdf(self):
        return self._get_pdf('diagnostics.pdf')

    @pdf_callback('Threshold PDF')
    def get_threshold_pdf(self):
        return self._get_pdf('MEMR_threshold.pdf')

    @dict_callback('Threshold Stats', 'fa-arrows-down-to-line')
    def get_threshold_stats(self):
        import json
        info = json.loads(self.get_file('MEMR_threshold_stats.json').read_text())
        return {
            'Threshold (click #)': f'{info["threshold"]:.1f}',
            'Center (click #)': f'{info["center"]:.1f}',
            'Width (clicks)': f'{info["width"]:.1f}',
            'Max amplitude (dB)': f'{info["amplitude_max"]:.2f}',
            'Mean amplitude (dB)': f'{info["amplitude_mean"]:.2f}',
        }
