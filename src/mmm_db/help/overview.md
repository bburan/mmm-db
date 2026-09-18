# Experiment data in this lab

Colony Manager does not know anything about hearing research on its own.
Everything it can say about an ABR run or a confocal image comes from
`mmm_db`, a companion package that supplies one **description class** per
kind of experiment. A description class knows three things:

- how to read an animal, a date, a side, a frequency out of a filename;
- which file identifies the dataset, so a move is recognised as a move
  rather than as a new file;
- which pre-generated outputs are worth a button in the interface.

That is why the file rows in Colony Manager show different buttons for an
ABR than for a cochleogram, and why some kinds of data can report whether
they have been analyzed and others cannot.

## The four families

| Family | What it covers | Attaches to |
|---|---|---|
| **CFTS** | physiology run folders — ABR, MLR/LLR, DPOAE, DPgram, EFR, MEMR, in-ear calibration, noise exposure | an animal event |
| **ABTS** | behavioural go/no-go runs | an animal event |
| **Histology** | synaptograms, IHC/OHC counts, cochleograms | a confocal image, or an ear |
| **Photos** | animal photos and ear dissection notes | an animal, or an ear |

Each family has its own topic; this page is the shared background.

## Folders versus files

CFTS and ABTS data are **folders**. One psiexperiment run produces a
directory whose name ends in the experiment type, and every file inside is
named after that directory. Colony Manager records the folder as one file
row, and the preview buttons reach into it for the individual outputs.

Histology images and photos are **files** — one row per image.

A cochleogram is a folder again, but keyed on the ear rather than on a
run.

This distinction is a property of the experiment, not a setting: it is why
pointing a data type at the wrong level produces a sync that reports
success and imports nothing.

## Why a file is or is not analyzed

Three kinds of data can report their own analysis state, and they are the
ones that appear on **Needs Analysis** and the **Analysis Scoreboard**:

- **ABR I/O** — from the `*-analyzed.txt` pick files, one per frequency
  per rater.
- **IHC/OHC counts** — from the `_analysis.json` sidecar beside the image.
- **Synaptograms** — from the analyzed sidecar beside the image.

Everything else — DPOAE, EFR, MEMR, noise exposure, behaviour, photos —
has no notion of "analyzed" here and never appears in those views. That is
not an omission; there is nothing in those datasets for the app to read.

## Where the data lives

Physiology runs are under the physiology animals tree, one folder per
animal per date. Histology images are under the histology tree, organised
by ear. The exact roots differ between the workstation and the server and
are configured per data type in
[Settings → Data Types](/help/settings-datatypes).
