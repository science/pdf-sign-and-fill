import os

import fitz
import pytest
from pdfsign.core import PdfDocument


class TestPathProperty:
    def test_pdf_document_path_property(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        assert doc.path == simple_pdf


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


class TestUpdateAnnotation:
    def test_update_position(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        doc.update_annotation(0, x=200, y=300)
        ann = doc.pending_annotations()[0]
        assert ann.x == 200
        assert ann.y == 300

    def test_update_image_size(self, simple_pdf, signature_png):
        doc = PdfDocument(simple_pdf)
        doc.add_image(0, 72, 400, signature_png, 150, 50)
        doc.update_annotation(0, width=200, height=80)
        ann = doc.pending_annotations()[0]
        assert ann.width == 200
        assert ann.height == 80

    def test_update_preserves_other_fields(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font, font_size=14, color=(1, 0, 0))
        doc.update_annotation(0, x=200)
        ann = doc.pending_annotations()[0]
        assert ann.x == 200
        assert ann.y == 72  # unchanged
        assert ann.text == "Hello"
        assert ann.font_size == 14
        assert ann.color == (1, 0, 0)

    def test_update_invalid_index_raises(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        with pytest.raises(IndexError):
            doc.update_annotation(5, x=100)

    def test_update_saved_correctly(self, simple_pdf, default_font, tmp_output):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Moved", default_font)
        doc.update_annotation(0, x=300, y=500)
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        assert "Moved" in result[0].get_text()
        result.close()

    def test_remove_annotation(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "First", default_font)
        doc.add_text(0, 72, 150, "Second", default_font)
        doc.add_text(0, 72, 200, "Third", default_font)
        doc.remove_annotation(1)
        anns = doc.pending_annotations()
        assert len(anns) == 2
        assert anns[0].text == "First"
        assert anns[1].text == "Third"

    def test_remove_invalid_index_raises(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        with pytest.raises(IndexError):
            doc.remove_annotation(0)


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
