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

- `registry.py` — `DESCRIPTION_CLASSES`, the only thing `colony-manager`
  imports. A class isn't usable until it's listed here under a
  `'<Family>: <Name>'` key.
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

Use the `gerbil-manager` conda env (`cftsdata`/`abr`/`psidata` are
installed there) — from git-bash, `conda activate` needs
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
