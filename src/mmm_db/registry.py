from mmm_db import abtsdata
from mmm_db import cftsdata
from mmm_db import images
from mmm_db import photos


DESCRIPTION_CLASSES = {
    'ABTS: Modulation GoNogo': abtsdata.ModulationGoNogo,
    'ABTS: Gap Detection GoNogo': abtsdata.GapDetectionGoNogo,
    'CFTS: ABR IO': cftsdata.ABRIO,
    'CFTS: DPOAE IO': cftsdata.DPOAEIO,
    'CFTS: EFR (SAM)': cftsdata.EFRSAM,
    'CFTS: EFR (RAM)': cftsdata.EFRRAM,
    'CFTS: IEC': cftsdata.IEC,
    'CFTS: Noise Exposure': cftsdata.NoiseExposure,
    'Histology: Synaptogram': images.Synaptogram,
    'Histology: Synaptogram (Analysis)': images.SynaptogramAnalysis,
    'Histology: IHC and OHC counts': images.IHCOHCCount,
    'Histology: IHC and OHC counts (Analysis)': images.IHCOHCCountAnalysis,
    'Photos: Animal': photos.AnimalPhoto,
    'Photos: Ear Dissection Notes': photos.EarDissectionNotes,
}
