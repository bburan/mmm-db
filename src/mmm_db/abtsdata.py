from colony_manager.datatypes import (
    plot_callback, pdf_callback,
)

from .psidata import PSIDataTypeDescription
from abtsdata.dataset import parse_abts_filename


class ABTSDataTypeDescription(PSIDataTypeDescription):

    def _parse(self, filename):
        return parse_abts_filename(filename)


class ModulationGoNogo(ABTSDataTypeDescription):
    experiment = 'modulation-gonogo'

    @pdf_callback('Performance')
    def get_io_pdf(self):
        return self._get_pdf('performance.pdf')
