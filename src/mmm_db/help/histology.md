# Histology images

Three kinds of histology data, each with its own way of saying whether it
has been analyzed.

## IHC and OHC counts

One row per imaged region, attached to a **confocal image** — so an image
record must exist at the right frequency before the file can link. Files
come from either era of acquisition:

- **Zeiss**: `..._IHC-OHC_<freq>_kHz.czi`, one file per image.
- **Leica**: `..._IHC_OHC_<freq>_kHz.ims`, split out of the ear's whole-ear
  `.lif` archive. The `.lif` itself is never imported — it holds every
  frequency for the ear, and one row per file is what the grid needs.

Where a `.czi` and an `.ims` of the same name sit side by side, only the
`.czi` is taken: those `.ims` files are conversions of the originals.

The **IHC and OHC counts** button plots the analysis.

### What analyzed, partial and unrated mean

Cell picks live in an `_analysis.json` beside the image. A complete count
traces four spirals — IHC, OHC1, OHC2, OHC3. A row counts as done when its
spiral is traced **or** when it has been explicitly marked unratable
(tissue missing, for instance). A traced spiral with zero cells is valid:
that region has no surviving hair cells.

So on [Needs Analysis](/help/unrated-data):

| Note | Meaning |
|---|---|
| `Not analyzed` | no sidecar yet |
| `Analysis started, no spirals traced` | sidecar exists, nothing traced |
| `Partial — no spiral for OHC2, OHC3` | some rows still to do — the note names them |
| `Analyzed — IHC 12, OHC 40/38/41` | all four rows done, with counts; `NaN` marks an unratable row |

Searching the **Note contains** box for `Partial OHC1` is the way to pull
out every image missing one particular row.

## Synaptograms

One row per image, again attached to a confocal image. Two formats:

- **napari / Zeiss**: `..._<freq>_kHz.czi` with an analyzed `.syn` sidecar.
- **imaris / Leica**: `..._<freq>_kHz_<rep>.ims` with an analyzed
  `..._IHC.ims` sidecar.

Two buttons: the raw **Image**, and the analyzed **Synaptogram**.

A napari synaptogram counts as analyzed once both the `IHCs` and
`CtBP2 masked points` layers *exist*. Presence, not count, is the test — a
layer can legitimately be empty where a region has no ribbons, the same
principle as an empty spiral in a cell count. For imaris, the analyzed
export only exists once the work is done, so its presence is the signal.

Files under a path containing `imaris`, `napari` or `_exclude` are skipped;
those directories hold working copies, not the images of record.

## Cochleograms

A cochleogram is a **folder**, attached to the **ear** rather than to one
image. A folder qualifies when its name starts with an animal ID and side
(`B008-CL...`) *and* it directly contains a `*_frequency_map.pdf`.

That "contains the map" rule is what keeps nested cochleogram folders
unambiguous — each resolves to the ear named by its own folder — and what
makes sibling folders like `original map` or `exclude - ...` correctly
ignored.

One button: the **Frequency Map** PDF. The raw pieces and analysis files
live alongside it in the same folder.

Cochleograms do not report analysis status.

## When an image will not link

An image file that parses but finds no confocal image record lands in the
**Unmatched Images** card on that [ear's page](/help/ear-detail), and as a
red hatched square on the [histology grid](/help/histology-grid). The
cause is nearly always that no image row exists yet at that frequency and
image type — create it on the ear page and the file links itself.
