# PDF Signing Tool — Implementation Plan

## Context

On Linux, no free tool reliably stamps text (name, date) and images (signatures) onto arbitrary PDFs and saves a flattened result. Existing tools try to parse/re-render PDF internals and break on complex documents. We'll build a minimal tool using PyMuPDF that overlays content onto the existing page content stream without touching the original layout.

## Development Methodology: TDD Red/Green

Adapted from the hot-tub-controller project:

1. **RED**: Write a failing test first, run to prove it fails
2. **GREEN**: Write minimal code to pass, run to prove it passes
3. **REFACTOR**: Clean up while keeping tests green
4. **REPEAT**: Build functionality incrementally with test coverage

**CLI-first approach**: Build and fully test the core PDF manipulation APIs via CLI before building the GUI. The GUI becomes a thin layer over battle-tested APIs.

## Architecture

```
/home/steve/dev/pdf-signing/
├── pdfsign/
│   ├── __init__.py
│   ├── core.py              # Core API: PdfDocument class (open, add_text, add_image, save)
│   └── cli.py               # CLI interface exercising core APIs
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared fixtures (sample PDFs, test images)
│   ├── test_open.py         # Opening/reading PDFs
│   ├── test_text.py         # Text insertion tests
│   ├── test_image.py        # Image overlay tests
│   └── test_save.py         # Save/flatten tests
├── fixtures/
│   ├── simple.pdf           # 1-page minimal PDF (from book-translate)
│   ├── medium.pdf           # 20-page document (MAPS workbook)
│   └── signature.png        # Test transparent PNG signature image
├── gui.py                   # PyQt6 GUI (built last, after CLI+API are solid)
├── requirements.txt         # PyMuPDF, PyQt6, pytest
├── .gitignore
└── CLAUDE.md
```

**Key principle**: `core.py` has zero GUI dependencies. CLI and GUI both consume the same API.

## Core API Design (`pdfsign/core.py`)

```python
class PdfDocument:
    def __init__(self, path: str)
    def page_count(self) -> int
    def page_size(self, page_num: int) -> tuple[float, float]
    def render_page(self, page_num: int, zoom: float) -> bytes  # PNG bytes for preview
    def add_text(self, page_num: int, x: float, y: float, text: str,
                 font_path: str, font_size: float, color: tuple[float,float,float])
    def add_image(self, page_num: int, x: float, y: float,
                  image_path: str, width: float, height: float)
    def pending_annotations(self) -> list  # inspect before save
    def undo(self) -> bool
    def clear(self)
    def save(self, output_path: str)  # always save-as, never overwrite original
```

## CLI Interface (`pdfsign/cli.py`)

Exercises every core API method so we can test without a GUI:

```bash
# Add text to page 0 at position (100, 200), font size 14, black
python -m pdfsign.cli add-text input.pdf output.pdf \
  --page 0 --x 100 --y 200 --text "John Smith" \
  --font-size 14 --color "0,0,0"

# Add image to page 0
python -m pdfsign.cli add-image input.pdf output.pdf \
  --page 0 --x 100 --y 500 --image signature.png \
  --width 150 --height 50

# Info about a PDF
python -m pdfsign.cli info input.pdf

# Render a page as PNG (for visual inspection)
python -m pdfsign.cli render input.pdf page0.png --page 0 --zoom 2.0
```

## Test Fixtures

Copy from existing files on the system:

| Fixture | Source | Purpose |
|---------|--------|---------|
| `fixtures/simple.pdf` | `~/dev/book-translate/test/fixtures/sample.pdf` | 1-page minimal, basic sanity |
| `fixtures/medium.pdf` | `~/dev/book-translate/source-docs/MAPS-Integration-Workbook.pdf` | 20-page, moderate complexity |
| `fixtures/signature.png` | Generated: transparent PNG with "signature" scribble | Image overlay testing |

We'll also generate a simple test signature PNG programmatically in `conftest.py` to avoid depending on external files.

## Implementation Steps

### Phase 0: Project Setup
- `git init` the repo
- Create `.gitignore`, `requirements.txt`, `CLAUDE.md`
- `pip install PyMuPDF pytest` (PyQt6 deferred to GUI phase)
- Copy test fixture PDFs into `fixtures/`
- Create a simple transparent signature PNG for testing

### Phase 1: Core API — Open & Inspect (TDD)
- **RED**: test opening a valid PDF returns page count and page size
- **RED**: test opening a nonexistent file raises clear error
- **RED**: test `render_page` returns valid PNG bytes
- **GREEN**: implement `PdfDocument.__init__`, `page_count`, `page_size`, `render_page`

### Phase 2: Core API — Text Insertion (TDD)
- **RED**: test `add_text` creates a pending annotation
- **RED**: test `save` with text annotation produces a PDF where text is present (verify with PyMuPDF text extraction)
- **RED**: test font size and color are respected
- **RED**: test text on specific page of multi-page PDF
- **GREEN**: implement `add_text` and the text path in `save`

