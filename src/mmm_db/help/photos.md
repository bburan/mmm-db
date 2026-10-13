# Photos and dissection notes

Simple file types, and the only ones in this deployment that can be
**uploaded** through the interface rather than only discovered by sync.

## Animal photos

Attached to an **animal**. Filename convention:

```
<animal id> - <YYYYMMDD> - <note>.jpg
```

for example `A001 - 20260415 - cage change.jpg`. A photo covering several
animals — a litter portrait, say — lists them separated by `,`, `+`, `&`
or `|`, and the photo is linked to each. JPEG and PDF are accepted.

## Animal text notes

Attached to an **animal**, and written in the app rather than uploaded:
**New Text Note** on the animal's Files list opens an editor. Notes are
Markdown — `# Heading`, `**bold**`, `- list item` — and text pasted from
Word or Outlook keeps its headings, lists, tables, bold and links,
converted to Markdown as it is pasted. Images and colours are dropped.

The file is saved as `<animal id> - <YYYYMMDD> - <name>.md` (a blank name
becomes *note 1*, *note 2*, …), in the same per-animal folder layout as
photos. The read button on its row shows it formatted, with an **Edit**
button to change the text later. A `.txt` file dropped into the location
by hand is picked up too, and can be read but not edited.

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
page. You choose the targets, a date, and for each file a **name** and a
**note**. The name becomes the `<note>` segment of the filename above; the
note is stored with the file and never appears in its name. Leave the name
blank and the file is numbered for you — *image 1*, *image 2*, … — picking
up past anything already in that folder, so an upload never replaces an
existing photo.

The rest of the name is generated from the targets and the date and written
into the configured location. An uploaded photo is indistinguishable from
one the sync found, so it gets the same thumbnail, status and notes
handling afterwards — and uploading is the reliable way to add one, since
it cannot produce a name the parser later fails to read.
