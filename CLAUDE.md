# PDF Sign & Fill

Linux tool to stamp text/images onto PDFs and fill AcroForm fields, saving output that round-trips in any standards-compliant viewer. Uses PyMuPDF to write directly to page content streams (for stamps) and to update widget values in place (for form fills) without parsing/re-rendering the original PDF layout.

## Project Structure

```
pdfsign/
├── core.py              # Core API: PdfDocument class
├── cli.py               # CLI interface
tests/
├── conftest.py          # Shared fixtures
├── test_open.py         # Open/inspect tests
├── test_text.py         # Text insertion tests
├── test_image.py        # Image overlay tests
├── test_save.py         # Save/flatten tests
fixtures/                # Test PDF and image files
gui.py                   # PyQt6 GUI (future)
```

## Running Tests

```bash
pytest tests/ -v
```

## CLI Usage

```bash
python -m pdfsign.cli info input.pdf
python -m pdfsign.cli add-text input.pdf output.pdf --text "Name" --page 0 --x 100 --y 200
python -m pdfsign.cli add-image input.pdf output.pdf --image sig.png --page 0 --x 100 --y 500 --width 150 --height 50
python -m pdfsign.cli render input.pdf page.png --page 0 --zoom 2.0
```

## Development Methodology

TDD Red/Green: write failing test first, then implement to pass.

## Architecture

`core.py` has zero GUI dependencies. CLI and GUI both consume the same PdfDocument API.
