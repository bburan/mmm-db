from mmm_db import abtsdata
from mmm_db import cftsdata
from mmm_db import images
from mmm_db import photos


DESCRIPTION_CLASSES = {
    'ABTS: Modulation GoNogo': abtsdata.ModulationGoNogo,
    'ABTS: Gap Detection GoNogo': abtsdata.GapDetectionGoNogo,
    'CFTS: ABR IO': cftsdata.ABRIO,
    'CFTS: ABR IO (Click)': cftsdata.ABRIOClick,
    'CFTS: MLR/LLR IO (freefield, tone)': cftsdata.MLRLLRIOFreeField,
    'CFTS: MLR/LLR IO (freefield, click)': cftsdata.MLRLLRIOClickFreeField,
    'CFTS: DPOAE IO': cftsdata.DPOAEIO,
    'CFTS: DPgram': cftsdata.DPGram,
    'CFTS: EFR (SAM)': cftsdata.EFRSAM,
    'CFTS: EFR (RAM)': cftsdata.EFRRAM,
    'CFTS: IEC': cftsdata.IEC,
    'CFTS: MEMR (Interleaved Click)': cftsdata.MEMRInterleavedClick,
    'CFTS: MEMR (Simultaneous Chirp)': cftsdata.MEMRSimultaneousChirp,
    'CFTS: MEMR (Sweep Click)': cftsdata.MEMRSweepClick,
    'CFTS: Noise Exposure': cftsdata.NoiseExposure,
    'Histology: Synaptogram': images.Synaptogram,
    'Histology: Synaptogram (Analysis)': images.SynaptogramAnalysis,
    'Histology: IHC and OHC counts': images.IHCOHCCount,
    'Histology: IHC and OHC counts (Analysis)': images.IHCOHCCountAnalysis,
    'Photos: Animal': photos.AnimalPhoto,
    'Photos: Ear Dissection Notes': photos.EarDissectionNotes,
}
