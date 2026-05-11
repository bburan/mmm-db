from mmm_db import abtsdata
from mmm_db import cftsdata
from mmm_db import images
from mmm_db import photos


DESCRIPTION_CLASSES = {
    'ABTS: Modulation GoNogo': abtsdata.ModulationGoNogo,
    'CFTS: ABR IO': cftsdata.ABRIO,
    'CFTS: DPOAE IO': cftsdata.DPOAEIO,
    'CFTS: IEC': cftsdata.IEC,
    'Histology: Synaptogram': images.Synaptogram,
    'Photos: Animal': photos.AnimalPhoto,
    'Photos: Ear Dissection Notes': photos.EarDissectionNotes,
}