### Phase 3: Core API — Image Insertion (TDD)
- **RED**: test `add_image` creates a pending annotation
- **RED**: test `save` with image produces a PDF with embedded image at correct position/size
- **RED**: test transparent PNG preserves transparency
- **GREEN**: implement `add_image` and the image path in `save`

### Phase 4: Core API — Undo/Clear & Edge Cases (TDD)
- **RED**: test `undo` removes last annotation
- **RED**: test `clear` removes all annotations
- **RED**: test `save` without annotations produces identical PDF
- **RED**: test multiple annotations across multiple pages
- **GREEN**: implement `undo`, `clear`

### Phase 5: CLI
- Build CLI using `argparse` that calls core API methods
- Manual integration testing with real PDFs via CLI
- Verify output PDFs open correctly in multiple viewers (Firefox, Chrome, Evince)

### Phase 6: GUI — Incremental Build with UAT Checkpoints

All GUI code goes in `/home/steve/dev/pdf-signing/gui.py` (single file). Prerequisite: `pip install PyQt6`.

**Widget structure:**
```
QMainWindow
  QToolBar (controls)
  QScrollArea (central widget)
    PdfCanvas(QWidget) — displays QPixmap, handles mousePressEvent, paints overlays
  QStatusBar
```

**Coordinate mapping** (used in every step):
- Render: `page.render_page(page_num, zoom)` returns PNG at `zoom * 72` DPI
- Screen click `(sx, sy)` → PDF point `(sx / zoom, sy / zoom)`
- Both QPainter.drawText and PyMuPDF insert_text use baseline y, so preview matches output

---

#### Step 6a: MVP — Open, View, Click-to-Stamp Fixed Text, Save As

**What the user can do:** Run `python gui.py`, file dialog opens to pick a PDF. Page 0 renders in a scrollable window at zoom 1.5. Click anywhere → hardcoded text ("Signed [today]") stamps at that position (LiberationSans 12pt black). "Save As" button writes flattened output.

**Implementation:**
- `PdfCanvas(QWidget)` inside `QScrollArea`, renders page via `QPixmap.loadFromData(doc.render_page(0, zoom))`
- `mousePressEvent` → `doc.add_text(page, sx/zoom, sy/zoom, text, font_path)` → repaint overlay
- `paintEvent` → draw base pixmap, then iterate `doc.pending_annotations()` and draw each with QPainter
- Toolbar: just `[Save As]` button → `QFileDialog.getSaveFileName` → `doc.save(path)`
- Load font for preview via `QFontDatabase.addApplicationFont(font_path)`

**API exercised:** `__init__`, `render_page`, `add_text`, `pending_annotations`, `save`

**UAT:** Open simple.pdf → click 2-3 spots → Save As → open output in Evince/Firefox → text at correct positions.

---

#### Step 6b: Editable Text Input

**What changes:** Clicking now pops `QInputDialog.getText()` asking for text. User types whatever they want. Cancel = no annotation added. Status bar shows "N annotation(s) pending".

**UAT:** Click → dialog → type "John Smith" → OK → text appears. Click again → type "2026-03-26" → appears. Status bar shows "2 annotation(s) pending". Save and verify.

---

#### Step 6c: Page Navigation

**What changes:** Toolbar gains `[< Prev] Page 1/36 [Next >]`. Navigate multi-page PDFs. Annotations are per-page; navigating back shows prior annotations.

**API exercised:** `page_count`, `page_size` (per page)

**UAT:** Open medium.pdf → go to page 5 → place text → go to page 10 → place text → go back to page 5 → first annotation still visible. Save → verify correct pages in viewer.

---

#### Step 6d: Undo and Clear

**What changes:** Toolbar adds `[Undo]` and `[Clear All]`. Ctrl+Z shortcut for undo. Clear All shows confirmation dialog.

**API exercised:** `undo()`, `clear()`

**UAT:** Place 3 annotations → Ctrl+Z → last one gone → Ctrl+Z → second gone. Place 2 more → Clear All → confirm → all gone. Status bar accurate throughout.

---

#### Step 6e: Image Stamp Mode

**What changes:** Toolbar adds mode toggle: `[Text Mode]` / `[Image Mode]`. In image mode, first click opens file dialog to pick PNG/GIF, places image at click position (default 150×50 pts). Subsequent clicks reuse same image without re-opening dialog. "Choose Image..." button to switch images. Width/height spin boxes for size control.

**API exercised:** `add_image()`

**UAT:** Switch to Image Mode → click → pick signature.png → image appears → click elsewhere → same image placed. Switch to Text Mode → place text → both types visible. Save → verify in viewer.

---

#### Step 6f: Font, Size, and Color Controls

**What changes:** Toolbar adds font family dropdown (Liberation Sans/Serif/Mono, DejaVu Sans/Serif/Mono), size spinbox (8-72, default 12), color picker button. New text annotations use selected settings.

