"""The registry colony-manager loads: description classes, plus help.

``COLONY_MANAGER_DESCRIPTION_REGISTRY`` points at this module. colony-manager
reads two names from it:

* ``DESCRIPTION_CLASSES`` — the parsers, keyed by the short opaque string
  stored in ``DataType.description_class``.
* ``HELP_TOPICS`` — the help pages this package contributes to the app's
  help section (see :mod:`mmm_db.helptopics`). Optional; a registry without
  it simply contributes no topics.
"""
from mmm_db import abtsdata
from mmm_db import cftsdata
from mmm_db import images
from mmm_db import photos
from mmm_db.helptopics import HELP_TOPICS  # noqa: F401  (read by colony-manager)


DESCRIPTION_CLASSES = {
    'ABTS: Modulation GoNogo': abtsdata.ModulationGoNogo,
    'ABTS: Gap Detection GoNogo': abtsdata.GapDetectionGoNogo,
    'CFTS: ABR IO': cftsdata.ABRIO,
    'CFTS: ABR IO (Click)': cftsdata.ABRIOClick,
    'CFTS: ABR IO (Freefield)': cftsdata.ABRIOFreeField,
    'CFTS: MLR/LLR IO (tone)': cftsdata.MLRLLRIO,
    'CFTS: MLR/LLR IO (click)': cftsdata.MLRLLRIOClick,
    'CFTS: MLR/LLR IO (freefield, tone)': cftsdata.MLRLLRIOFreeField,
    'CFTS: MLR/LLR IO (freefield, click)': cftsdata.MLRLLRIOClickFreeField,
    'CFTS: DPOAE IO': cftsdata.DPOAEIO,
    'CFTS: DPgram': cftsdata.DPGram,
    'CFTS: EFR (SAM)': cftsdata.EFRSAM,
    'CFTS: EFR (RAM)': cftsdata.EFRRAM,
    'CFTS: EFR (SAM, freefield)': cftsdata.EFRSAMFreeField,
    'CFTS: EFR (RAM, freefield)': cftsdata.EFRRAMFreeField,
    'CFTS: EFR (SAM, legacy)': cftsdata.EFRSAMLegacy,
    'CFTS: EFR (RAM, legacy)': cftsdata.EFRRAMLegacy,
    'CFTS: IEC': cftsdata.IEC,
    'CFTS: MEMR (Interleaved Click)': cftsdata.MEMRInterleavedClick,
    'CFTS: MEMR (Simultaneous Chirp)': cftsdata.MEMRSimultaneousChirp,
    'CFTS: MEMR (Sweep Click)': cftsdata.MEMRSweepClick,
    'CFTS: Noise Exposure': cftsdata.NoiseExposure,
    'Histology: Synaptogram': images.Synaptogram,
    'Histology: IHC and OHC counts': images.IHCOHCCount,
    'Histology: Cochleogram': images.Cochleogram,
    'Photos: Animal': photos.AnimalPhoto,
    'Photos: Ear Dissection Notes': photos.EarDissectionNotes,
}
