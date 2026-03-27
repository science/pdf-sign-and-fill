import os

import fitz
import pytest
from pdfsign.core import PdfDocument


class TestUndoClear:
    def test_undo_removes_last(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "First", default_font)
        doc.add_text(0, 72, 150, "Second", default_font)
        assert len(doc.pending_annotations()) == 2
        assert doc.undo() is True
        assert len(doc.pending_annotations()) == 1
        assert doc.pending_annotations()[0].text == "First"

    def test_undo_empty_returns_false(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        assert doc.undo() is False

    def test_clear_removes_all(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "First", default_font)
        doc.add_text(0, 72, 150, "Second", default_font)
        doc.clear()
        assert len(doc.pending_annotations()) == 0

    def test_clear_empty_is_noop(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        doc.clear()
        assert len(doc.pending_annotations()) == 0


class TestSaveEdgeCases:
    def test_save_without_annotations(self, simple_pdf, tmp_output):
        doc = PdfDocument(simple_pdf)
        doc.save(tmp_output)
        assert os.path.exists(tmp_output)
        result = fitz.open(tmp_output)
        assert len(result) == 1
        result.close()

    def test_save_does_not_modify_original(self, simple_pdf, default_font, tmp_output):
        original_size = os.path.getsize(simple_pdf)
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "ModifiedText", default_font, font_size=24)
        doc.save(tmp_output)
        # Original file should be unchanged
        assert os.path.getsize(simple_pdf) == original_size
        # Original should NOT contain the new text
        orig = fitz.open(simple_pdf)
        assert "ModifiedText" not in orig[0].get_text()
        orig.close()

    def test_mixed_annotations_across_pages(self, medium_pdf, default_font, signature_png, tmp_output):
        doc = PdfDocument(medium_pdf)
        doc.add_text(0, 72, 72, "TextOnPageZero", default_font)
        doc.add_image(2, 72, 400, signature_png, 150, 50)
        doc.add_text(5, 72, 72, "TextOnPageFive", default_font)
        assert len(doc.pending_annotations()) == 3
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        assert "TextOnPageZero" in result[0].get_text()
        assert "TextOnPageFive" in result[5].get_text()
        assert len(result[2].get_images()) > 0
        result.close()

    def test_save_after_undo(self, simple_pdf, default_font, tmp_output):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Keep", default_font)
        doc.add_text(0, 72, 150, "Remove", default_font)
        doc.undo()
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        text = result[0].get_text()
        assert "Keep" in text
        assert "Remove" not in text
        result.close()
