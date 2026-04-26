# PDF Sign & Fill

A minimal Linux tool to stamp text/images onto PDFs *and* fill existing AcroForm text fields. Built because no free Linux PDF tool reliably handles these simple use cases on arbitrary PDF documents.

Unlike LibreOffice Draw, Okular, or Evince, this tool does **not** parse or re-render the PDF layout for stamping. It overlays content directly onto the page content stream using PyMuPDF, so it works on any valid PDF regardless of internal complexity. For forms, it fills AcroForm text widgets in place and leaves them interactive on save — the output round-trips in any standards-compliant viewer.

## Why this exists (Linux-only, by design)

On Windows and macOS, [Foxit Reader](https://www.foxit.com/) is a free, no-fuss PDF tool that handles signing (overlay typing/image stamps) and form filling fluently. Foxit isn't available on Linux. The standard Linux PDF tools — Okular, Evince, Xreader, qpdfview — are excellent **readers** but don't reliably fill AcroForm fields or support easily typing/stamping freeform overlays onto a page. LibreOffice Draw can edit some PDFs but re-renders layouts in ways that break complex documents. This project fills the gap: a tiny PyQt6 + PyMuPDF app focused on stamping and form-filling, nothing more. **Targeting Linux only is intentional** — Foxit covers Windows and macOS users, so spending engineering effort on a cross-platform installer would be redundant.

## Installation

Requires Python 3.10+ and a Linux desktop with PyQt6 support.

```bash
git clone https://github.com/science/pdf-sign-and-fill.git
cd pdf-sign-and-fill
./install.sh
```

This creates a virtual environment in `build/`, installs dependencies, symlinks the launcher to `~/.local/bin/pdf-sign-and-fill`, and installs a `.desktop` file so the app appears in your application menu under **Office**. The `.desktop` entry registers the app as a handler for `application/pdf` — you can right-click a PDF in your file manager and choose **Open With → PDF Sign & Fill**, and the file will load directly (no dialog).

To run from terminal after install:
```bash
pdf-sign-and-fill                # empty window
pdf-sign-and-fill path/to/x.pdf  # open a specific PDF
```

If you had a previous install and the `.desktop` file doesn't pass the file path, re-run `./install.sh` to pick up the updated entry.

## GUI Usage

```bash
python gui.py
```

### Modes: Stamp vs Fill

At the left of the toolbar, a **Stamp / Fill** toggle chooses what you're doing:

- **Stamp mode** — overlay new text or images on the page and flatten to a static PDF. Works on any PDF. The Text/Image sub-controls on Row 2 are active.
- **Fill mode** — fill existing AcroForm fields in a form PDF: text fields, checkboxes, radio buttons, and dropdowns. Fillable fields are outlined in blue; click one to interact. Filled fields show green. The Text/Image sub-controls are disabled.

When you open a PDF, the mode is chosen automatically: if the PDF has fillable form widgets, Fill mode is selected; otherwise Stamp. You can switch at any time.

The two modes share the same save pipeline — stamps flatten, form values stay interactive. You can use both modes on the same document (fill the fields that exist, stamp where they don't).

**XFA forms** (Adobe LiveCycle, used by some older government PDFs) aren't supported. If you try to switch to Fill mode on an XFA-only PDF, you'll see a one-time notice telling you to use Stamp mode instead.

### Toolbar (Row 1)
- **Stamp / Fill** -- top-level mode toggle (see above)
- **Open / Save As** -- open a PDF, save the result. Save As pre-fills with the current file's folder and name (matching standard editor behavior); the OS confirms before overwriting an existing file.
- **Page navigation** -- `< >` buttons or Left/Right arrow keys
- **Zoom** -- 50% to 200% in discrete steps
- **Undo / Clear All** -- Ctrl+Z undoes adds, deletes, repositions, resizes, and fills
- **Text / Image mode** -- radio buttons to select stamp placement mode (Stamp mode only)
- **W / H** -- image dimension spinboxes (auto-populated from per-image size memory)

### Toolbar (Row 2)
- **Font** -- family, size, and color controls for text annotations
- **Text template** -- dropdown of recently used texts with variable expansion (`{date}`, `{name}`)
- **Image picker** -- dropdown with thumbnails of recently used images, delete button per entry
- **Settings** -- configure name and date format (strftime with live preview)

### Placing Text
1. Select **Text** mode (default)
2. Choose font, size, and color
3. Select or type a text template in the dropdown (supports `{date}`, `{name}`)
4. Click on the PDF -- a dialog appears with the expanded text
5. Edit if needed, press OK -- text appears at click position

### Placing Images (Signatures)
1. Select an image from the **Image:** dropdown (or choose "Choose file...")
2. Adjust W/H dimensions if needed (remembered per image)
3. Click on the PDF -- image is placed at that position
4. Subsequent clicks reuse the same image and size

### Filling Form Fields (Fill mode)
1. Open a PDF with form fields -- the app auto-selects Fill mode
2. Blue outlines appear on every fillable widget on the current page
3. Interact based on widget type:
   - **Text fields** -- click to open a multi-line, resizable dialog **pre-populated with the field's current value** (your pending edit if you've already touched it, otherwise the value baked into the PDF). Edit and press **OK**, **Clear** to blank the field, or **Cancel** for no change. The field turns green and shows your value over an opaque cover that hides the original baked-in text.
   - **Checkboxes** -- click to toggle on/off. A ✓ appears when checked.
   - **Radio buttons** -- click to select. The chosen radio shows a ●; siblings in the same group automatically deselect on save.
   - **Dropdowns** -- click to pop a menu of choices; pick one. The selected value renders inside the field.
4. Save As -- the PDF is written with your values; fields remain interactive so you (or a recipient) can edit them later in any viewer. Cleared text fields are written truly blank, not as a stale default

The text-field dialog uses a multi-line text area with scrollbars, so memo-style fields with long content are usable. Use Ctrl+Z to undo any fill, toggle, selection, or clear.

#### What's not supported
| Widget | Note |
|---|---|
| Listboxes (multi-select) | Rare; revisit if a user needs it. |
| Signature widgets | Cryptographic (PKI) — different problem. Use Stamp mode to overlay a visual signature image instead. |
| Calculated / JavaScript fields | This tool doesn't run embedded JS, so dependent values aren't recalculated when you fill a source field. Most viewers re-run the PDF's JavaScript on open, so totals/derived fields typically resolve themselves when the recipient opens the saved PDF. |
| Submit / Reset / Print buttons | These are actions, not fields — nothing to "fill." |

### Editing Annotations
- **Select** -- click on an existing annotation (dashed blue border appears)
- **Drag** -- click and drag to reposition
- **Resize images** -- drag corner handles (proportional) or edge handles (free)
- **Delete** -- press Delete/Backspace with annotation selected
- **Deselect** -- press Escape

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Ctrl+O | Open PDF |
| Ctrl+S | Save As |
| Ctrl+Z | Undo |
| Left/Right | Previous/Next page |
| Delete | Remove selected annotation |
| Escape | Deselect |

### Persistent Settings

All settings are saved automatically on close and restored on next launch:
- Recent images with per-image remembered dimensions
- Font family, size, and color
- Recently used text templates
- Name and date format preferences
- Window size and position
- Zoom level
- Last opened PDF directory

Settings are stored in `~/.config/PDF Sign & Fill/`. (Settings from a previous "PDF Simple Signing" install are migrated automatically on first launch.)

## CLI Usage

For scripting or batch operations:

```bash
# Show PDF info
python -m pdfsign.cli info input.pdf

# Add text
python -m pdfsign.cli add-text input.pdf output.pdf \
  --text "John Smith" --page 0 --x 100 --y 200 --font-size 14

# Add signature image
python -m pdfsign.cli add-image input.pdf output.pdf \
  --image signature.png --page 0 --x 100 --y 500 --width 150 --height 50

# Render page as PNG for inspection
python -m pdfsign.cli render input.pdf page0.png --page 0 --zoom 2.0
```

## Development

```bash
pip install -r requirements.txt
pytest tests/ -v
```

### Architecture

- `pdfsign/core.py` -- Core API (`PdfDocument` class) with zero GUI dependencies. Stamps live in `_annotations` (`Annotation` dataclass, type=`text`/`image`); form fills live in a parallel `_fields` list (`FieldFill` dataclass, keyed by AcroForm field name). Both share one undo stack; action dataclasses carry a `list_name` tag.
- `pdfsign/cli.py` -- CLI interface consuming the core API
- `gui.py` -- PyQt6 GUI consuming the same core API. The top-level Stamp/Fill toggle routes clicks: in Fill mode, `mousePressEvent` hit-tests the cached widget rects and opens a prompt; in Stamp mode, the existing stamp flow runs unchanged.
- Command-pattern undo stack with `AddAction`, `RemoveAction`, `UpdateAction`, `ClearAction`
- Dirty flag tracks undo stack depth vs. save point

### Tests

Run `pytest tests/ -v`. Key fixtures in `tests/conftest.py`:
- `simple_pdf`, `medium_pdf` -- non-form PDFs
- `form_pdf` -- 2-field AcroForm PDF built programmatically (fast)
- `multipage_form_pdf` -- 2-page form with a shared field name across pages
- `complex_form_pdf` -- real-world D&D character sheet (2 pages, 260 text + 151 checkbox widgets) copied to `tmp_path` for each test

The D&D sheet is the user-acceptance benchmark: if the tool can fill and round-trip it, the tool works.

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0), as required by its dependency on [PyMuPDF](https://pymupdf.readthedocs.io/) which is AGPL-3.0 licensed.
