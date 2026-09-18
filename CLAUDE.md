# CLAUDE.md

Guidance for working in this repo.

## What this is

`mmm-db` provides the `DataTypeDescription` plugin classes for the
[`colony-manager`](../colony-manager) Flask app's data-file sync/viewer
system. `colony-manager` points its `COLONY_MANAGER_DESCRIPTION_REGISTRY`
env var at `mmm_db.registry`, whose `DESCRIPTION_CLASSES` dict maps short
opaque keys (stored in the DB) to `DataTypeDescription` subclasses defined
here. See `colony-manager`'s `CLAUDE.md` ("Description-class plugin
system") for how the framework side consumes this; this file covers the
`mmm_db` side — mainly how to add support for a new experiment type.

## Layout

- `registry.py` — `DESCRIPTION_CLASSES` plus a re-export of
  `HELP_TOPICS`; the only module `colony-manager` imports. A class isn't
  usable until it's listed here under a `'<Family>: <Name>'` key.
- `helptopics.py` + `help/*.md` — the help pages this package contributes
  to colony-manager's help section. See "Help pages" below.
- `psidata.py` — `PSIDataTypeDescription` base class. `parse()` matches
  folders whose name ends in `self.experiment` and delegates to
  `cftsdata.dataset.parse_psi_filename` for animal/date/side metadata.
  `hash_files()` uses the dataset's `.zip`. `get_file(suffix)` /
  `_get_pdf(suffix)` resolve sibling output files named
  `"<folder name> <suffix>"` (psiexperiment's convention: every output
  file in a run's folder is prefixed with the folder's own name).
- `cftsdata.py` — `CFTSDataTypeDescription` subclasses, one per cfts
  `experiment_type` (`abr_io`, `abr_io_click`, `dpoae_io`, `dpgram`,
  `memr_interleaved_click`, `memr_simultaneous_chirp`, `memr_sweep_click`,
  `efr_ram_epoch`, `efr_sam_epoch`, `noise_exposure`,
  `inear_speaker_calibration_chirp`, ...).
- `abtsdata.py`, `images.py`, `photos.py` — other `target_type` families
  (behavior, histology images, photos).
- `scripts/check_psi_filenames.py` — scans the physiology run folders and
  flags names `parse_psi_filename` can't read (typically a doubled space),
  names that don't *end* at the experiment type (a trailing note, which
  parses but matches no description class), and names that disagree with
  the `<animal>/<date>/` folders they sit in. Reports only; renaming a
  folder changes its `relative_path` and wants a `flask data sync`
  afterwards. Run it after adding an experiment type — its
  `unregistered-type` line lists what's on disk but not in `registry.py`.

  The tree to scan comes from the `DataLocation` rows attached to CFTS
  datatypes, via `DATABASE_URL`, so it needs no arguments on either the
  dev machine (`M:/physiology/animals`) or the server
  (`/volume1/data/physiology/animals`). On the server:

  ```sh
  ssh mmm 'cd /volume2/docker/flask && /usr/local/bin/docker-compose \
      exec -T web python /app/mmm-db/scripts/check_psi_filenames.py --quiet'
  ```

- `scripts/list_analysis_hosts.py` — reports which machine each IHC/OHC
  cell-count analysis was done on, read from the `meta.history` block in
  each `*_analysis.json` (`{user, host, modified}` per save). Older
  sidecars predate that block and report `-` rather than being skipped;
  at last run 307 of 1691 analyses carried a host. Same
  `DataLocation`-via-`DATABASE_URL` root resolution as
  `check_psi_filenames.py`.

## Help pages

`registry.py` exports `HELP_TOPICS` (defined in `helptopics.py`) alongside
`DESCRIPTION_CLASSES`. colony-manager merges those topics into its own
`/help/` index under the *Experiment data* section, labelled *plugin*, and
each description class's `help_topic` attribute puts a `?` button on every
file of that type and on its row in Settings → Data Types. The framework
side is documented under "In-app help" in colony-manager's `CLAUDE.md`.

Bodies are Markdown files in `help/`, read on each request (no restart
needed). colony-manager renders a **subset**: headings, paragraphs, nested
lists, fenced code, blockquotes, pipe tables, and inline
emphasis/code/links. Anything fancier is escaped and shown literally, so
check a new page in the app rather than assuming a Markdown feature works.
Cross-links use in-app paths (`/help/<slug>`) and work in both directions.

