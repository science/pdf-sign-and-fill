import pytest
from pdfsign.core import PdfDocument


class TestOpenPdf:
    def test_open_valid_pdf(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        assert doc.page_count() >= 1

    def test_open_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            PdfDocument("/nonexistent/file.pdf")

    def test_page_count_simple(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        assert doc.page_count() == 1

    def test_page_count_medium(self, medium_pdf):
        doc = PdfDocument(medium_pdf)
        assert doc.page_count() == 36

    def test_page_size_returns_tuple(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        width, height = doc.page_size(0)
        assert width > 0
        assert height > 0

    def test_page_size_invalid_page_raises(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        with pytest.raises(IndexError):
            doc.page_size(999)

    def test_render_page_returns_png_bytes(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        data = doc.render_page(0, zoom=1.0)
        assert isinstance(data, bytes)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_render_page_zoom_changes_size(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        small = doc.render_page(0, zoom=1.0)
        large = doc.render_page(0, zoom=2.0)
        assert len(large) > len(small)
