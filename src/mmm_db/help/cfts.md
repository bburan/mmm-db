# CFTS physiology

Closed-field and free-field physiology collected with psiexperiment: ABR,
MLR/LLR, DPOAE, DPgram, EFR, MEMR, in-ear calibration and noise exposure.

## One run, one folder

Every run is a folder whose name ends in the raw experiment type:

```
20250819-091648 Sean G011-1 left abr_io
```

Read left to right: timestamp, experimenter, animal, ear, and the
experiment type that decides which description class claims the folder.
Every output file inside is prefixed with the folder's own name, which is
how the preview buttons find them.

Two consequences worth knowing:

- **The name must *end* at the experiment type.** A trailing note —
  `... abr_io retest` — parses fine but matches no description class, so
  the folder is never imported at all. It does not show up as an unmatched
  file either; nothing knows it exists.
- **A folder anywhere under a path containing `_exclude` is ignored.** That
  is the way to take a run out of circulation without deleting it.

Each folder is attached to an **animal event**. If no event exists for that
animal on that date, the file lands on
[Unmatched Data Files](/help/unmatched-data), where *Auto-create events*
can make one.

## What each experiment type gives you

| Experiment | Preview buttons |
|---|---|
| **ABR I/O** (tone, click, free-field) | Waveforms PDF, EEG spectrum PDF, ECG PDF, ABRpresto diagnostics, and a **Thresholds** table |
| **MLR/LLR I/O** (tone, click, free-field) | the waveform PDF under its own name |
| **DPOAE I/O** | I/O PDF, Thresholds PDF |
| **DPgram** | DPgram PDF, Mic spectrum PDF |
| **EFR** (SAM / RAM, free-field, legacy) | EEG spectrum PDF, Stimulus SPL PDF, ECG PDF, an **EFR response** table and a **processing settings** table |
| **MEMR** (interleaved click, simultaneous chirp) | MEMR, MEMR total, probe and elicitor PDFs, plus epoch waveform, HT2 threshold diagnostics and an **HT2 threshold** table |
| **MEMR** (sweep click) | MEMR, MEMR total, probe, elicitor, MEMR block, diagnostics and threshold PDFs, plus a **threshold stats** table |
| **In-ear calibration** | Calibration PDF |
| **Noise exposure** | Noise exposure PDF and a **parameters** table (requested and measured level, band, correction factor) |

A button that errors when clicked means the processing step that produces
that file has not been run for this dataset. Several of these outputs come
from optional extra passes — MEMR sweep thresholds in particular — so an
error there is expected rather than a fault.

## Noise exposures cover several animals

Noise exposure is routinely run on a whole group, and the folder name lists
every animal:

```
20250819-091648 Sean G011-1,G011-2 103 dB SPL 2h noise_exposure
```

IDs may be separated by spaces or commas and need not sit next to the
experimenter. One file row is created and linked to *every* animal named,
so the same exposure appears on each animal's page. This is also why
noise-exposure files show up in the **Data Files Shared Across Animals**
panel on the [study page](/help/study-detail) — that is correct, not a
linking mistake.

## ABR analysis status

ABR I/O is the one physiology type that reports whether it has been
analyzed. Analysis means peak-picked waveforms, saved as one
`*-analyzed.txt` per frequency per rater.

On [Needs Analysis](/help/unrated-data) an ABR run reads as:

- **`0 of N frequencies rated`** — no picks at all.
- **a rater list** — who has picked it. A run needing two independent
  raters shows one name until the second is done, so the Raters column is
  how you find work waiting on a second opinion.
- **analyzed** — every frequency has picks.

Click-stimulus ABR is handled alongside tone ABR; its picks are labelled
`click` rather than a frequency.

The analysis timestamp is taken from the pick files themselves, so the
[scoreboard](/help/analysis-scoreboard) credits whoever's name is in the
filename.
