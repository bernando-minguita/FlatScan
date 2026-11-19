# Architecture

Technical reference for FlatScan. It describes how
the modules fit together, how the correction pipeline works, how threading and
persistence are handled, and which trade-offs were made.

---

## Contents

1. [Goals and constraints](#1-goals-and-constraints)
2. [Layers](#2-layers)
3. [Startup sequence](#3-startup-sequence)
4. [Module reference](#4-module-reference)
5. [Correction pipeline](#5-correction-pipeline)
6. [Detection engine](#6-detection-engine)
7. [Geometry, dimensions and orientation](#7-geometry-dimensions-and-orientation)
8. [Enhancement and quality analysis](#8-enhancement-and-quality-analysis)
9. [Edit state and undo/redo](#9-edit-state-and-undoredo)
10. [Threading model](#10-threading-model)
11. [Persistence](#11-persistence)
12. [Interface architecture](#12-interface-architecture)
13. [Export naming and conflicts](#13-export-naming-and-conflicts)
14. [Error handling and logging](#14-error-handling-and-logging)
15. [Performance considerations](#15-performance-considerations)
16. [Testing](#16-testing)
17. [Extension points](#17-extension-points)
18. [Trade-offs and known limitations](#18-trade-offs-and-known-limitations)

---

## 1. Goals and constraints

- Windows 10/11 desktop application, Python 3.14, run from source with `python main.py`.
- Fully offline: no network calls anywhere in the codebase.
- Non-destructive: the source image is read once and never written to.
- Responsive: all heavy work happens on Qt worker threads; the UI thread only builds
  results.
- Modular: no single-file application, no GUI code inside image-processing modules.
- Exact physical output: millimetres and DPI determine pixel dimensions.
- No fabricated functionality: every shipped control is connected to working code.

Dependencies were checked against the installed Python 3.14 environment and are pinned by
minimum version in `requirements.txt`; PDF export uses PyMuPDF rather than ReportLab
because PyMuPDF is already required for import and covers both directions.

---

## 2. Layers

```
┌─────────────────────────────────────────────────────────────┐
│ ui/            PySide6 widgets and pages                    │
│                no image algorithms, no SQL                   │
└───────────────┬──────────────────────────────┬──────────────┘
                │ signals / calls              │ calls
┌───────────────▼──────────────┐  ┌────────────▼─────────────┐
│ services/                    │  │ workers/                 │
│ projects, exports, batch     │  │ QThread wrappers around  │
│ orchestration                │  │ core tasks               │
└───────────┬──────────────────┘  └────────────┬─────────────┘
            │                                  │
┌───────────▼──────────────┐  ┌────────────────▼─────────────┐
│ database/  SQLite        │  │ core/  OpenCV, NumPy, Pillow │
│ models, repository       │  │ PyMuPDF — no Qt imports      │
└──────────────────────────┘  └──────────────────────────────┘
```

Rules enforced throughout:

- `core/` never imports PySide6. It can be tested without a GUI (and is).
- `database/` never imports UI or OpenCV.
- `ui/` does not construct SQL; it calls repository or service methods.
- `workers/` is the only place where Qt threading meets processing code.
- Cross-page communication goes through Qt signals owned by `AppContext` or the pages,
  not through direct page lookups.

---

## 3. Startup sequence
 
`main.py` → `app.application.run()`:
 
1. Create `QApplication` and show **custom splash screen** (`FlatScanSplashScreen`) with
   branded logo, version and "Loading..." message.
2. Configure logging: `storage/logs/app.log`, rotating at 1.5 MB with three backups.
3. Create `AppConfig`, which loads `storage/settings.json` (writing defaults on first run).
4. Create the storage tree (`ensure_directories`), falling back to a per-user folder if the
   install location is read-only.
5. Open `Database(storage/app.db)` and apply migrations not yet recorded in
   `schema_migrations`.
6. Seed the five shipped document profiles if the profile table is empty, and persist a
   default profile id when none is configured.
7. Apply the theme stylesheet.
8. Create `AppContext` (config, database, repository, services, signals).
9. Build `MainWindow`: sidebar, seven pages, notifications, menu, status bar.
10. Close splash screen, show main window.
11. Install `sys.excepthook` so unexpected errors are logged and shown as a dialog with
    details, never as a raw console traceback.
12. Enter the event loop.

`PROJECT_ROOT` (writable data) and `RESOURCE_ROOT` (bundled read-only assets) are resolved
separately so a PyInstaller build can load `profiles/default_profiles.json` from
`sys._MEIPASS` while keeping data beside the executable or under `%LOCALAPPDATA%` when
that location is read-only.

---

## 4. Module reference

### app/

| File | Responsibility |
| --- | --- |
| `constants.py` | App identity, supported extensions, output formats, status constants, storage paths, resource paths |
| `config.py` | JSON key/value settings with declared defaults, validation by allow-list, atomic write (`*.tmp` then replace), directory creation |
| `context.py` | `AppContext(QObject)` bundling config, database, repository, services; emits `profilesChanged`, `settingsChanged`, `historyChanged`; temporary-file cleanup |
| `application.py` | Logging, exception hook, dependency bootstrap, `QApplication` and `MainWindow` creation |

### core/

| File | Responsibility |
| --- | --- |
| `image_loader.py` | Pillow decoding (EXIF transpose, Unicode paths), bytes/array/clipboard ingestion, thumbnails, folder listing |
| `corner_detection.py` | Candidate quadrilaterals from Canny, adaptive threshold and Hough lines; scoring, de-duplication, defaults |
| `image_detector.py` | Public detection API: `detect_document`, `suggest_corners`, confidence and message |
| `perspective.py` | Corner ordering, convexity/area validation, transform matrix, warping, serialisation |
| `pipeline.py` | Shared `ProcessingSettings` → `ProcessedDocument`; auto orientation by outline, warp, rotate, enhance, quality |
| `orientation.py` | Quarter-turn rotation, expected-orientation helper, effective size |
| `enhancement.py` | White balance, tone LUT, saturation, unsharp mask, denoise, grayscale, automatic parameter estimation |
| `quality_analyzer.py` | Blur, exposure, shadow, glare, resolution and boundary checks with severities |
| `dimension_calculator.py` | mm ↔ px ↔ DPI conversions with validation and page-orientation swaps |
| `image_exporter.py` | PNG/JPEG/TIFF writing with DPI metadata, conflict resolution, PDF image encoding |
| `pdf_handler.py` | PyMuPDF page rendering, PDF construction, page-size modes, in-memory previews |
| `edit_history.py` | `EditState` and snapshot-based `UndoStack` with labels and JSON serialisation |

### services/

| File | Responsibility |
| --- | --- |
| `project_service.py` | Build/update project records, thumbnails, portable project JSON, load/relink/delete, undo restoration |
| `export_service.py` | Filename token expansion and sanitisation, raster/PDF export orchestration, conflict handling, option defaults |
| `batch_service.py` | Per-file processing with isolated failures, folder collection, filename-based pairing, paired PDF export, batch defaults |

### database/

| File | Responsibility |
| --- | --- |
| `connection.py` | Connection factory (`row_factory`, foreign keys, WAL), migration runner, integrity check, backup |
| `models.py` | Dataclasses: `DocumentProfile`, `ProjectRecord`, `BatchJobRecord`, `BatchItemRecord`, `DashboardStats` |
| `repository.py` | All SQL: profile CRUD and defaults, project CRUD/search/stats/purge, batch jobs and items |
| `migrations/001_initial.sql` | Initial schema and indexes |

### workers/

| File | Responsibility |
| --- | --- |
| `image_worker.py` | `LatestTaskWorker` (newest-request queue), `detect_task`, `render_task`, `pdf_render_task` |
| `batch_worker.py` | `BatchWorker(QThread)` with pause/resume/cancel and per-item signals |
| `export_worker.py` | `ExportWorker(QThread)` for raster queues and combined PDFs |
| `pdf_worker.py` | `build_pdf_task`, `preview_pdf_task`, `PdfRenderWorker` helpers for off-thread PDF work |

### ui/
 
| File | Responsibility |
| --- | --- |
| `main_window.py` | Sidebar, page stack, menu, status bar, signals, project opening, theme reload, shutdown, **recent files menu**, **splash screen**, **keyboard shortcuts dialog** |
| `dashboard.py` | Statistics cards, empty state, recent projects table, recent thumbnails, quick actions, **clickable stat cards for history filtering** |
| `correction_studio.py` | Editor state, detection/render scheduling, corner canvas, result preview, enhancement controls, quality list, save/export, **detection confidence bar**, **auto-save draft**, **metadata tab**, **active handle highlight**, **zoom to corner** |
| `batch_window.py` | Queue, settings, pairing, worker control, counters, retry, manual review hand-off, **drag-to-reorder queue**, **duration column** |
| `profile_manager.py` | Profile table and editor with validation and default management, **aspect ratio preview** |
| `history_window.py` | History table, details, reopen, re-export, relink, purge/delete, **copy path buttons**, **status filter search syntax** |
| `export_window.py` | Export Center, quick export dialog, PDF preview dialog, history picker, **export presets** |
| `settings_window.py` | All persistent settings with folder browsers and maintenance actions, **theme preview dialog**, **tooltips on all fields** |
| `pdf_dialog.py` | PDF page selection, rendering resolution and preview |
| `icons.py` | QPainter-drawn icon set (no binary assets) |
| `image_utils.py` | NumPy BGR ↔ `QImage`/`QPixmap` |
| `widgets/` | CornerHandle, ImageCanvas, ImagePreview, ZoomControls, ProgressPanel, NotificationHost, **AspectRatioPreview** |
| `styles/` | Theme token dictionaries and the shared QSS |

---

## 5. Correction pipeline

Entry points: `core.pipeline.correct_document` (studio, PDF/history re-export) and
`core.pipeline.process_document` (detect then correct, used by batch).

```
source BGR image + corners + ProcessingSettings
        │
        ├─ order_points + is_valid_quad          (reject degenerate outlines)
        │
        ├─ oriented_quad                          (auto landscape/portrait alignment)
        │
        ├─ output_pixel_size(mm, mm, dpi, 0)      (w = mm/25.4*dpi, rounded)
        │
        ├─ warp_perspective                        (single cv2.warpPerspective)
        │
        ├─ rotate_image × manual quarter turn      (output dims swap for 90/270)
        │
        ├─ base_image (unenhanced) ────────────────► Before/After comparison
        │
        ├─ apply_enhancements (copy) ──────────────► final image
        │
        └─ analyze_quality (optional) ─────────────► issues + severity
```

`ProcessedDocument` keeps both images, the source corners, effective rotation, output
size, settings and the quality report. Nothing is written to disk at this stage; export
is a separate decision.

### `ProcessingSettings`

- physical width/height in mm and DPI,
- manual rotation (0/90/180/270),
- `auto_orientation` flag,
- interpolation name,
- enhancement parameter dictionary,
- `apply_enhancement`.

`expected_landscape()` returns `None` for square or invalid sizes, so no automatic
rotation is guessed.

### Why one warp

The image is warped once, directly into the target pixel dimensions. Rotating afterwards
uses `cv2.rotate`, which is lossless. Avoiding a second warp prevents double resampling
and keeps the physical aspect ratio exact.

When `auto_orientation` rolls the sampling outline so the document's long edge maps to
the page width, the warp is called with `order=False`; `compute_transform` still validates
convexity and area but keeps the caller's corner sequence. Re-sorting there would discard
the roll and squeeze a sideways document into the page.

---

## 6. Detection engine

`detect_candidates(image, sensitivity)` returns up to eight scored, de-duplicated
candidates. The image is first resized so its longest side is at most **1280 px**; all
coordinates are scaled back afterwards.

### Pre-processing

- Grayscale → CLAHE (`clipLimit=2.0`, 8×8 tiles) → bilateral filter (9, 45, 45).
- Automatic Canny thresholds from the median: `sigma = 0.33 + 0.12 × (1 − sensitivity)`.

### Candidate sources

1. **Canny contours** — 3×3 close (2 iterations), `RETR_LIST`, top 25 contours by area.
   Contours below `min_area = (0.01 + 0.06 × (1 − sensitivity)) × image area` are
   skipped. Several `approxPolyDP` epsilons (1.5%–6% of perimeter) are tried; the first
   four-point result that validates wins.
2. **Near-rectangular blobs** — if no 4-point approximation exists, a minimum-area
   rectangle is accepted when contour area / hull area > 0.86, suggesting a card with
   noisy edges.
3. **Adaptive thresholding** — Gaussian adaptive threshold with block size
   `31 + 8 × round(2 × sensitivity)` (forced odd) and `C = 7`, both normal and inverted.
4. **Hough lines** — probabilistic Hough on the Canny image with
   `threshold = 40 + 60 × (1 − s)`, `minLineLength = (0.18 + 0.12 × (1 − s)) × min side`,
   `maxLineGap = 25%` of that. Lines are grouped into near-horizontal and near-vertical,
   the outermost six of each are kept, and the extreme midpoints produce top, bottom,
   left and right lines. Intersections form the quad; intersections outside the frame by
   more than 5% are rejected.
5. **Whole-frame fallback** — a 1% inset rectangle, deliberately scored low, for cards
   that fill the photo and expose no boundary.

### Scoring

Each candidate receives:

| Component | Weight | Meaning |
| --- | --- | --- |
| Area ratio | 0.17 | 0.02–0.97 of the frame; nearly-frame candidates penalised |
| Rectangularity | 0.19 | 1.0 for right angles, falling with mean corner deviation |
| Edge strength | 0.23 + 0.06·s | Mean Sobel magnitude sampled along the four edges |
| Background contrast | 0.16 + 0.06·s | Inside vs immediate outside intensity difference |
| Aspect plausibility | 0.15 | Distance from common document ratios (1.585, 1.414, 1.42, 1.5, 1.6, 1.33) |
| Convexity | 0.10 | Hard requirement in practice; invalid outlines are rejected earlier |

The weighted sum is divided by 1.10 and clamped to 0–1. Candidates whose intersection
over union exceeds 0.85 are merged, keeping the higher score. A best score at or above
**0.42** is considered usable (`CONFIDENCE_USABLE`); below that the result is still
returned for manual correction but reported as uncertain.

`default_quad(image, inset=0.06)` provides a valid starting outline when detection cannot
produce one.

### Why not "largest rectangle"

A table edge, a laptop, a document tray or a frame line can be larger than the card and
still rectangular. Area is only one of six factors, edge and contrast support must be
real, and the aspect prior rejects extreme shapes. The tests verify accuracy against
known ground-truth corners rather than only checking "something was found".

---

## 7. Geometry, dimensions and orientation

**Corner ordering** (`perspective.order_points`) uses the classic sum/difference method
(TL = minimum x+y, BR = maximum x+y, TR = minimum y−x, BL = maximum y−x) with an
angular fallback around the centroid for diamond-like inputs. Duplicate points raise
`InvalidQuadrilateral`.

**Validation** requires four distinct points, convexity via consistent cross-product
signs, area above a threshold and minimum side length. The canvas uses stricter limits
than the pipeline so interactive edits stay sane.

**Warping** builds a destination rectangle at `(width−1, height−1)` and calls
`cv2.getPerspectiveTransform` + `cv2.warpPerspective` with `BORDER_REPLICATE`, which
avoids black seams when an edge is very close to the source border. Interpolation is
selectable (Nearest, Linear, Cubic, Lanczos; Cubic default).

**Physical size** uses `dimension_calculator.output_pixel_size`, which validates mm and
DPI, converts each axis and swaps them for 90°/270° output rotation.

**Auto orientation** has two separate meanings, kept deliberately distinct:

1. *Sampling alignment* (`pipeline.oriented_quad`): if the profile expects landscape but
   the ordered outline's width/height ratio is clearly portrait (or vice versa), the
   outline is rotated by one corner step before warping. The document's aspect ratio is
   preserved instead of stretching a sideways card into a landscape rectangle.
2. *Manual rotation*: the user can turn the finished page by 90°/180° at any time; output
   width and height swap accordingly.

Square profiles or unknown dimensions skip automatic alignment. The direction of a
sideways capture is ambiguous without OCR, so one quarter turn is chosen and the manual
buttons remain available.

---

## 8. Enhancement and quality analysis

Enhancement is applied to a copy, in this order:

1. White balance (gray-world channel scaling).
2. Grayscale conversion, or saturation/colour boost in HSV.
3. Tone curve: gamma, contrast and brightness combined into a 256-entry LUT
   (`cv2.LUT`), so three controls cost one pass.
4. Denoise (`fastNlMeansDenoisingColored`, strength scales with the slider).
5. Unsharp mask (Gaussian blur radius 1.4, strength from the slider).

`is_identity` short-circuits the neutral state, returning an unchanged copy. Parameters
are clamped by declared limits, so values loaded from old projects cannot break the
pipeline.

**Auto enhance** inspects mean, standard deviation and 2nd/98th percentiles:

- dark mean → gamma above 1, bright mean → gamma below 1;
- low spread or low deviation → modest contrast increase;
- extreme mean → small brightness correction;
- white balance always on, mild sharpening, optional denoise when local differences are
  high.

It is a conservative starting point; nothing claims detail restoration.

**Quality analysis** (`quality_analyzer.analyze_quality`) reports:

| Check | Threshold |
| --- | --- |
| Blur | Laplacian variance < 45 critical, < 110 warning |
| Underexposure | mean < 55 or > 45% of pixels below 40 |
| Overexposure | mean > 205 or > 30% of pixels above 245 |
| Shadow | brightest vs darkest row/column mean difference > 85 |
| Glare | > 4% of pixels above 250 (critical above 12%) |
| Low resolution | fewer than 0.5 megapixels |
| Below target | source smaller than 75% of the requested output |
| Boundary | detection confidence < 0.45 |

Each issue has a code, severity (`info` / `warning` / `critical`), title and message.
Messages state consequences rather than promising repairs.

---

## 9. Edit state and undo/redo

`EditState` contains only serialisable, non-pixel data:

```python
corners: list[[x, y]]          # in original image coordinates
rotation: int                  # 0/90/180/270 manual
auto_orientation: bool
enhancement: dict              # brightness, contrast, ..., white_balance, grayscale
interpolation: str
```

`UndoStack` stores `(EditState clone, label)` pairs with an index, a 60-entry limit and a
`suspend()` context manager for coalescing. `push` ignores snapshots identical to the
current one, truncates redo entries when a new edit is made, and notifies listeners.

The Correction Studio keeps a separate **working** state cloned from the stack's current
snapshot. All live edits mutate the working copy; `_push(label)` stores a clone. This is
what makes undo correct: storing mutations directly into a stack entry would corrupt the
snapshot that undo is supposed to restore.

Undo/redo labels appear in the tooltips ("Contrast", "Rotate 90°", "Auto-detect corners",
…). The full stack is serialised into the project record and restored on reopen, so
history survives sessions.

---

## 10. Threading model

| Worker | Pattern | Used for |
| --- | --- | --- |
| `LatestTaskWorker` | persistent `QThread`, mutex + wait condition, only the newest request is executed | Studio detection and rendering; paired PDF generation |
| `BatchWorker` | `QThread` loop with pause/cancel flags | Batch processing |
| `ExportWorker` | `QThread` over the export queue | Export Center |
| `PdfRenderWorker` / task functions | same latest-request pattern | available for heavier PDF work; current dialogs render small previews synchronously |

**Stale-result protection.** The Studio increments a token for every detection/render
request and passes it to the worker. Results carrying an older token are discarded, so a
slow render cannot overwrite a newer one.

**Responsiveness.** Slider drags can submit many renders; the worker drops all but the
newest pending payload instead of queueing them. Large warps therefore do not build a
backlog.

**Database thread affinity.** SQLite access happens on the UI thread only. Batch workers
write output files and emit per-file results; the page records them in the database as
signals arrive. This keeps the connection simple and avoids cross-thread transaction
hazards.

**Shutdown.** `MainWindow.closeEvent` calls `studio.shutdown()` and `batch.shutdown()`,
which stop workers and wait briefly. Batch cancellation stops after the current file so
no half-written output is left behind.

---

## 11. Persistence

### SQLite schema (`migrations/001_initial.sql`)

- `profiles` — id, name (unique), description, width_mm, height_mm, dpi, format,
  quality, orientation, filename_prefix, active, builtin, is_default, timestamps.
- `projects` — id (UUID), name, source_path, output_path, thumbnail_path, profile_id
  (FK, `ON DELETE SET NULL`), profile_name, corners JSON, settings JSON, status, error,
  document_id, side, timestamps. Indexed by creation date and status.
- `batch_jobs` — id, name, profile_name, output_dir, total, succeeded, failed, status,
  started_at, finished_at.
- `batch_items` — id, job_id (FK `ON DELETE CASCADE`), source_path, output_path, status,
  confidence, error, document_id, side, updated_at.
- `schema_migrations` — applied migration file stems.

Image binaries are never stored. Undo history is embedded inside the project's settings
JSON under `_undo` and stripped back out in `ProjectRecord.from_row`.

### Portable project files

`storage/projects/<id>.json`, written atomically by `ProjectService`:

```json
{
  "format_version": 1,
  "id": "…",
  "name": "…",
  "source_path": "C:/photos/iqama.jpg",
  "output_path": "C:/exports/iqama_iqama.jpg",
  "profile_name": "Saudi Iqama",
  "corners": [[x, y], …],
  "settings": { "rotation": 0, "dpi": 300, "width_mm": 85.6, "…": "…" },
  "status": "success",
  "undo": { "states": [], "labels": [], "index": 0 }
}
```

Opening a project file re-registers it in SQLite, so history stays authoritative while
the JSON remains portable between machines.

### Settings

`storage/settings.json` is a flat object with a declared allow-list. Unknown keys are
ignored on load, and writes go through a temporary file followed by `Path.replace` to
avoid truncated settings on a crash.

### Missing files

Only paths are stored. `ProjectService.identify_missing_source` checks existence and
returns an actionable message; the UI offers relinking rather than deleting the record.

---

## 12. Interface architecture

**Shell.** `MainWindow` owns a `QStackedWidget` with seven pages and a sidebar of
exclusive checkable buttons. Navigation also covers the menu actions. `NotificationHost`
is a transparent overlay child that positions a toast in the top-right and auto-hides on
a timer.

**Cross-page flow** (Qt signals):
 
```
Dashboard ──newCorrection──► MainWindow ──loads file──► Correction Studio
Dashboard ──recordRequested──► MainWindow ──load_project──► Studio / History
Dashboard ──historyFilteredRequested──► MainWindow ──navigate history with filter──► History
Studio ──batchFilesRequested──► MainWindow ──add_files──► Batch
Studio/Batch ──historyChanged──► MainWindow ──refresh──► Dashboard + History
Batch ──reviewRequested(path)──► Studio.load_image_path
Profiles ──ctx.profilesChanged──► Studio/Batch/Settings pickers refresh
Settings ──ctx.settingsChanged──► MainWindow reapplies the theme
```

**Image canvas.** `QGraphicsView` with a scene in image coordinates: a pixmap item, a
dashed polygon item and four `CornerHandle` items. Handles use
`ItemIgnoresTransformations` so they stay the same size at any zoom. **Active handle
highlight** — the keyboard-selected corner (keys 1–4) shows an amber ring. Each handle
validates a proposed position through the canvas, which rejects crossed or concave
outlines by returning the previous position from `itemChange`. Wheel zoom is anchored
under the pointer; panning uses left-drag on empty space or middle-drag. **Double-click
a handle** centres the view on that corner and zooms to 200%.

**Preview.** `ImagePreview` paints a fitted pixmap and, in compare mode, clips the before
image to the left of a draggable divider and the after image to the right, with labels.

**Styling.** `styles.qss` uses `@[token]` placeholders replaced by the active theme's
colour dictionary. Both themes share the same structural rules. Icons are generated with
`QPainter` at runtime, so no binary image assets are required.

**Controls.** All destructive or risky operations confirm first (replacing files,
deleting records, resetting the editor). Controls are disabled until an image is loaded,
and during batch runs. Progress and status are always visible in the bottom bar.

---

## 13. Export naming and conflicts

`build_filename` expands `{name}`, `{profile}`, `{side}`, `{date}`, `{time}`, `{dpi}` and
`{index}`, sanitises Windows-invalid characters and whitespace, appends missing profile
or side segments once, and guarantees the correct extension.

`resolve_target` implements the three policies:

- `rename` → first free `stem_n` (up to 10 000 attempts),
- `skip` → return `None`, caller reports a skip,
- `replace` → the same path, after the UI has asked once.

Raster writes go through Pillow with DPI metadata (`dpi=(x, y)`) for PNG, JPEG and TIFF;
JPEG also carries the requested quality and no chroma subsampling. PDFs are built by
PyMuPDF: each image is JPEG-encoded once and inserted into a page whose size follows the
`fit`, A4, A5, Letter or physical-size mode, with aspect ratio preserved and optional
margins.

---

## 14. Error handling and logging

Typed exceptions define failure categories:

| Exception | Raised by |
| --- | --- |
| `ImageLoadError` / `UnsupportedFormatError` | loading |
| `InvalidQuadrilateral` | geometry and pipeline |
| `DimensionError` | dimension calculations |
| `ExportError` | raster/PDF writing |
| `DatabaseError` | SQLite operations |

The UI catches these at the action boundary and shows a message box or toast with an
actionable explanation. Batch processing wraps per-file work, so one bad file becomes a
failed row rather than an aborted job. Unexpected exceptions are caught by the global
hook, logged with a full traceback and shown as a dialog with detailed text.

Logging goes to `storage/logs/app.log` (rotating, 1.5 MB × 3) and warnings also reach
stderr. No document content or personal identifiers are logged — only paths, sizes,
operations and errors.

---

## 15. Performance considerations

- Detection runs on a ≤1280 px copy, keeping per-photo detection in the low hundreds of
  milliseconds on typical hardware.
- The pipeline performs exactly one perspective warp and a lossless rotation.
- Rendering is debounced by dropping superseded requests rather than queueing them.
- Pixmaps are converted once per result and reused by the preview; thumbnails are cached
  on disk.
- Denoise and Lanczos are the most expensive options and are opt-in; Cubic is the
  default.
- SQLite connections are short-lived (`connect` per operation) with WAL enabled, so the
  UI never holds a long transaction open.

No specific timing claims are made here: performance was not benchmarked across a range
of hardware, and the numbers depend heavily on image size and chosen options.

---

## 16. Testing

`pytest` runs 115 tests, all GUI-free except the separately executed offscreen smoke check.

- **Fixtures** (`tests/conftest.py`) generate card photos by warping a synthetic card
  image into a textured background with known ground-truth corners. No sample photos or
  personal data are needed.
- **Detection** is measured against those corners (tolerance 30 px) rather than only
  "something was found"; blank images must not produce confident results.
- **Perspective** compares the warp output against the original synthetic card with a
  mean absolute difference, which would fail immediately if corner order were inverted.
- **Dimensions** assert exact pixel sizes (1011 × 638 at 300 DPI for ID-1), rotation
  swaps, and rejection of invalid values.
- **Export** reads back embedded DPI, verifies rename/skip/replace, and hashes the source
  file before and after to prove it is untouched.
- **Database/profiles** cover schema creation, CRUD, uniqueness, built-in protection,
  statistics, purge, settings round-trip, project JSON round-trip, relinking and
  undo/redo serialisation.

The offscreen smoke check instantiated the real main window, visited all seven pages,
loaded a synthetic photo through detection and warping, rotated, undid, saved a project
and shut the workers down cleanly.

Not covered automatically: mouse dragging in the canvas, visual layout at different
resolutions, actual batch progress dialogs and real-world camera photos.

---

## 17. Extension points

- **New detection strategy** — add a candidate source in `corner_detection.py` and feed
  it into `raw_quads`; scoring and de-duplication are shared.
- **New document profile** — data only: `profiles/default_profiles.json` for shipped
  defaults, or the profile manager at runtime.
- **New export token** — extend `build_filename` and validate in the UI tooltip.
- **OCR (optional, local)** — add a service that runs only on explicit user action and
  never writes results into the database by default; the design keeps images out of
  SQLite.
- **Additional page** — create a `QWidget`, register it in `MainWindow.pages` and
  `NAV_ITEMS`, and pass `AppContext` for services.
- **Different PDF engine** — `pdf_handler.py` is the single boundary; ReportLab or
  another writer could replace it without touching the UI.

---

## 18. Trade-offs and known limitations

| Decision | Reason | Consequence |
| --- | --- | --- |
| Heuristic detection, no ML model | offline, no large dependency, predictable behaviour | extreme backgrounds or glare require manual corners |
| PyMuPDF for PDF in and out | one dependency already required for import | output styling is deliberately plain |
| JSON settings instead of QSettings | inspectable, portable, easy to test | manual validation and path handling |
| SQLite connection per operation | thread simplicity, WAL safety | small per-call overhead |
| Snapshot undo rather than command objects | simple, serialisable, robust | memory grows with history (capped at 60) |
| Exact physical pixel output | meets the sizing requirement | low-resolution sources are upscaled and warned about |
| No OCR | privacy and scope | no text search or identifier extraction |
| Autosave only on export/save | avoids record spam | unsaved explorations are not in history |
| Auto orientation picks one quarter turn | direction is ambiguous without reading text | upside-down results are fixed manually |

These are documented in the UI and in `README.md` rather than hidden.