Adding a topic: drop a `.md` in `help/`, add an entry to `HELP_TOPICS`
(slug prefixed `mmm-db-` to stay clear of colony-manager's own), and point
the relevant classes' `help_topic` at it. Put `help_topic` **after** the
class docstring — before it, the docstring stops being `__doc__`.

When adding an experiment type, say what the new type's callbacks actually
show in `help/cfts.md`; the table there is what a user reads to know
whether a missing PDF means "not run yet" or "something is wrong".

## Adding a new CFTS experiment type

1. Find a real example on disk, e.g.
   `M:\physiology\animals\<animal>\<date>\<timestamp> <experimenter> <animal> <side> ... <experiment_type>\`
   — the folder name ends in the raw `experiment_type` string (e.g.
   `memr_sweep_click`), and every file inside is named
   `"<folder name> <suffix>"`.
2. Read the matching `summarize_*.py` in the separate
   [`cftsdata`](../cftsdata) repo to see what suffixes/columns/JSON keys
   that experiment type actually produces — don't guess from the folder
   listing alone (e.g. `MEMR.csv` vs `MEMR_total.csv` vs
   `MEMR_amplitude.csv` all exist and mean different things).
3. Add `class Foo(CFTSDataTypeDescription): experiment = '<experiment_type>'`
   in `cftsdata.py`.
4. For each pre-generated output worth surfacing, add a callback:
   - `@pdf_callback('Label')` → `return self._get_pdf('suffix.pdf')`
   - `@dict_callback('Label', icon)` → read a `*.json` sidecar via
     `json.loads(self.get_file('suffix.json').read_text())`
   - `@plot_callback('Label')` for an interactive Bokeh/Plotly view — see
     `ABRIO.load_waveforms` for the heavy example; usually not needed.
5. Register it in `registry.py`'s `DESCRIPTION_CLASSES` under a
   `'CFTS: <Name>'` key.
6. Share a base class across variants that produce identical output files
   (e.g. `MEMRSimultaneousChirp` subclasses `MEMRInterleavedClick` and
   only overrides `experiment`) rather than inventing a one-off mixin —
   don't add an intermediate abstract layer unless 3+ concrete classes
   actually need it.

## Verifying against real data

There's no test suite in this repo. Verify a new/changed class by
instantiating it directly against a real folder and exercising it:

```python
from mmm_db import cftsdata
from pathlib import Path
obj = cftsdata.Foo(Path(r'M:\physiology\animals\...\...experiment_type'))
obj.parse()          # should return metadata, not None
obj.hash_files()     # should point at an existing .zip
for name, info in obj.get_callbacks().items():
    result = obj.invoke_callback(name)
    # for pdf callbacks: result.exists() should be True
```

Use the `colony-manager` conda env (`cftsdata`/`abr`/`psidata`/`cochleogram`
are installed there, as are `colony_manager` and `mmm_db` themselves,
editable) — from git-bash, `conda activate` needs
`source /c/Users/buran/bin/anaconda3/etc/profile.d/conda.sh` first. Pass
Windows-style paths (`M:\...`) to Python, not the git-bash `/m/...`
mount — Python on Windows doesn't resolve the latter.

## Gotchas

- **Click-stimulus ABR** (`abr_io_click`) analyzed-picks filenames use
  `-click-` instead of `-{freq}kHz-`. `cftsdata.summarize_abr.load_abr_waveforms`
  maps click stimuli to a sentinel frequency of `-1` (`abr.ABRStim.CLICK.value`).
  `cftsdata.py`'s `CLICK_FREQ_HZ` constant, `_load_all_analyzed`'s regex,
  and `_format_freq_label` all have to agree on this sentinel, or
  click-ABR datasets silently show up as "unrated" / mislabeled instead
  of erroring loudly.
- Route handlers in `colony-manager` wrap every `invoke_callback()` call
  in a broad `except Exception`, so a callback that raises (missing file,
  bad JSON) degrades to a UI error rather than a 500 — safe to add
  callbacks for files a given processing pipeline step might not have
  been run yet (e.g. `MEMRSweepClick`'s threshold PDF/stats, which come
  from an optional separate `summarize_memr_sweep_th.py` pass).

## Known issues

- **`B029-2L` count images fail to load** — 5 of its 7 series raise
  `Mismatch between channels in filename and file (GluR2, CtBP2,
  MyosinVIIa != Channel 0)` out of
  `cochleogram.util.channels_from_filename`, so their "IHC and OHC
  counts" plot errors instead of rendering.

  Not a conversion bug: the `.ims` files match the `.lif` channel for
  channel. `5p7`, `11p3`, `16p0`, `32p0` and `45p3` were *acquired*
  single-channel (AF647 only) while the folder name promises
  `GluR2-CtBP2-MyosinVIIa`; `8p0` and `22p6` have all three and load
  fine. `lif_to_ims.py` copied faithfully what was there.

  All five nonetheless carry an `_analysis.json`, so they were analyzed
  in that state — whatever is decided, those picks should survive it.
  Note also that the `.lif` holds an `IHC_OHC_11p3_kHzB` series with the
  full three channels (a re-scan), and its converted `.ims` is parked in
  the folder's `_exclude/`, i.e. someone deliberately kept the
  single-channel `11p3` over it.

  Three ways out, in rough order of preference — all of them data
  decisions rather than something to paper over in `images.py`:

  1. Rename the folder to the markers actually acquired, so the
     filename stops promising channels the files never had. Changes the
     `relative_path` of every row under it, so it wants a `flask data
     sync` and a check for orphans afterwards.
  2. Relax `channels_from_filename` upstream to accept a subset of the
     declared markers. Widest blast radius — it is shared with the
     analysis app.
  3. Swap in the `_exclude`-ed `11p3B` re-scan for `11p3`, which fixes
     exactly one of the five and needs its analysis redone.
