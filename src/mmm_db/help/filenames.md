# Why a file did not import

Nearly every data-file problem in this deployment comes back to a
filename. The parsers are deliberately strict: a name that is *almost*
right is rejected rather than guessed at, because a wrong guess attaches
real data to the wrong animal.

Work through these in order.

## The file never appeared at all

Not on the animal page, and not on
[Unmatched Data Files](/help/unmatched-data) either. The parser refused the
name outright, so no record was ever created.

For a **physiology or behaviour run folder**:

- **Does the folder name end at the experiment type?** `... abr_io` is
  read; `... abr_io retest` is not. A trailing note is the single most
  common cause.
- **Is there a doubled space in the name?** The parser splits on single
  spaces and a double space shifts every field.
- **Is the experiment type one that is set up?** A type on disk that no
  data type uses is invisible; check *Not Set Up* in
  [Settings → Data Types](/help/settings-datatypes).
- **Is `_exclude` anywhere in the path?** Then it is being skipped on
  purpose.

For a **photo or dissection note**, the name must match its convention
exactly, including the spaced dashes — see
[Photos and dissection notes](/help/mmm-db-photos).

For a **cochleogram folder**, the name must start with the animal ID and
side, and the folder must directly contain a `*_frequency_map.pdf`.

## The file imported but matched nothing

It is on [Unmatched Data Files](/help/unmatched-data) with an
**Unresolved target** badge. The name parsed; what it named could not be
found. The *Unlinked objects* column says which:

| What you see | What to do |
|---|---|
| A plain light pill | that animal ID does not exist — check for a typo in the name, or add the animal |
| A split pill (animal + side) | the animal exists, the ear does not — create the ear from the animal page |
| No pills at all, physiology run | there is no event for that animal on that date — use *Auto-create events*, or add the event by hand |
| Nothing, confocal image | no image record at that frequency and image type — create it on the ear page |

After fixing the underlying record, **Re-run matching** on that data type
picks the file up; there is no need to re-sync from disk.

## The file was there and is now Missing

The record still exists, the file does not. Either it moved, or it was
deleted.

A **move** is normally handled for you: files are identified by content, so
a renamed or relocated dataset is recognised and its record follows it on
the next sync, keeping all its notes and links. A move that is not picked
up usually means the identity file changed too — for a psiexperiment run,
that is the `.zip`.

Genuinely deleted files can be cleared in bulk from the *Missing* filters
on the unmatched page.

## After renaming anything on disk

Renaming changes the path a record points at. Run a **sync** for that data
type afterwards and check the unmatched page for orphans — see
[Settings → Data Types](/help/settings-datatypes).
