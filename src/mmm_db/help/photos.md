# Photos and dissection notes

Two simple file types, and the only ones in this deployment that can be
**uploaded** through the interface rather than only discovered by sync.

## Animal photos

Attached to an **animal**. Filename convention:

```
<animal id> - <YYYYMMDD> - <note>.jpg
```

for example `A001 - 20260415 - cage change.jpg`. A photo covering several
animals — a litter portrait, say — lists them separated by `,`, `+`, `&`
or `|`, and the photo is linked to each. JPEG and PDF are accepted.

## Ear dissection notes

Attached to an **ear**. Filename convention:

```
<id1><L|R> <id2><L|R> ... - <note>.jpg
```

for example `G014-4L G018-3R - dissection notes.jpg`. Each ID before the
dash may carry an `L` or `R` suffix naming the side; an ID without one is
still recorded as a candidate animal but will not match a specific ear,
which is why such a file often shows up on
[Unmatched Data Files](/help/unmatched-data) with a split pill.

## Uploading

Both types accept uploads from the **Upload** button on an animal or ear
page. You choose the targets, a date and per-file notes; the file is
renamed to the convention above and written into the configured location.
An uploaded photo is indistinguishable from one the sync found, so it gets
the same thumbnail, status and notes handling afterwards.

Because the name is generated from the targets and the date, uploading is
the reliable way to add a photo — it cannot produce a name the parser
later fails to read.
