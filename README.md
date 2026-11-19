# FlatScan — Perspective Correction for ID Cards and Documents

A complete, offline Windows desktop application for turning phone photographs of
documents into clean, correctly proportioned digital copies.

Photograph an Iqama, driving licence, Istimara, passport or any other card, and the
application detects its outline, corrects perspective distortion, straightens the
document, resizes it to its real physical measurements at a chosen DPI, enhances the
image, and exports PNG, JPEG, TIFF or PDF. Batch processing, front/back pairing,
projects, processing history and undo/redo are included.

> Built with Python 3.14, PySide6 and OpenCV. No internet connection is used, and no
> document image ever leaves the computer.

---

## Contents

- [Status](#status)
- [Features](#features)
- [Supported documents](#supported-documents)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [How the correction works](#how-the-correction-works)
- [Document profiles and calibration](#document-profiles-and-calibration)
- [Supported formats](#supported-formats)
- [Export naming and conflicts](#export-naming-and-conflicts)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Data and storage layout](#data-and-storage-layout)
- [Testing](#testing)
- [Packaging a Windows executable](#packaging-a-windows-executable)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)
- [Known limitations](#known-limitations)
- [Documentation](#documentation)

---

## Status

| Item | Value |
| --- | --- |
| Application version | 1.0.0 |
| Verified Python | 3.14.7 (64-bit, Windows 11) |
| Interface | PySide6 6.12, light theme by default |
| Image engine | OpenCV 5.0, NumPy 2.5 |
| PDF engine | PyMuPDF 2.0 (import and export) |
| Database | SQLite (bundled with Python) |
| Automated tests | 115 passing (`python -m pytest tests -q`) |

The application is a working desktop program, not a mock-up. Every visible control is
wired to real functionality.

---

## Features
 
 ### Correction Studio
 - Open JPEG, PNG, BMP, TIFF and WebP photos; drag and drop; paste from the clipboard;
   import pages from PDF files.
 - Automatic card detection using several independent strategies, with a sensitivity
   control and candidate scoring instead of "largest rectangle wins".
 - **Confidence progress bar** — colour-coded detection confidence (green ≥70%, yellow 45-70%, red <45%).
 - Manual four-corner editor with zoom, pan, fit-to-screen, corner labels, keyboard
   nudging and rejection of crossed or concave outlines.
 - **Active corner highlight** — amber ring on the keyboard-selected handle (keys 1–4 or click).
 - **Zoom to corner** — double-click a handle to centre and zoom to 200%.
 - Perspective correction with `cv2.getPerspectiveTransform` / `cv2.warpPerspective`,
   selectable interpolation, preview before committing.
 - Automatic orientation plus manual 90° left, 90° right and 180° rotation.
 - Physical output size in millimetres and DPI, with the pixel size shown before
   rendering. The original photo is never modified.
 - Enhancement: brightness, contrast, saturation, sharpness, gamma, denoise, colour
   boost, white balance, grayscale and automatic enhancement.
 - Quality analysis: blur, under/overexposure, shadows, glare, low resolution and
   uncertain boundaries, reported as plain-language warnings.
 - Undo/redo for corners, rotation, dimensions and enhancement.
 - **Auto-save draft** — 30 s interval; crash recovery prompt on next launch.
 - **Image Metadata tab** — EXIF data viewer (camera, exposure, GPS, etc.).
 
 ### Batch Processing
 - Add multiple files or a whole folder, preview each one, remove and clear entries.
 - Automatic detection, profile selection, output format/DPI/quality, filename
   template and conflict policy.
 - Background worker with start, pause, resume, cancel, progress, per-file status and a
   detailed error per failed file. One failure never stops the batch.
 - **Duration column** — per-file processing time (ms/s/min).
 - **Drag-to-reorder queue** — drag rows to change processing order.
 - Retry failed files, or send a failed file to the Correction Studio for manual corners.
 - Front/back pairing by explicit assignment or filename, with combined PDF export.
 
 ### Profiles, history and export
 - Five editable built-in profiles plus unlimited custom profiles: physical size,
   default DPI, format, quality, orientation, filename prefix, active state.
 - **Aspect ratio preview** — visual rectangle showing landscape/portrait/square.
 - SQLite processing history with saved corners, settings, status and error details;
   reopen, re-export, relink a moved source, delete records, purge by age.
 - **Clickable dashboard stats** — click Total/Success/Failed to filter history.
 - **Copy path buttons** — copy source/output paths to clipboard from history.
 - Export Center for PNG, JPEG, TIFF and PDF, DPI metadata, filename templates,
   overwrite protection, PDF page-size control, PDF preview and queue export.
 - **Export presets** — 6 one-click profiles (ID Card, Archive, Web, Print, PDF A4, PDF Physical).
 - Settings for theme, defaults, directories, retention, batch behaviour and dialogs.
 - **Theme preview dialog** — live preview of Light/Dark themes with sample controls.
 - **Tooltips on all form fields** — hover any control for instant explanation.

### Safety and privacy
- 100% local processing; no network calls, no uploads, no telemetry.
- Original images are opened read-only and never overwritten.
- Exported files never silently replace existing files unless the user explicitly
  chooses "Replace after confirmation".
- No identification numbers are extracted or stored. Images are not stored in the
  database — only file paths and processing metadata.

---

## Supported documents

Any rectangular document can be corrected. Profiles ship for:

| Profile | Default measurements | Default output |
| --- | --- | --- |
| Saudi Iqama | 85.6 × 53.98 mm (ID-1) | JPEG, 300 DPI |
| Saudi Driving License | 85.6 × 53.98 mm (ID-1) | JPEG, 300 DPI |
| Saudi Istimara | 210 × 297 mm (A4 paper) | PDF, 300 DPI |
| Passport | 125 × 88 mm (TD3 data page) | JPEG, 300 DPI |
| Custom Card | 85.6 × 53.98 mm | PNG, 300 DPI |

These are starting points, not claims about every issue of every document. Physical
dimensions are user-editable and should be calibrated with a ruler when exact output
size matters.

---

## Requirements

- Windows 10 or Windows 11 (64-bit).
- Python 3.14 installed and available as `python`.
- Approximately 300 MB of free disk space for dependencies.
- No internet connection at run time.

The following versions were verified together:

```
Python 3.14.7
PySide6 6.12.0
opencv-python-headless 5.0.0
numpy 2.5.3
Pillow 12.3.0
PyMuPDF 2.0
pytest 9.1.1
```

---

## Installation

A virtual environment is not required; install into the Python 3.14 interpreter that
will run the application.

```bat
cd FlatScan
python -m pip install -r requirements.txt
```

If the packages are already installed, `pip` will simply confirm them. Do not install
both `opencv-python` and `opencv-python-headless` in the same interpreter — they share
the `cv2` module and conflict. The application only needs the headless build because
all windows are drawn with Qt.

Verify the installation:

```bat
python -c "import PySide6, cv2, numpy, PIL, pymupdf; print('dependencies OK')"
```

---

## Quick start

```bat
python main.py
```

1. **Dashboard** → *New correction*.
2. Choose a photo (or drag it onto the window).
3. The document is detected automatically. If the outline is wrong, switch to
   **Corner adjustment** and drag the four handles, or use the arrow keys.
4. Check the **Corrected result** tab and enable **Before / after** to compare.
5. Choose a document profile, or type measured width/height and DPI.
6. Adjust enhancement if needed and review the quality warnings.
7. Press **Save project** to keep it in history, then **Export…** to write a file.

For many photos, use **Batch Processing**. For re-exporting earlier work, use
**Processing History** or the **Export Center**.

---

## How the correction works

1. The photo is loaded with Pillow (EXIF rotation applied) and converted to an OpenCV
   BGR array. The file on disk is never modified.
2. Detection runs on a resized copy (longest side 1280 px) to stay fast:
   - CLAHE contrast equalisation, bilateral filtering and automatic Canny edges;
   - contours → several polygon approximations → convex quadrilaterals;
   - adaptive thresholding (normal and inverted) for low-contrast boundaries;
   - probabilistic Hough lines grouped into top/bottom/left/right edges and intersected;
   - a whole-frame fallback candidate for cards that fill the photo.
3. Every candidate is scored by area ratio, rectangularity (corner angles), edge
   strength, inside/outside background contrast, plausible document aspect ratio and
   convexity. The best score wins; the largest rectangle is not assumed to be the card.
4. The four corners are ordered top-left, top-right, bottom-right, bottom-left and
   validated. If the photo is sideways, the sampling outline is rotated so the profile's
   expected orientation is respected.
5. `cv2.getPerspectiveTransform` maps the quadrilateral to a rectangle whose pixel size
   is `(millimetres / 25.4) * DPI`, rounded, and `cv2.warpPerspective` renders it with
   the selected interpolation. Output is a rectangle by construction and never clipped.
6. Rotation and enhancement are applied to a copy. The unenhanced corrected image stays
   available, which is what the Before / After view compares.
7. Quality checks report measurable facts. A blurred photo is described as blurred;
   the application never claims that lost detail can be restored.

---

## Document profiles and calibration

Open **Document Profiles** to edit physical sizes.

**To calibrate a card:**

1. Measure the card with a ruler in millimetres (width along the long side).
2. Select the closest profile, or press **Duplicate** to keep the original intact.
3. Enter width and height, choose DPI and a default format, then **Save profile**.
4. Press **Set as default** if new corrections should use it automatically.

Pixel dimensions are calculated, not guessed:

```
pixels = (millimetres / 25.4) * DPI
```

Example: 85.6 mm at 300 DPI = 1011 px; 53.98 mm at 300 DPI = 638 px.

Changing the profile in the Correction Studio does not modify the profile itself; use
the profile manager for permanent changes. Built-in profiles cannot be deleted, only
deactivated, so a default set always remains available. **Restore defaults** re-creates
the shipped measurements while keeping custom profiles.

---

## Supported formats

| Direction | Formats |
| --- | --- |
| Import | JPEG, PNG, BMP, TIFF, WebP, PDF pages |
| Export | PNG, JPEG, TIFF, PDF |

DPI metadata is embedded in PNG, JPEG and TIFF exports. PDF pages carry a physical page
size in millimetres when the "Document physical size" page mode is selected.

JPEG quality is configurable from 50 to 100. TIFF uses LZW compression. PNG uses
lossless compression. Images are not recompressed more than necessary: the corrected
pixels are encoded once for the chosen format.

---

## Export naming and conflicts

Filename templates support these tokens:

| Token | Meaning |
| --- | --- |
| `{name}` | Original file name without extension |
| `{profile}` | Document profile name |
| `{side}` | `front` or `back` when assigned |
| `{date}` | `YYYY-MM-DD` |
| `{time}` | `HHMMSS` |
| `{dpi}` | Output DPI |
| `{index}` | Zero-padded queue index (`000`, `001`, …) |

Default template: `{name}_{profile}`.

Conflict policies:

- **Rename automatically** — writes `name_1`, `name_2`, … (default, safest).
- **Skip existing files** — leaves the existing file untouched.
- **Replace after confirmation** — asks once before replacing.

Invalid path characters are replaced with underscores, and the correct extension is
always appended.

---

## Keyboard shortcuts
 
 | Shortcut | Action |
 | --- | --- |
 | `Ctrl+N` | New correction (main window) |
 | `Ctrl+O` | Open image (studio) |
 | `Ctrl+Shift+O` | Open project |
 | `Ctrl+V` | Paste image from clipboard |
 | `Ctrl+Z` | Undo |
 | `Ctrl+Shift+Z` / `Ctrl+Y` | Redo |
 | `Ctrl+S` | Save project |
 | `Ctrl+Shift+S` | Save project as… |
 | `Ctrl+W` | Close project |
 | `Ctrl+E` | Export |
 | `Ctrl+D` | Detect document |
 | `F5` | Refresh the current page |
 | `Ctrl+Q` | Exit |
 | `F1` | Keyboard shortcuts help dialog |
 | Mouse wheel | Zoom at pointer |
 | Arrow keys | Nudge selected corner 1 px |
 | `Shift`+Arrow keys | Nudge selected corner 10 px |
 | `1`–`4` | Select corner TL / TR / BR / BL |
 | Drag empty area / Middle mouse | Pan |
 | Double-click corner handle | Zoom to corner (200%) |

---

## Menu bar

The menu bar follows the standard desktop layout, and every entry is enabled only
when it applies to the page you are looking at.

| Menu | Entries |
| --- | --- |
| **File** | New correction, Open image, Open project, Recent files, Save project, Save project as…, Revert to saved, Close project, Export…, Export Center, Batch processing, Exit |
| **Edit** | Undo, Redo, Paste image, Detect document, Reset to detected corners, Reset to original image, Rotate 90° left / 90° right / 180° |
| **View** | Dashboard, Correction Studio, Batch Processing, Document Profiles, Processing History, Export Center, Settings, Refresh |
| **Tools** | Document profiles, Processing history, Settings…, Open data folder |
| **Help** | Keyboard shortcuts, About FlatScan |

Enablement rules:

- **Save / Save as / Close / Export / Detect / Reset / Rotate** require an open
  document in the Correction Studio.
- **Save** is enabled only while there are unsaved changes.
- **Revert to saved** is enabled only when the document has been saved *and* has
  diverged from that saved version.
- **Undo / Redo** mirror the undo stack.
- **Refresh** is enabled on the Dashboard, Processing History and Document Profiles
  pages, which load their data from the database.
- **View** greys out the page you are already on.

---

## Data and storage layout


Everything lives under `storage/` next to `main.py` (or next to the executable when
packaged; a per-user folder is used if the install directory is read-only).

```
storage/
    app.db              SQLite: profiles, projects, batch jobs and items
    settings.json       persistent application settings
    projects/           portable project files (<id>.json)
    exports/            default export destination
    thumbnails/         small previews for dashboard and history
    temp/               PDF page renders and scratch files
    logs/app.log        rotating technical log
```

Deleting `storage/` resets the application to a fresh installation, including the
database and profiles. Exported files are stored wherever you choose and are not
deleted by the application.

---

## Testing

The automated suite generates synthetic card photographs, so it contains no personal
data and needs no sample files.

```bat
python -m pytest tests -q
```

Current result: **124 passed**.

The GUI tests create Qt worker threads that outlive the interpreter on Windows, so a
plain `pytest` run can print its summary and then appear to hang. Use the bundled
runner when you need a guaranteed exit code (it runs one file per process with a
timeout):

```bat
python tools/run_tests.py
```

Coverage:

| File | Focus |
| --- | --- |
| `tests/test_detection.py` | detection accuracy against ground-truth corners, rotated photos, blank images, candidate scoring |
| `tests/test_perspective.py` | corner ordering, invalid quadrilaterals, warp fidelity, output size |
| `tests/test_dimensions.py` | mm/pixel/DPI formulas, rotation, profile sizes, auto orientation, enhancement |
| `tests/test_export.py` | DPI metadata, conflict policies, original-file preservation, templates, PDF page sizes and page counts |
| `tests/test_profiles.py` | seeding, defaults, duplication, validation, built-in protection, restore |
| `tests/test_database.py` | schema, project lifecycle, dashboard stats, purge, batch rows, settings persistence, project files, relinking, undo/redo |
| `tests/test_menu_flow.py` | menu structure and order, page-aware action enablement, recent files at startup, save-as/close/revert, saved-measurement round trip, malformed project files |
| `tests/test_save_flow.py` | save toast, dirty tracking, save-state chip, failed sidecar writes |
| `tests/test_settings.py` | settings whitelist audit, export/save preference persistence, recent-profile startup |
| `tests/test_regressions.py` | previously reported defects kept fixed |

A headless UI smoke test was also run during development: the main window and all seven
pages instantiate, an image loads through detection and warping, rotation/undo work, and
a project saves to SQLite and JSON. Interactive clicking and visual layout on a physical
display were not part of that check.

---

## Packaging a Windows executable

PyInstaller is supported but optional. Install it first:

```bat
python -m pip install pyinstaller
```

Build from the project root (Windows uses `;` as the `--add-data` separator):

```bat
python -m PyInstaller --noconfirm --windowed --name FlatScan ^
  --add-data "profiles;profiles" --add-data "ui\styles;ui\styles" main.py
```

PowerShell uses a backtick for line continuation, or simply put everything on one line.
The result is `dist\FlatScan\FlatScan.exe` (or a single file if you add
`--onefile`). The executable creates its `storage/` folder beside itself when that
folder is writable, otherwise under `%LOCALAPPDATA%\FlatScan`. Bundled,
read-only assets (profiles and the stylesheet) are resolved from the PyInstaller bundle.

No installer is generated by this project. The executable can be zipped and run
portably, or wrapped with your preferred installer tool.

---

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| "No document outline was detected" | Raise detection sensitivity, ensure the whole card is visible with some background around it, or drag the corners manually. |
| Corners snap back while dragging | The outline would become crossed or concave; move another corner first, or place corners in a clockwise order. |
| Output looks stretched | The profile's width/height may be reversed, or the corners do not follow the card's real edges. Check `Auto` orientation and the profile measurements. |
| Output is smaller than expected | The selected DPI or profile is different from what you assumed. The pixel dimensions are shown under the size fields before export. |
| "The image could not be decoded" | The file is corrupted or is not a real image despite its extension. Re-export it from the camera roll and retry. |
| A PDF cannot be opened | Password-protected PDFs are intentionally not supported. |
| Export fails with a permission error | Choose a folder you can write to (for example `Documents`), not a protected system folder. |
| "Original image missing" in history | The photo was moved or renamed. Use **Relink source** in Processing History. |
| Interface shows an unexpected error message | The application catches errors and writes the traceback to `storage/logs/app.log`; nothing is shown as a raw console traceback. |
| Batch stops unexpectedly | It should not: each file is isolated. If it does, check the per-file error column and the log. Retry failed files after correcting the cause. |

---

## Project structure

```
FlatScan/
    main.py                     entry point
    requirements.txt
    README.md
    LICENSE

    docs/                       long-form documentation
        USER_GUIDE.md           task-by-task instructions for every screen
        ARCHITECTURE.md         modules, algorithms, threading, schema

    app/                        application plumbing
        application.py          bootstrap, logging, exception hook
        constants.py            paths, formats, status constants
        config.py               JSON settings store
        context.py              shared services and cross-page signals

    ui/                         PySide6 interface
        main_window.py          sidebar navigation and page wiring
        dashboard.py            statistics and quick actions
        correction_studio.py    detection, corners, enhancement, preview
        batch_window.py         queue, pairing and progress
        profile_manager.py      document profile CRUD
        history_window.py       projects and relinking
        export_window.py        Export Center and quick export dialogs
        settings_window.py      persistent settings
        pdf_dialog.py           PDF page import
        icons.py                QPainter-drawn icons
        image_utils.py          NumPy ↔ Qt image conversion
        widgets/                canvas, handles, previews, progress, toasts
        styles/                 theme tokens and stylesheet

    core/                       GUI-independent image processing
        image_loader.py         decoding, clipboard, thumbnails
        corner_detection.py     candidate generation and scoring
        image_detector.py       detection API and confidence
        perspective.py          ordering, validation, warping
        pipeline.py             shared correction pipeline
        orientation.py          rotations
        enhancement.py          non-destructive adjustments
        quality_analyzer.py     measurable quality checks
        dimension_calculator.py mm ↔ pixels ↔ DPI
        image_exporter.py       raster writing and DPI metadata
        pdf_handler.py          PDF rendering and export
        edit_history.py         edit state and undo stack

    services/                   orchestration
        project_service.py      SQLite + project JSON + thumbnails
        export_service.py       naming, conflicts, export queue
        batch_service.py        batch processing and pairing

    workers/                    Qt threads
        image_worker.py         latest-request detection/render worker
        batch_worker.py         pause/resume/cancel batch worker
        export_worker.py        background export queue
        pdf_worker.py           PDF tasks

    database/                   SQLite
        connection.py           migrations
        models.py               data classes
        repository.py           CRUD and statistics
        migrations/001_initial.sql

    profiles/default_profiles.json
    storage/                    runtime data (created on first run)
    tests/                      pytest suite
```

---

## Known limitations

- **No OCR.** Text is not recognised, and no personal identifiers are extracted or
  stored. If OCR is added later it must be optional and fully local.
- **Automatic detection is heuristic.** Uniform backgrounds, extreme glare, or a card
  cut off by the frame can defeat it; manual corners are always available.
- **Auto orientation is best-effort.** It guarantees the profile's landscape/portrait
  orientation, not which way is up. Use the 90°/180° buttons if a document is upside
  down.
- **Physical sizes require calibration.** Shipped millimetre values are standard
  starting points; exact reproductions need measured dimensions.
- **No detail recovery.** Sharpening and denoising cannot restore information lost to
  blur, clipping, glare or low resolution. Warnings say so explicitly.
- **PDF import is raster.** Pages are rendered to images at the chosen DPI; embedded
  text and vector content are not preserved.
- **Single-user desktop database.** SQLite is local, not a multi-user server store.
- **Interface language is English only.**
- **Packaging was documented but not executed in this environment**; the PyInstaller
  command above is the supported route.
- **Visual review was structural.** The UI was instantiated and exercised offscreen;
  pixel-level layout on a physical display was not inspected.

---

## Documentation

- [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) — task-by-task instructions for every screen.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — modules, data flow, algorithms, threading,
  database schema and design decisions.


---

## License and intended use

This is a local utility for digitising your own documents. Only process documents you
are authorised to handle. The application does not transmit, upload or analyse document
contents; retention and deletion of images and projects remain under your control.
