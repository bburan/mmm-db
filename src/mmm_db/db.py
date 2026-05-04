import re
from pathlib import Path

from .dataset import parse_psi_filename


def parse_abr_io_filename(relative_path, location):
    path = Path(location.base_path) / relative_path
    if not path.stem.endswith('abr_io'):
        return None
    return parse_psi_filename(path)
