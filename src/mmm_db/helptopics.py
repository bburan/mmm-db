"""Help pages this package contributes to colony-manager's help section.

`colony-manager` ships help for its own pages — the animal list, the
histology grid, the settings screens. It cannot ship help for *what the
data is*, because it does not know: ABR, synaptograms and go/no-go
sessions only exist here. So the registry module may export a
``HELP_TOPICS`` sequence, and colony-manager merges those topics into its
help index alongside its own (labelled *plugin*, since they travel with
this package rather than with the app).

Two directions of linking:

* From the index — every topic below is listed under its ``section``.
* From the data itself — a ``DataTypeDescription`` subclass that sets
  ``help_topic = '<slug>'`` gets a ``?`` button next to every file of that
  type, and next to its entry in Settings → Data Types.

The bodies are Markdown files in ``help/``, read on each request, so
editing one shows up without a restart. The subset colony-manager renders
covers headings, paragraphs, nested lists, fenced code, blockquotes, pipe
tables and inline emphasis/code/links — see
``colony_manager_gui.helpdocs``.

Cross-links use ordinary in-app paths (``/help/<slug>``), which work from
either side: colony-manager's own topics link here by slug, and these link
back to its pages the same way.

To add a topic: drop a ``.md`` file in ``help/`` and add an entry below.
Slugs are lowercase-and-hyphens, unique across the whole deployment, and
are what ``help_topic`` points at — so prefix them with ``mmm-db-`` to
stay clear of colony-manager's own.
"""
from pathlib import Path


HELP_DIR = Path(__file__).parent / 'help'

#: Grouping these topics appear under in colony-manager's help index.
SECTION = 'Experiment data'


HELP_TOPICS = [
    {
        'slug': 'mmm-db-overview',
        'title': 'Experiment data in this lab',
        'summary': 'The four families of data, and which ones report their '
                   'own analysis status.',
        'section': SECTION,
        'order': 10,
        'path': HELP_DIR / 'overview.md',
    },
    {
        'slug': 'mmm-db-cfts',
        'title': 'CFTS physiology',
        'summary': 'ABR, DPOAE, EFR, MEMR, noise exposure — run folders, '
                   'outputs and ABR analysis status.',
        'section': SECTION,
        'order': 20,
        'path': HELP_DIR / 'cfts.md',
    },
    {
        'slug': 'mmm-db-histology',
        'title': 'Histology images',
        'summary': 'IHC/OHC counts, synaptograms and cochleograms, and what '
                   'partial analysis means for each.',
        'section': SECTION,
        'order': 30,
        'path': HELP_DIR / 'histology.md',
    },
    {
        'slug': 'mmm-db-abts',
        'title': 'Behavioural data',
        'summary': 'Go/no-go sessions and the outputs they produce.',
        'section': SECTION,
        'order': 40,
        'path': HELP_DIR / 'abts.md',
    },
    {
        'slug': 'mmm-db-photos',
        'title': 'Photos and dissection notes',
        'summary': 'Naming conventions, and the only file types that can be '
                   'uploaded from the interface.',
        'section': SECTION,
        'order': 50,
        'path': HELP_DIR / 'photos.md',
    },
    {
        'slug': 'mmm-db-filenames',
        'title': 'Why a file did not import',
        'summary': 'Working back from a missing or unmatched file to the '
                   'filename that caused it.',
        'section': SECTION,
        'order': 60,
        'path': HELP_DIR / 'filenames.md',
    },
]
