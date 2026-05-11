from colony_manager.datatypes import DataTypeDescription


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