**Font path resolution:**
```python
FONTS = {
    "Liberation Sans": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "Liberation Serif": "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "Liberation Mono": "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "DejaVu Sans": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVu Serif": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "DejaVu Sans Mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
}
```
Color picker: `QPushButton` showing swatch → `QColorDialog` → convert to RGB 0.0-1.0 tuple.

**UAT:** Select Liberation Serif, size 24 → place text → renders large serif. Switch to DejaVu Sans Mono, size 10 → place text → renders small mono. Change color to red → place text → red text. Save → verify all fonts/sizes/colors in viewer.

---

#### Step 6g: Drag-to-Reposition (Text and Images)

**What changes:** Click an existing annotation to select it (highlight border). Drag to reposition. Click on empty space still creates new annotations (as before). ESC deselects.

**Core API change needed:** Add `update_annotation(index, **kwargs)` to `PdfDocument` — allows mutating x/y (and potentially other fields) of an existing annotation by index. Alternatively, annotations can be mutated directly since they're dataclasses — but a method keeps the API clean.

**Implementation:**
- Hit-testing in `mousePressEvent`: check if click is within the bounding box of any existing annotation on the current page. For text: estimate bbox from font metrics (`QFontMetrics.boundingRect`). For images: bbox is `(x, y, x+width, y+height)` in PDF coords.
- If hit: enter "dragging" state, store the annotation index and click offset.
- `mouseMoveEvent`: update annotation x/y by delta (converted to PDF coords). Repaint on each move.
- `mouseReleaseEvent`: end drag state.
- Visual feedback: selected annotation gets a dashed blue border overlay.

**UAT:** Place a text annotation → click on it → drag to new position → release → text is now at new position. Same for image. Save → verify new position in viewer.

---

#### Step 6h: Image Resize (Drag Handles)

**What changes:** When an image annotation is selected, small square handles appear at the corners and edges. Drag a corner handle to resize proportionally. Drag an edge handle to resize in one dimension.

**Core API change needed:** None beyond 6g — just update `width`/`height` on the annotation.

**Implementation:**
- When an image annotation is selected, draw 8 resize handles (4 corners + 4 edge midpoints) as small squares (6x6 px).
- Hit-test handles in `mousePressEvent` before hit-testing annotations. If a handle is hit, enter "resizing" state.
- Corner handles: maintain aspect ratio. Calculate new width/height from mouse delta.
- Edge handles: resize freely in one axis.
- Minimum size constraint: 10x10 PDF points.
- `mouseMoveEvent`: update annotation width/height, repaint.

**UAT:** Place signature image → click to select → drag corner handle → image grows/shrinks proportionally → release. Drag edge handle → stretches in one direction. Save → verify correct size in viewer.

---

#### Step 6i: Zoom Controls

**What changes:** Toolbar adds `[Zoom -] 100% [Zoom +]` controls. Discrete steps: 50%, 75%, 100%, 125%, 150%, 200%. Annotations, handles, and hit-testing all scale correctly.

**Implementation:**
- Store `zoom` as class attribute, default 1.5.
- Zoom buttons cycle through preset levels.
- `refresh_page()` re-renders pixmap at new zoom and resizes canvas.
- All coordinate conversions already use `zoom` factor, so annotations stay in correct positions.
- QScrollArea handles scrollbars automatically when canvas size changes.

**UAT:** Zoom in to 200% → annotations stay positioned correctly → place new annotation → zoom out to 75% → annotation at same PDF position. Save → verify positions unchanged regardless of zoom during editing.

---

#### Step 6j: Open File (Ctrl+O) and Keyboard Shortcuts

**What changes:** Ctrl+O opens a new PDF (prompts to save if pending annotations). Ctrl+S triggers Save As. Window title shows filename. Complete keyboard shortcut set.

**Shortcuts:**
- Ctrl+O: Open PDF
- Ctrl+S: Save As
- Ctrl+Z: Undo
- Delete/Backspace: Remove selected annotation
- Escape: Deselect
- Left/Right arrows: Previous/Next page

**UAT:** Full keyboard-driven workflow without touching the mouse (except for placement clicks).

## Dependencies

```
# requirements.txt
PyMuPDF>=1.24.0
pytest>=8.0.0
# PyQt6>=6.6.0  # uncomment when building GUI
```

## System Fonts (for text insertion)

Already present on the system:
- `/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf`
- `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`
- Plus Serif and Mono variants of both families

## Verification

### Automated (pytest)
```bash
pytest tests/ -v
```

### Manual (CLI)
```bash
# Add text, open result in viewer
python -m pdfsign.cli add-text fixtures/medium.pdf /tmp/test-text.pdf \
  --text "Signed 2026-03-26" --page 0 --x 100 --y 700 --font-size 14
xdg-open /tmp/test-text.pdf

# Add signature image, open result
python -m pdfsign.cli add-image fixtures/medium.pdf /tmp/test-sig.pdf \
  --page 0 --x 100 --y 500 --image fixtures/signature.png --width 150 --height 50
xdg-open /tmp/test-sig.pdf
```
