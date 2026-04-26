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


class TestTextWrap:
    def test_default_wrap_width_is_none(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 100, 200, "Hello", default_font)
        assert doc.pending_annotations()[0].wrap_width is None

    def test_add_text_stores_wrap_width(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 100, 200, "Hello", default_font, wrap_width=120.0)
        assert doc.pending_annotations()[0].wrap_width == 120.0

    def test_save_wraps_long_text_into_multiple_lines(self, simple_pdf, default_font, tmp_output):
        # Width too narrow for the whole string on one line at 12pt.
        long_text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, long_text, default_font, font_size=12, wrap_width=120)
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        words = result[0].get_text("words")  # tuples (x0, y0, x1, y1, word, ...)
        result.close()
        ys = {round(w[1], 1) for w in words if w[4] in long_text.split()}
        # Expect words to land on more than one distinct y-coordinate.
        assert len(ys) >= 2, f"expected wrapped text on multiple lines, got ys={ys}"

    def test_save_wrap_does_not_truncate_overflowing_text(self, simple_pdf, default_font, tmp_output):
        # 50 short words wrapped at narrow width — would overflow most boxes.
        words_in = [f"w{i}" for i in range(50)]
        long_text = " ".join(words_in)
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, long_text, default_font, font_size=10, wrap_width=80)
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        text_out = result[0].get_text()
        result.close()
        # Every word must appear in the output (no bottom truncation).
        for w in words_in:
            assert w in text_out, f"word {w!r} missing — text was truncated"

    def test_save_uses_point_mode_when_wrap_none(self, simple_pdf, default_font, tmp_output):
        # Without wrap, a long string stays on one line (no auto-wrap).
        long_text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 50, 100, long_text, default_font, font_size=12)
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        words = result[0].get_text("words")
        result.close()
        ys = {round(w[1], 1) for w in words if w[4] in long_text.split()}
        assert len(ys) == 1, f"expected single-line output, got ys={ys}"
