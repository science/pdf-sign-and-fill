"""Tests for the undo stack and dirty flag — TDD Red/Green cycles."""

import pytest
from pdfsign.core import PdfDocument


class TestUndoAdd:
    def test_undo_add_removes_last(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "First", default_font)
        doc.add_text(0, 72, 150, "Second", default_font)
        assert doc.undo() is True
        assert len(doc.pending_annotations()) == 1
        assert doc.pending_annotations()[0].text == "First"

    def test_undo_add_empty_returns_false(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        assert doc.undo() is False

    def test_undo_add_image(self, simple_pdf, signature_png):
        doc = PdfDocument(simple_pdf)
        doc.add_image(0, 72, 400, signature_png, 150, 50)
        assert doc.undo() is True
        assert len(doc.pending_annotations()) == 0

    def test_multiple_undo(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "A", default_font)
        doc.add_text(0, 72, 150, "B", default_font)
        doc.add_text(0, 72, 200, "C", default_font)
        doc.undo()
        doc.undo()
        assert len(doc.pending_annotations()) == 1
        assert doc.pending_annotations()[0].text == "A"


class TestUndoRemove:
    def test_undo_remove_restores_annotation(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "First", default_font)
        doc.add_text(0, 72, 150, "Second", default_font)
        doc.remove_annotation(0)  # removes "First"
        assert len(doc.pending_annotations()) == 1
        assert doc.undo() is True
        anns = doc.pending_annotations()
        assert len(anns) == 2
        assert anns[0].text == "First"
        assert anns[1].text == "Second"

    def test_undo_remove_restores_at_correct_index(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "A", default_font)
        doc.add_text(0, 72, 150, "B", default_font)
        doc.add_text(0, 72, 200, "C", default_font)
        doc.remove_annotation(1)  # removes "B"
        doc.undo()
        assert doc.pending_annotations()[1].text == "B"

    def test_undo_remove_then_undo_add(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "A", default_font)
        doc.remove_annotation(0)
        doc.undo()  # undo remove → "A" back
        doc.undo()  # undo add → empty
        assert len(doc.pending_annotations()) == 0


class TestUndoUpdate:
    def test_undo_drag_restores_position(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        doc.begin_edit(0)
        doc.update_annotation(0, x=200, y=300)
        doc.update_annotation(0, x=250, y=350)  # simulate multiple moves
        doc.commit_edit()
        ann = doc.pending_annotations()[0]
        assert ann.x == 250 and ann.y == 350
        doc.undo()
        ann = doc.pending_annotations()[0]
        assert ann.x == 72 and ann.y == 72

    def test_undo_resize_restores_size(self, simple_pdf, signature_png):
        doc = PdfDocument(simple_pdf)
        doc.add_image(0, 100, 100, signature_png, 150, 50)
        doc.begin_edit(0)
        doc.update_annotation(0, width=300, height=100)
        doc.commit_edit()
        doc.undo()
        ann = doc.pending_annotations()[0]
        assert ann.width == 150 and ann.height == 50

    def test_commit_without_change_no_undo_entry(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        doc.begin_edit(0)
        # No update_annotation calls — user clicked but didn't move
        doc.commit_edit()
        # Undo should pop the AddAction, not a no-op UpdateAction
        doc.undo()
        assert len(doc.pending_annotations()) == 0

    def test_begin_edit_invalid_index_raises(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        with pytest.raises(IndexError):
            doc.begin_edit(0)

    def test_begin_edit_auto_commits_previous(self, simple_pdf, default_font):
        """If begin_edit called while another edit is pending, auto-commit first."""
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "A", default_font)
        doc.add_text(0, 72, 150, "B", default_font)
        doc.begin_edit(0)
        doc.update_annotation(0, x=200)
        # Start editing another without committing first
        doc.begin_edit(1)
        doc.update_annotation(1, x=300)
        doc.commit_edit()
        # Undo the second edit
        doc.undo()
        assert doc.pending_annotations()[1].x == 72
        # Undo the auto-committed first edit
        doc.undo()
        assert doc.pending_annotations()[0].x == 72


class TestUndoClear:
    def test_undo_clear_restores_all(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "First", default_font)
        doc.add_text(0, 72, 150, "Second", default_font)
        doc.clear()
        assert len(doc.pending_annotations()) == 0
        doc.undo()
        assert len(doc.pending_annotations()) == 2
        assert doc.pending_annotations()[0].text == "First"
        assert doc.pending_annotations()[1].text == "Second"

    def test_clear_empty_no_undo_entry(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        doc.clear()
        assert doc.undo() is False

    def test_undo_clear_then_undo_adds(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "A", default_font)
        doc.add_text(0, 72, 150, "B", default_font)
        doc.clear()
        doc.undo()  # undo clear → both back
        doc.undo()  # undo add "B"
        assert len(doc.pending_annotations()) == 1
        assert doc.pending_annotations()[0].text == "A"


class TestDirtyFlag:
    def test_new_document_is_clean(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        assert doc.is_dirty is False

    def test_add_makes_dirty(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        assert doc.is_dirty is True

    def test_save_marks_clean(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        doc.mark_saved()
        assert doc.is_dirty is False

    def test_undo_to_save_point_is_clean(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "A", default_font)
        doc.mark_saved()
        doc.add_text(0, 72, 150, "B", default_font)
        assert doc.is_dirty is True
        doc.undo()
        assert doc.is_dirty is False

    def test_undo_past_save_is_dirty(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        doc.mark_saved()
        doc.undo()
        assert doc.is_dirty is True

    def test_reposition_after_save_is_dirty(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        doc.mark_saved()
        assert doc.is_dirty is False
        doc.begin_edit(0)
        doc.update_annotation(0, x=200)
        doc.commit_edit()
        assert doc.is_dirty is True

    def test_undo_reposition_back_to_save_point(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        doc.mark_saved()
        doc.begin_edit(0)
        doc.update_annotation(0, x=200)
        doc.commit_edit()
        doc.undo()
        assert doc.is_dirty is False

    def test_remove_after_save_is_dirty(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        doc.mark_saved()
        doc.remove_annotation(0)
        assert doc.is_dirty is True

    def test_clear_after_save_is_dirty(self, simple_pdf, default_font):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        doc.mark_saved()
        doc.clear()
        assert doc.is_dirty is True
