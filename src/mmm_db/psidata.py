from colony_manager.datatypes import DataTypeDescription

import pandas as pd


def summarize_stretches(s: pd.Series) -> str:
    """
    Summarizes consecutive identical values in a pandas Series.
    """
    if s.empty:
        return ""

    # 1. Identify where the value changes from the previous row
    # s.ne(s.shift()) returns True whenever a value differs from the one before it
    # .cumsum() creates a unique ID for each "stretch" of identical values
    blocks = s.ne(s.shift()).cumsum()

    # 2. Group by those blocks and aggregate the first value and the count
    summary = s.groupby(blocks).agg(['first', 'size'])

    # 3. If there is only one block, just return the value (per your requirement)
    if len(summary) == 1:
        return str(summary['first'].iloc[0])

    # 4. Otherwise, format the blocks into a readable string
    parts = [f"{val} ({count})" for val, count in zip(summary['first'], summary['size'])]

    return ", ".join(parts)


class PSIDataTypeDescription(DataTypeDescription):

    experiment = None

    def _parse(self, filename):
        raise NotImplementedError

    def parse(self):
        """Parse the folder name for animal/date metadata.

        Returns
        -------
        dict or None
            Parsed metadata with keys ``'animal_id'``, ``'date'``, etc.
            Returns ``None`` if the path does not look like an ABR I/O folder.
        """
        if '_exclude' in str(self.path):
            return None
        if not self.path.stem.endswith(self.experiment):
            return None
        try:
            return self._parse(self.path)
        except ValueError:
            return None

    def hash_files(self):
        """Return the psiexperiment dataset as the identity file for this
        dataset.

        Returns
        -------
        list of Path
            The ABR zip file if it exists.
        """
        return [self.path / f'{self.path.name}.zip']

    def _get_pdf(self, suffix):
        """Return the path to the pre-generated PDF.

        Returns
        -------
        Path
        """
        return self.path / f'{self.path.name} {suffix}'
