# PDF Simple Signing

A minimal Linux tool to stamp text and signature images onto PDFs. Built because no free Linux PDF tool reliably handles this simple use case on arbitrary PDF documents.

Unlike LibreOffice Draw, Okular, or Evince, this tool does **not** parse or re-render the PDF layout. It overlays content directly onto the page content stream using PyMuPDF, so it works on any valid PDF regardless of internal complexity.

## Installation

```bash
pip install PyMuPDF PyQt6 pytest
```

Requires Python 3.10+ and system fonts (Liberation Sans, DejaVu Sans families).

## GUI Usage

```bash
python gui.py
```

### Toolbar (Row 1)
- **Open / Save As** -- open a PDF, save flattened output (always Save As, never overwrites original)
- **Page navigation** -- `< >` buttons or Left/Right arrow keys
- **Zoom** -- 50% to 200% in discrete steps
- **Undo / Clear All** -- Ctrl+Z to undo last annotation
- **Text / Image mode** -- radio buttons to select placement mode
- **Image filename** -- click to quickly switch to image mode with the last-used signature

### Toolbar (Row 2)
- **Font** -- family, size, and color controls for text annotations
- **Text template** -- dropdown of recently used texts with variable expansion
- **Settings** -- configure your name for `{name}` variable

### Placing Text
1. Select **Text** mode (default)
2. Choose font, size, and color
3. Select or type a text template in the dropdown (supports `{date}`, `{name}`)
4. Click on the PDF -- a dialog appears with the expanded text
5. Edit if needed, press OK -- text appears at click position

### Placing Images (Signatures)
1. Click the image filename in the toolbar (or select **Image** mode and **Choose...**)
2. Set W/H dimensions in the spinboxes
3. Click on the PDF -- image is placed at that position
4. Subsequent clicks reuse the same image

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
- Last selected signature image and size
- Font family, size, and color
- Recently used text templates
- Window size and position
- Zoom level
- Last opened PDF directory

Settings are stored in `~/.config/PDF Simple Signing/`.

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

## Running Tests

```bash
pytest tests/ -v
```

## Architecture

- `pdfsign/core.py` -- Core API (`PdfDocument` class) with zero GUI dependencies
- `pdfsign/cli.py` -- CLI interface consuming the core API
- `gui.py` -- PyQt6 GUI consuming the same core API
- `tests/` -- 36 tests covering open, text, image, save, undo, update, and remove
