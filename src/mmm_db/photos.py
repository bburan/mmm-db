"""Description classes for free-form photos attached to animals."""
import re
from datetime import datetime

from colony_manager.datatypes import DataTypeDescription


P_ANIMAL_PHOTO = re.compile(
    r'^(?P<animal_id>.+?)\s+-\s+'
    r'(?P<date>\d{8})\s+-\s+'
    r'(?P<note>.+)$'
)


P_DISSECTION_NOTES = re.compile(
    r'^(?P<ids>.+?)\s+.*?$'
)


class AnimalPhotoDescription(DataTypeDescription):
    """Description for animal photo files.

    Filename convention::

        <animal_id> - <date> - <note>.jpg

    where ``<date>`` is ``YYYYMMDD``. For example:
    ``A001 - 20260415 - cage change.jpg``. The
    ``<animal_id>`` segment may contain multiple IDs separated by
    ``,``, ``+``, ``&`` or ``|`` for photos that apply to several
    animals (e.g. litter portraits).

    Configure a DataType row with ``target_type='animal'`` and
    ``description_class='mmm_db.photos.AnimalPhotoDescription'`` to use
    this with the sync framework.
    """

    def parse(self):
        """Parse an animal-photo filename into metadata.

        Returns
        -------
        dict or None
            Keys: ``animal_id`` (list of strings), ``date`` (datetime.date),
            ``note`` (str or None). Returns ``None`` for files that don't
            match the convention.
        """
        if self.path.suffix.lower() != '.jpg':
            return None
        match = P_ANIMAL_PHOTO.match(self.path.stem)
        if match is None:
            return None
        info = match.groupdict()
        try:
            info['date'] = datetime.strptime(info['date'], '%Y%m%d').date()
        except ValueError:
            return None
        info['animal_id'] = [
            a.strip() for a in re.split(r'[,+&|]', info['animal_id'])
            if a.strip()
        ]
        if not info['animal_id']:
            return None
        info['note'] = info['note'].strip() or None
        return info

    def hash_files(self):
        """Return the JPEG itself for hashing.

        Returns
        -------
        list of Path
        """
        if self.path.exists():
            return [self.path]
        return []


class EarDissectionNotesDescription(DataTypeDescription):
    """Description for ear-dissection-notes images.

    Filename convention::

        <id1>[L|R] <id2>[L|R] ... - <note>.jpg

    Each whitespace-separated ID token before the ``-`` separator may
    end in ``L`` (left ear) or ``R`` (right ear); tokens without an
    ``L``/``R`` suffix are still recorded as candidate animals but
    won't match a specific Ear. For example
    ``G014-4L G018-3R - dissection notes.jpg`` parses to two animals
    with their respective sides.

    Configure a DataType row with ``target_type='ear'`` and
    ``description_class='mmm_db.photos.EarDissectionNotesDescription'``.
    """

    def parse(self):
        """Parse a multi-animal ear-dissection filename.

        Returns
        -------
        dict or None
            ``animal_id`` is a list of strings; ``side`` is a parallel
            list whose entries are ``'Left'``, ``'Right'``, or ``None``
            for tokens without a side suffix. Returns ``None`` when no
            token has a usable side.
        """
        if self.path.suffix.lower() != '.jpg':
            return None
        match = P_DISSECTION_NOTES.match(self.path.stem)
        if match is None:
            return None
        tokens = match.group('ids').split()
        if not tokens:
            return None

        animal_ids = []
        sides = []
        for tok in tokens:
            last = tok[-1].upper()
            if last == 'L':
                animal_ids.append(tok[:-1])
                sides.append('Left')
            elif last == 'R':
                animal_ids.append(tok[:-1])
                sides.append('Right')
            else:
                animal_ids.append(tok)
                sides.append(None)

        if not any(sides):
            return None

        return {
            'animal_id': animal_ids,
            'side': sides,
        }

    def hash_files(self):
        if self.path.exists():
            return [self.path]
        return []
