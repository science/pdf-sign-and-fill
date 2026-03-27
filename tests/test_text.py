import fitz
import pytest
from pdfsign.core import PdfDocument


class TestTextInsertion:
    def test_add_text_creates_annotation(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 100, 200, "Hello", default_font)
        assert len(doc.pending_annotations()) == 1
        ann = doc.pending_annotations()[0]
        assert ann.type == "text"
        assert ann.text == "Hello"

    def test_add_text_invalid_page_raises(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        with pytest.raises(IndexError):
            doc.add_text(999, 100, 200, "Hello", default_font)

    def test_save_with_text_embeds_text(self, simple_pdf, default_font, tmp_output):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "TestString123", default_font, font_size=14)
        doc.save(tmp_output)
        # Verify text is in the output PDF
        result = fitz.open(tmp_output)
        text = result[0].get_text()
        assert "TestString123" in text
        result.close()

    def test_save_with_custom_font_size(self, simple_pdf, default_font, tmp_output):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "BigText", default_font, font_size=36)
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        text = result[0].get_text()
        assert "BigText" in text
        result.close()

    def test_save_with_color(self, simple_pdf, default_font, tmp_output):
        doc = PdfDocument(simple_pdf)
        # Red text
        doc.add_text(0, 72, 72, "RedText", default_font, font_size=12,
                     color=(1.0, 0.0, 0.0))
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        text = result[0].get_text()
        assert "RedText" in text
        result.close()

    def test_text_on_specific_page_of_multipage(self, medium_pdf, default_font, tmp_output):
        doc = PdfDocument(medium_pdf)
        doc.add_text(5, 72, 72, "PageFiveText", default_font, font_size=12)
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        # Text should be on page 5, not page 0
        assert "PageFiveText" not in result[0].get_text()
        assert "PageFiveText" in result[5].get_text()
        result.close()

    def test_multiple_text_annotations(self, simple_pdf, default_font, tmp_output):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "First", default_font)
        doc.add_text(0, 72, 150, "Second", default_font)
        assert len(doc.pending_annotations()) == 2
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        text = result[0].get_text()
        assert "First" in text
        assert "Second" in text
        result.close()
