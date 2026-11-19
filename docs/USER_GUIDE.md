# FlatScan — User Guide

This guide explains every screen and control in the application. It assumes the app is
already installed (see `README.md` if not) and that you are processing documents you are
authorised to handle.

---

## Contents

1. [Before you take the photo](#1-before-you-take-the-photo)
2. [Starting the application](#2-starting-the-application)
3. [Dashboard](#3-dashboard)
4. [Correction Studio](#4-correction-studio)
5. [Document Profiles](#5-document-profiles)
6. [Batch Processing](#6-batch-processing)
7. [Export Center](#7-export-center)
8. [Processing History](#8-processing-history)
9. [Settings](#9-settings)
10. [Keyboard shortcuts](#10-keyboard-shortcuts)
11. [Where your files live](#11-where-your-files-live)
12. [Frequently asked questions](#12-frequently-asked-questions)

---

## 1. Before you take the photo

Better input means a better result. You do not need special equipment, but:

- Place the document on a **plain, contrasting surface**. A dark desk under a light card
  is easier to detect than a white card on a white table.
- Keep the **whole document inside the frame**, with a small margin of background.
- Avoid direct flash and shiny reflections. Glare destroys printed information
  permanently.
- Hold the phone as parallel to the document as you can; a little perspective is fine
  and will be corrected.
- Use the highest resolution your camera offers. Very small images cannot produce sharp
  300 DPI output.
- Do not worry about taking the photo perfectly straight — corners can be adjusted.

The application will tell you when an image is blurry, dark, overexposed, too small or
contains glare. It will not pretend those problems can be undone.

---

## 2. Starting the application

From the project folder:

```bat
python main.py
```

A light-themed window opens with a navigation sidebar on the left:

- **Dashboard**
- **Correction Studio**
- **Batch Processing**
- **Document Profiles**
- **Processing History**
- **Export Center**
- **Settings**

The sidebar also shows a privacy badge: all processing is local. The status bar at the
bottom displays "Offline · local processing only" and the data folder in use.

On first launch the application creates its local database, copies the built-in document
profiles, and shows an empty dashboard.

---

## 3. Dashboard

The dashboard answers "what has been done so far?" and provides shortcuts.

**Statistics**

| Card | Meaning |
| --- | --- |
| Total images processed | All saved corrections plus all batch attempts |
| Successful corrections | Records with a successful result |
| Failed detections | Records or batch items that need attention |
| Batch jobs completed | Finished batch jobs |

**Quick actions**

- **New correction** — opens a file picker and starts the Correction Studio.
- **Batch processing** — switches to the batch queue.
- **Open project** — loads a saved `.json` project file.
- **Document profiles** — opens profile management.

**Recent projects** — a table of the latest corrections. Double-click a row to reopen it
in the Studio.

**Recent documents** — thumbnails of the latest successful corrections. Double-click a
thumbnail to reopen it.

**Empty state** — on a fresh installation, a guidance card appears with buttons to start
a correction, open batch processing, or review profiles.

---

## 4. Correction Studio
 
This is the main workspace. It has a header, an information strip, a tools panel on the
left, and **three tabs** in the centre: **Corner adjustment**, **Corrected result** and
**Metadata**.

### 4.1 Opening an image

Use any of these:

- **Open image** (top right) — choose a JPEG, PNG, BMP, TIFF or WebP file.
- **Drag and drop** a photo anywhere onto the window.
- **Paste** — copies the clipboard image, or a file copied in Explorer.
- **From PDF** — choose a PDF and import selected pages.
- **File → New correction** (`Ctrl+N`) or **File → Open project…** (`Ctrl+Shift+O`).

The header strip then shows:

- file name (and project name after saving),
- source pixel dimensions,
- orientation (Landscape / Portrait / Square),
- file size, whether EXIF rotation was applied, and the format.

The original file is opened read-only. Nothing in the Studio writes to it.

### 4.2 Importing PDF pages

1. Press **From PDF** (or drop a `.pdf` onto the window).
2. Pick the PDF. Password-protected files are rejected with a clear message.
3. Tick the pages you want, choose a render resolution (100–400 DPI), and preview a page.
4. Press **Import selected**.

The first page opens in the Studio. Any additional pages are rendered to temporary PNG
files and added to **Batch Processing**, with a notification telling you so.

### 4.3 Automatic detection
 
When an image loads, detection runs in the background.
 
- The **Detection** card shows the result and the confidence.
- **Confidence progress bar** — a colour-coded bar (green ≥70%, yellow 45-70%, red <45%) appears below the sensitivity slider after detection completes.
- **Sensitivity** (0–100%) controls how permissive detection is. Raise it for faint or
  low-contrast edges; lower it when background clutter is being mistaken for the card.
- **Detect document** re-runs detection with the current sensitivity. It is also
  available as `Ctrl+D` and as **Reset to detected corners** under the canvas.
 
If detection is uncertain, a warning appears. The corners are filled with the best
candidate anyway, so you can adjust them rather than starting from scratch.

### 4.4 Manual corner adjustment
 
Open the **Corner adjustment** tab.
 
- Four circular handles are labelled **TL** (top-left), **TR**, **BR**, **BL**.
- **Active handle highlight** — the currently selected corner (via keys 1–4 or mouse click) shows an amber ring.
- Dashed lines connect them and a light overlay shows the area that will be kept.
- Drag any handle. The outline refuses to become crossed, concave, or degenerate; the
  handle simply stops at the last valid position.
- **Arrow keys** nudge the selected corner by 1 px; **Shift+arrows** by 10 px.
- Click a handle (or press **1–4**) to select a corner for keyboard nudging.
- **Mouse wheel** zooms at the pointer. **Fit** fits the document; **100%** shows one
  screen pixel per image pixel.
- **Zoom to corner** — double-click a handle to centre the view and zoom to 200%.
- Drag an empty area, or drag with the middle mouse button, to pan.
- **Reset to detected corners** restores the last successful detection result instantly (does not re-run detection).
- **Reset to original image** discards *all* edits for this session (after confirmation)
  and reloads the source, or rebuilds from the in-memory image if it came from the
  clipboard.
 
Good practice: place each corner on the visible corner of the document, not on its
shadow. Zoom in for precision.

### 4.5 Orientation

The Document card provides:

- **Auto** — respects the profile's expected landscape/portrait orientation. If the card
  was photographed sideways, the sampling outline is aligned so the physical aspect
  ratio is preserved.
- **90° left** — rotates the corrected page 90° counter-clockwise.
- **90° right** — rotates the corrected page 90° clockwise.
- **180°** — turns it upside down.

Manual rotation clears "Auto" for that edit. The effective rotation and output size are
shown in the Result tab and the information strip. Rotating swaps the pixel width and
height, as expected for a turned page.

EXIF orientation is applied when loading, but orientation is never determined from EXIF
alone.

### 4.6 Dimensions and DPI

The Document card contains:

- **Document profile** — selecting one loads its measurements.
- **Width** and **Height** in millimetres (editable for this correction).
- **Output DPI** (72–1200; common values 150, 200, 300, 600).
- A live line such as `Output: 1011 × 638 px`. If the source is narrower than the
  requested output, the line says so; the image will be interpolated.

The calculation is always:

```
pixels = (millimetres / 25.4) × DPI
```

Editing these values only affects the current document. To change a profile
permanently, use **Document Profiles**.

### 4.7 Preview and before/after

Open the **Corrected result** tab.

- The straightened document is shown fitted to the panel.
- Tick **Before / after** to compare the perspective-corrected (unenhanced) image on the
  left with the enhanced result on the right. Drag the vertical divider to move the
  split. Labels mark BEFORE and AFTER.
- The label above the preview shows the output pixel size, rotation and DPI.
- Rendering happens in a background worker; the progress bar under the tabs shows when
  it is busy, and the interface stays usable.
 
### 4.8 Image Metadata
 
Open the **Metadata** tab.
 
- Displays all EXIF metadata extracted from the source image.
- Shows camera make/model, exposure settings (shutter speed, aperture, ISO), focal length,
  white balance, date/time, GPS data (if present), and software used.
- Useful for verifying image provenance or troubleshooting detection issues.
- If no EXIF data is found, a message is shown.
 
### 4.9 Enhancement

The **Enhancement** card applies adjustments to a copy of the corrected image. The
original perspective result remains available for comparison and re-export.

| Control | Range | Effect |
| --- | --- | --- |
| Brightness | −100…100 | Lightens or darkens the whole image |
| Contrast | −100…100 | Expands or compresses tonal range |
| Saturation | −100…100 | Colour intensity |
| Sharpness | 0…100 | Unsharp mask |
| Gamma | 0.30×…3.00× | Mid-tone correction without clipping highlights |
| Denoise | 0…100 | Non-local means colour denoising (slower on large images) |
| Colour boost | 0…100 | Additional gentle saturation |
| White balance | on/off | Gray-world colour cast removal |
| Grayscale | on/off | Produces a neutral grayscale image |

- **Auto enhance** estimates exposure, contrast, gamma, white balance, sharpening and
  denoise from the image histogram. It is a starting point, not a guarantee.
- **Reset** returns every enhancement control to neutral.
- Sliders update the preview as you drag. Each completed slider movement is a separate
  undo step.

### 4.9 Quality analysis

The **Image quality** card lists issues found in the corrected result:

- very blurred or slightly soft,
- underexposed or overexposed,
- strong shadow / uneven lighting,
- glare or clipped highlights,
- low source resolution or source below the target output size,
- uncertain card boundary (low detection confidence),
- or "No quality problems detected".

Warning text explains the real consequence — for example that clipping or blur cannot be
recovered. **Re-check quality** re-runs the analysis on the current result. The chip at
the bottom right summarises the worst severity.

### 4.10 Resampling

The **Document** card has a **Resampling** selector: Nearest, Linear, Cubic (default) or
Lanczos. It controls the interpolation used when the document is straightened.

- **Cubic** is the best general choice.
- **Lanczos** keeps the most fine detail on high-resolution scans, at a small speed cost.
- **Nearest** is the fastest but produces visibly blocky edges.
- **Linear** sits between Nearest and Cubic.

Changing it is an undoable edit, is stored with the project, and only affects the
current document — the global default lives in **Settings → Interpolation**.

### 4.11 Undo, redo and resetting

The bottom bar offers **Undo** and **Redo** (also `Ctrl+Z`, `Ctrl+Shift+Z`, `Ctrl+Y`).
Undo covers corner changes, rotation, dimension changes that re-render, brightness,
contrast, all enhancement sliders, white balance/grayscale, auto enhancement, reset, and
reset-to-original corner detection. Tooltips name the step that will be undone or
redone. The undo history is saved with the project and restored when you reopen it.

The original image itself is never changed by undo or reset.

### 4.11 Saving and exporting

- **Save project** (`Ctrl+S`) stores the processing record in SQLite, writes a portable
  `.json` project file in `storage/projects/`, and creates a thumbnail. Unsaved projects
  are also saved automatically when you export. The physical width, height and DPI you
  set in the Document card are saved with the project, so a document you calibrated by
  hand reopens at exactly that size.
- **Save project as…** (`Ctrl+Shift+S`) writes a copy of the project `.json` to any
  folder you choose. The history record stays where it is, so the studio keeps editing
  the same project.
- **Revert to saved** discards your edits and reloads the last saved version. It is only
  available when the document has unsaved changes.
- **Close project** (`Ctrl+W`) closes the document and returns the studio to its empty
  state. You are asked first if there are unsaved changes.
- **Export…** (`Ctrl+E`) opens the export dialog for the current corrected image.

If you close the main window while the studio holds unsaved work, FlatScan asks whether
to **Save**, **Discard** or **Cancel**. Choosing Save and having the save fail keeps the
application open so nothing is lost.

The export dialog provides format (PNG, JPEG, TIFF, PDF), DPI, JPEG quality, output
folder, filename template, conflict policy and PDF page size. **Preview PDF** renders
the page so you can confirm the physical layout before saving. Press **Export** to write
the file.

---

## 5. Document Profiles

Profiles define physical measurements and defaults. Open **Document Profiles** from the
sidebar.

**The table** lists every profile with its size, DPI, format and default marker.

**The editor** on the right contains:

- Name (must be unique),
- Description,
- Physical width and height in millimetres,
- Output DPI,
- Default format (PNG, JPEG, TIFF, PDF),
- Image quality (JPEG),
- Default orientation,
- Filename prefix,
- Active checkbox (inactive profiles disappear from pickers),
- A live pixel-size summary.

**Buttons**

| Button | Action |
| --- | --- |
| **New** | Creates a custom profile with generic measurements; edit and save it |
| **Duplicate** | Copies the selected profile, including its measurements |
| **Delete** | Deletes a custom profile (built-ins are protected) |
| **Set as default** | Makes this profile the default for new work |
| **Restore defaults** | Re-creates/refreshes the five built-in profiles, keeping custom ones |
| **Save profile** | Validates and persists the fields |

Validation rejects empty or duplicate names, non-positive sizes and DPI outside
72–1200. Built-in profiles can be deactivated instead of deleted, so a default always
exists. Existing projects keep their profile name even if a profile is later removed.

**Calibrating:** measure the document with a ruler, duplicate the closest profile, enter
the measured width and height, choose the DPI your workflow needs, save, and optionally
set it as default.

---

## 6. Batch Processing

Use batch mode for many files. The page has the queue and preview on the left, settings
and pairing on the right, and progress/actions at the bottom.

### 6.1 Building the queue

- **Add files** — multi-select images.
- **Add folder** — adds supported images directly inside that folder (not recursive).
- **Remove selected** / **Clear** — edit the queue. These are disabled while a batch is
  running.
- Duplicate absolute paths are ignored.
- Select a row to preview the original image underneath the queue.
- Double-click a row to open that file in the Correction Studio.

Each row shows the file, side, document ID, status (Pending, Processing, Completed,
Failed, Needs review), **duration** (ms/s/min) and details (output path or error). Hover
over a detailed error to read the full message.

- **Drag-to-reorder** — drag rows to change the processing order (disabled while running).

### 6.2 Settings

- **Document profile** — measurements and DPI default for the whole batch.
- **Sensitivity** — detection sensitivity (0–100%).
- **Detect document automatically** — when off, the full frame is used; useful for
  pre-cropped scans.
- **Auto enhance** — applies automatic enhancement per image.
- **Continue when a file fails** — keep going after an error (recommended; one bad file
  never stops the rest).
- **Format** — JPEG, PNG, TIFF or PDF per image.
- **DPI**, **Quality**, **Output folder**, **Filename** template.
- **If file exists** — rename, skip, or replace after confirmation. Replacing is
  confirmed once before the batch starts.

### 6.3 Front/back pairing

Pairing groups the two sides of one document while still exporting each side
individually.

- Select one or more rows and press **Mark front** or **Mark back**. Rows receive a
  document ID automatically.
- **Clear pairing** removes side/ID from selected rows (or all rows if none are selected).
- **Auto-pair by filename** recognises tokens such as `front`, `back`, `f`, `b`, `face`,
  `rear`, `amam`, `khalf`, `1`, `2`, separated by `_`, `-`, `.` or spaces. For example
  `iqama_front.jpg` and `iqama_back.jpg` pair under the ID `iqama`.
- **Export paired PDFs** processes each complete pair and writes one PDF per document
  into the output folder. Incomplete groups are skipped; assign both sides first.

### 6.4 Running a batch

1. Configure the settings and output folder.
2. Press **Start batch**.
3. Watch the counters: Total, Pending, Completed, Failed, Needs review, plus the current
   file name and a progress bar.
4. **Pause** stops after the current file; the button becomes **Resume**.
5. **Cancel batch** stops after the current file and keeps results already written.
6. When finished, a summary reports successes and failures.

Every processed file is recorded in the batch job tables. Dashboard totals include batch
attempts.

### 6.5 Handling failures

- **Failed** — the file could not be decoded, written, or corrected. The reason is in the
  Details column.
- **Needs review** — automatic detection was not confident enough. No output is written
  for that file. Select it and press **Open selected in Studio** to set the corners
  manually.

After fixing causes, press **Retry failed** to run only the failed and needs-review
files again.

---

## 7. Export Center

The Export Center converts corrected images and PDFs with explicit control over naming,
size and conflicts.
 
### 7.1 Queue
 
- **Add files** — any supported image, typically a corrected export or scan.
- **Add from history** — pick saved projects; the corrected output is used when it still
  exists, otherwise the source image.
- **Remove selected**, **Clear list**.
- Selecting an entry shows a preview.
 
### 7.2 Settings
 
- **Preset profiles** — a dropdown at the top provides 6 one-click presets:
  - **ID Card / Passport** (JPEG, 300 DPI)
  - **High-Quality Archive** (PNG, 600 DPI)
  - **Web Optimized** (JPEG, 150 DPI, 85%)
  - **Print Ready** (TIFF, 300 DPI)
  - **PDF Document (A4, 300 DPI)**
  - **PDF Document (Physical Size, 300 DPI)**
  Selecting a preset fills in the format, DPI, quality and PDF page mode; you can then tweak
  individual settings if needed.
 
| Setting | Purpose |
| --- | --- |
| Format | PNG, JPEG, TIFF or PDF |
| DPI | 150/200/300/600 or any 72–1200 |
| JPEG quality | 50–100 |
| Output folder | Destination; created if needed |
| Filename | Template with the tokens listed in `README.md` |
| If file exists | Rename automatically, skip, or replace after confirmation |
| PDF page size | Fit to image, A4, A5, US Letter, or the document's physical size |
| PDF margin | Optional white border in millimetres |
| Add document type to filename | Appends the profile name when the template does not include it |
| Add front/back designation | Appends `front`/`back` when assigned |
| Combine all entries into one PDF | One multi-page PDF instead of one file per entry |

**Preview PDF** builds a temporary PDF with the current page size and margin and shows
its pages, with Previous/Next navigation, before anything is saved.

**Export** runs in a background worker. Existing-file replacement is confirmed once
before starting. The result line lists the saved path(s) or the first errors.

Notes:

- Raster entries are re-encoded once into the chosen format with DPI metadata.
- Combining into a PDF always produces a PDF, even if the format selector is set to an
  image format.
- Images are inserted with their aspect ratio preserved and centred on the page.

---

## 8. Processing History

Every saved project and export is listed here.
 
**Table columns:** Date, Name, Document profile, Status, Source, Output.
 
- A red "missing" marker means the original file has moved or been deleted.
- Use the **search** field to filter by project name, profile or path. Type `status:success` or `status:failed` to filter by status.
- **Refresh** reloads the list.
 
**Details panel** shows full source and output paths, rotation, DPI, whether corners were
saved, the last update and any recorded error. Paths are selectable.
 
**Actions**
 
| Button | Action |
| --- | --- |
| **Open in Studio** | Reloads the project with its corners, rotation and enhancement for further editing. If the source is missing, you are offered a relink. |
| **Export again** | Rebuilds the correction from the source and saved settings, then opens the export dialog. |
| **Relink source** | Points the record at the moved image file. |
| **Open source folder** | Opens the containing folder in Explorer. |
| **Copy source path** | Copies the source image file path to clipboard. |
| **Copy output path** | Copies the exported file path to clipboard. |
| **Purge old records** | Deletes records older than the retention period set in Settings. |
| **Delete record** | Removes the history entry and its project file. Exported files and original images are not deleted. |

The database stores paths and processing metadata only — never image binaries. If an
image is moved, relink it; if it is gone, the record remains for reference but cannot be
reopened.

---

## 9. Settings

Settings are saved to `storage/settings.json` when you press **Save settings** and are
restored on the next start.

**Appearance**
 
- Theme: Light (default) or Dark. Applied immediately after saving.
- **Preview** — opens a live dialog showing the selected theme with sample controls.
 
**Processing defaults**

- Default document profile (or the database default).
- Default DPI, format, JPEG quality.
- Detection sensitivity for new images.
- Interpolation for warping: Nearest, Linear, Cubic, Lanczos.
- Automatic enhancement for newly opened images.
- Filename template and overwrite policy.

**Directories**

- Project files, exported documents, temporary files, thumbnails. Each has a browse
  button. Folders are created and validated on save.

**History and storage**

- History retention in days (0 = keep forever) and **Purge old history**.
- **Clear all history** removes records only; images and exports remain.
- **Clean temporary files** empties the temp folder.
- Clean temporary files automatically on exit.

**Behaviour and confirmations**

- Automatic detection in batch processing.
- Continue a batch when one file fails.
- Confirm before replacing an existing output file.
- Confirm before deleting history records or profiles.
- Show image quality warnings.
 
**All form fields have tooltips** — hover any control for an instant explanation of its
purpose and valid values.
 
**Restore defaults** resets all settings to factory values while keeping profiles and
history.

Temporary PDF renders and scratch files can be removed at any time; the original images
live wherever you keep them.

---

## 10. Keyboard shortcuts
 
| Shortcut | Action |
| --- | --- |
| `Ctrl+N` | New correction |
| `Ctrl+O` | Open image |
| `Ctrl+Shift+O` | Open project file |
| `Ctrl+V` | Paste image from clipboard |
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z`, `Ctrl+Y` | Redo |
| `Ctrl+S` | Save project |
| `Ctrl+Shift+S` | Save project as… |
| `Ctrl+W` | Close project |
| `Ctrl+E` | Export |
| `Ctrl+D` | Detect document |
| `F5` | Refresh the current page |
| `Ctrl+Q` | Exit |
| `F1` | Keyboard shortcuts help dialog |
| Wheel | Zoom at the pointer |
| Arrows | Nudge selected corner 1 px |
| `Shift`+arrows | Nudge selected corner 10 px |
| `1`–`4` | Select TL / TR / BR / BL corner |
| Drag empty area, middle drag | Pan the image |
| Double-click corner handle | Zoom to corner (200%) |

---

## 11. Where your files live

```
storage/
    app.db              profiles, projects, batch history (no images)
    settings.json       your preferences
    projects/*.json     portable project files
    exports/            default export folder
    thumbnails/         dashboard and history previews
    temp/               PDF page renders and scratch files
    logs/app.log        technical log (rotating)
```

- Nothing is written into your photo folders unless you choose them as the export
  destination.
- The application never overwrites a source image.
- To start completely fresh, close the app and delete `storage/`. Your images and
  previously exported files stay where they are.
- When packaged as an executable in a non-writable folder, the same structure is created
  under `%LOCALAPPDATA%\FlatScan`.

---

## 12. Frequently asked questions

**Detection keeps choosing the table edge instead of the card.**
Lower the sensitivity, ensure some contrasting background surrounds the card, or place
the corners manually. Once adjusted, save the project — the corners are stored.

**The card is found but a corner is slightly off.**
Zoom in (wheel), drag the handle, then fine-tune with the arrow keys. Shift+arrows move
faster.

**The output is stretched.**
Check that the profile's width and height match the document's real orientation (landscape
= width is the longer side). If you photographed it sideways, press **Auto** under the
Document card, or use the rotation buttons.

**The result is 1011 × 638 px, but I need 300 DPI A4.**
Select or create a profile with A4 measurements (210 × 297 mm) and the required DPI, or
type the values directly in the Document card.

**The photo is blurry. Can it be fixed?**
Enhancement can improve readability slightly, but detail that was not captured cannot be
recreated. The quality analysis warns about this. Retake the photo when accuracy matters.

**What does "Needs review" mean in a batch?**
Automatic detection confidence was below the usable threshold, so the file was not
exported. Open it in the Studio, set the corners, and process it there, or retry after
raising the batch sensitivity.

**Where are my original images?**
Exactly where they were. The application only reads them.

**Can I use this offline?**
Yes, entirely. It makes no network requests.

**Does it read the ID number or personal data?**
No. There is no OCR, and no text extraction or storage. Only file paths and processing
settings are recorded locally.

**Why can't I delete a built-in profile?**
So that a working default always exists. Deactivate it instead, or change its
measurements, or press **Duplicate** to make an editable copy.

**A PDF I imported has low resolution.**
PDF pages are rasterised; choose a higher render resolution (up to 400 DPI) in the import
dialog. The vector content of the PDF is not preserved.

**The export says the file exists.**
Choose a different conflict policy: **Rename automatically** keeps both files,
**Skip** leaves the old file, **Replace after confirmation** overwrites it.
