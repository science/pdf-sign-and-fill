# PDF Simple Signing

A minimal Linux tool to stamp text and signature images onto PDFs. Built because no free Linux PDF tool reliably handles this simple use case on arbitrary PDF documents.

Unlike LibreOffice Draw, Okular, or Evince, this tool does **not** parse or re-render the PDF layout. It overlays content directly onto the page content stream using PyMuPDF, so it works on any valid PDF regardless of internal complexity.

## Installation

Requires Python 3.10+ and a Linux desktop with PyQt6 support.

```bash
git clone https://github.com/science/pdf-simple-signing.git
cd pdf-simple-signing
./install.sh
```

This creates a virtual environment in `build/`, installs dependencies, symlinks the launcher to `~/.local/bin/pdf-simple-signing`, and installs a `.desktop` file so the app appears in your application menu under **Office**.

To run from terminal after install:
```bash
pdf-simple-signing
```

## GUI Usage

```bash
python gui.py
```

### Toolbar (Row 1)
- **Open / Save As** -- open a PDF, save flattened output (always Save As, never overwrites original)
- **Page navigation** -- `< >` buttons or Left/Right arrow keys
- **Zoom** -- 50% to 200% in discrete steps
- **Undo / Clear All** -- Ctrl+Z undoes adds, deletes, repositions, and resizes
- **Text / Image mode** -- radio buttons to select placement mode
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

## Development

```bash
pip install -r requirements.txt
pytest tests/ -v
```

### Architecture

- `pdfsign/core.py` -- Core API (`PdfDocument` class) with zero GUI dependencies
- `pdfsign/cli.py` -- CLI interface consuming the core API
- `gui.py` -- PyQt6 GUI consuming the same core API
- Command-pattern undo stack with `AddAction`, `RemoveAction`, `UpdateAction`, `ClearAction`
- Dirty flag tracks undo stack depth vs. save point

### Tests

98 tests covering core API, GUI logic, undo stack, dirty flag, image picker, resize behavior, and settings persistence.

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0), as required by its dependency on [PyMuPDF](https://pymupdf.readthedocs.io/) which is AGPL-3.0 licensed.
