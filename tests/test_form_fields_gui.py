"""GUI integration tests for Stamp/Fill mode."""
from unittest.mock import patch

import pytest

from PyQt6.QtCore import QSettings, Qt, QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QMessageBox


@pytest.fixture
def _isolated(qapp):
    QSettings("PDF Sign & Fill", "PDF Sign & Fill").clear()
    with patch("gui.QFileDialog.getOpenFileName", return_value=("", "")), \
         patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        yield


@pytest.fixture
def mw_factory(_isolated):
    """Return a callable that creates a MainWindow and yields it. Caller responsible for cleanup."""
    created = []
    def _make(initial_path=None):
        from gui import MainWindow
        mw = MainWindow(initial_path=initial_path)
        mw.hide()
        created.append(mw)
        return mw
    yield _make
    for mw in created:
        if mw.doc:
            mw.doc.mark_saved()
        mw.close()


class TestAutoMode:
    def test_auto_selects_fill_on_form_pdf(self, mw_factory, form_pdf):
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf)
        assert mw.top_mode == "fill"
        assert mw.btn_fill.isChecked()

    def test_auto_selects_stamp_on_non_form_pdf(self, mw_factory, simple_pdf):
        mw = mw_factory(initial_path=simple_pdf)
        assert mw.top_mode == "stamp"
        assert mw.btn_stamp.isChecked()


class TestModeToggle:
    def test_text_toolbar_disabled_in_fill_mode(self, mw_factory, form_pdf):
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf)
        assert mw.text_toolbar.isEnabled() is False
        mw.btn_stamp.setChecked(True)
        assert mw.text_toolbar.isEnabled() is True

    def test_field_cache_populated_on_load(self, mw_factory, form_pdf):
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf)
        names = {row[1] for row in mw._form_field_cache}
        assert names == {"given_name", "email"}


def _fake_dialog(returned_value: str, accept: bool = True):
    """Patch helper: returns a context manager that replaces FillFieldDialog with a stub
    that captures the constructor's initial_value and returns a fixed result on exec()."""
    captured = {}
    class _Stub:
        def __init__(self, parent, field_name, initial_value):
            captured["field_name"] = field_name
            captured["initial_value"] = initial_value
        def exec(self_inner):
            from PyQt6.QtWidgets import QDialog
            return (
                QDialog.DialogCode.Accepted if accept
                else QDialog.DialogCode.Rejected
            )
        def value(self_inner):
            return returned_value
    cm = patch("gui.FillFieldDialog", _Stub)
    return cm, captured


def _click_at_pdf(canvas, mw, pdf_x: float, pdf_y: float):
    pos = QPointF(pdf_x * mw.zoom, pdf_y * mw.zoom + canvas._page_y_offset)
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        pos, pos, Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(event)


class TestFillClick:
    def test_fill_click_opens_dialog_and_saves_value(self, mw_factory, form_pdf):
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf)
        cm, _ = _fake_dialog("Alice", accept=True)
        with cm:
            _click_at_pdf(mw.canvas, mw, 200, 110)
        fills = mw.doc.pending_fields()
        assert len(fills) == 1
        assert fills[0].field_name == "given_name"
        assert fills[0].value == "Alice"

    def test_fill_empty_string_creates_blank_pending(self, mw_factory, form_pdf):
        """User submits empty → pending fill of empty string (forces blank on save)."""
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf)
        mw.doc.fill_field("given_name", "Alice")
        cm, _ = _fake_dialog("", accept=True)
        with cm:
            _click_at_pdf(mw.canvas, mw, 200, 110)
        fills = mw.doc.pending_fields()
        assert len(fills) == 1
        assert fills[0].value == ""

    def test_fill_click_outside_any_field_is_noop(self, mw_factory, form_pdf):
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf)
        cm, _ = _fake_dialog("X", accept=True)
        from gui import FillFieldDialog
        with patch("gui.FillFieldDialog") as mock_cls:
            _click_at_pdf(mw.canvas, mw, 50, 10)  # above all field rects
            assert not mock_cls.called
        assert mw.doc.pending_fields() == []

    def test_cancel_dialog_does_nothing(self, mw_factory, form_pdf):
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf)
        cm, _ = _fake_dialog("anything", accept=False)
        with cm:
            _click_at_pdf(mw.canvas, mw, 200, 110)
        assert mw.doc.pending_fields() == []


class TestDialogPrePopulation:
    def test_dialog_pre_populates_with_original_value(self, mw_factory, form_pdf_with_default):
        """Clicking a field with a baked-in default opens the dialog with that default."""
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf_with_default)
        cm, captured = _fake_dialog("ignored", accept=False)
        with cm:
            _click_at_pdf(mw.canvas, mw, 200, 110)
        assert captured["field_name"] == "given_name"
        assert captured["initial_value"] == "DEFAULT_NAME"

    def test_dialog_pre_populates_with_pending_value_when_present(self, mw_factory, form_pdf_with_default):
        """A pending fill takes precedence over the original value in pre-population."""
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf_with_default)
        mw.doc.fill_field("given_name", "Bob")
        cm, captured = _fake_dialog("ignored", accept=False)
        with cm:
            _click_at_pdf(mw.canvas, mw, 200, 110)
        assert captured["initial_value"] == "Bob"

    def test_unchanged_pre_populated_value_is_not_recorded_as_pending(self, mw_factory, form_pdf_with_default):
        """Opening dialog and pressing OK without edits should not create a phantom pending."""
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf_with_default)
        cm, _ = _fake_dialog("DEFAULT_NAME", accept=True)  # same as original
        with cm:
            _click_at_pdf(mw.canvas, mw, 200, 110)
        assert mw.doc.pending_fields() == []
        assert mw.doc.is_dirty is False


class TestClearBakedInDefault:
    def test_clear_through_empty_submit_blanks_default_on_save(self, mw_factory, form_pdf_with_default, tmp_output):
        """User-flow regression: dialog pre-fills with 'DEFAULT_NAME', user clears it,
        OK, save — re-opened PDF widget is empty (not 'DEFAULT_NAME')."""
        import fitz
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf_with_default)
        cm, _ = _fake_dialog("", accept=True)
        with cm:
            _click_at_pdf(mw.canvas, mw, 200, 110)
        mw.doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            for p in reopened:
                for w in (p.widgets() or []):
                    if w.field_name == "given_name":
                        assert w.field_value == ""
        finally:
            reopened.close()


class TestSaveAfterFill:
    def test_save_after_fill_persists_value(self, mw_factory, form_pdf, tmp_output):
        import fitz
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=form_pdf)
        mw.doc.fill_field("given_name", "Alice")
        mw.doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            vals = {w.field_name: w.field_value for p in reopened for w in (p.widgets() or [])}
        finally:
            reopened.close()
        assert vals["given_name"] == "Alice"


class TestCheckboxClick:
    def test_click_unchecked_checkbox_sets_yes(self, mw_factory, complex_form_pdf):
        import fitz
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=complex_form_pdf)
        cb = next(f for f in mw._form_field_cache if f.widget_type == fitz.PDF_WIDGET_TYPE_CHECKBOX)
        # Hit center of checkbox rect
        x0, y0, x1, y1 = cb.rect
        # Make sure we're on the checkbox's page
        mw.current_page = cb.page_num
        mw.refresh_page()
        _click_at_pdf(mw.canvas, mw, (x0 + x1) / 2, (y0 + y1) / 2)
        fills = mw.doc.pending_fields()
        assert any(f.field_name == cb.field_name and f.value == cb.on_state for f in fills)

    def test_click_checked_checkbox_sets_off(self, mw_factory, complex_form_pdf):
        import fitz
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=complex_form_pdf)
        cb = next(f for f in mw._form_field_cache if f.widget_type == fitz.PDF_WIDGET_TYPE_CHECKBOX)
        mw.current_page = cb.page_num
        mw.refresh_page()
        x0, y0, x1, y1 = cb.rect
        # First click → set to on_state
        _click_at_pdf(mw.canvas, mw, (x0 + x1) / 2, (y0 + y1) / 2)
        # Second click → toggle to "Off"
        _click_at_pdf(mw.canvas, mw, (x0 + x1) / 2, (y0 + y1) / 2)
        fills = mw.doc.pending_fields()
        match = next(f for f in fills if f.field_name == cb.field_name)
        assert match.value == "Off"

    def test_click_checkbox_does_not_open_text_dialog(self, mw_factory, complex_form_pdf):
        import fitz
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=complex_form_pdf)
        cb = next(f for f in mw._form_field_cache if f.widget_type == fitz.PDF_WIDGET_TYPE_CHECKBOX)
        mw.current_page = cb.page_num
        mw.refresh_page()
        x0, y0, x1, y1 = cb.rect
        with patch("gui.FillFieldDialog") as mock_dlg:
            _click_at_pdf(mw.canvas, mw, (x0 + x1) / 2, (y0 + y1) / 2)
        assert not mock_dlg.called


class TestRadioClick:
    def test_click_radio_records_selection(self, mw_factory, radio_pdf):
        import fitz
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=radio_pdf)
        radios = [f for f in mw._form_field_cache if f.widget_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON]
        green = next(r for r in radios if r.on_state == "Green")
        x0, y0, x1, y1 = green.rect
        _click_at_pdf(mw.canvas, mw, (x0 + x1) / 2, (y0 + y1) / 2)
        fills = mw.doc.pending_fields()
        assert len(fills) == 1
        assert fills[0].field_name == "color"
        assert fills[0].value == "Green"

    def test_click_different_radio_overwrites(self, mw_factory, radio_pdf):
        import fitz
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=radio_pdf)
        radios = [f for f in mw._form_field_cache if f.widget_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON]
        green = next(r for r in radios if r.on_state == "Green")
        blue = next(r for r in radios if r.on_state == "Blue")
        for r in (green, blue):
            x0, y0, x1, y1 = r.rect
            _click_at_pdf(mw.canvas, mw, (x0 + x1) / 2, (y0 + y1) / 2)
        fills = mw.doc.pending_fields()
        # Single entry per field_name; latest selection wins
        assert len(fills) == 1
        assert fills[0].value == "Blue"

    def test_click_radio_does_not_open_text_dialog(self, mw_factory, radio_pdf):
        import fitz
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=radio_pdf)
        radios = [f for f in mw._form_field_cache if f.widget_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON]
        green = next(r for r in radios if r.on_state == "Green")
        x0, y0, x1, y1 = green.rect
        with patch("gui.FillFieldDialog") as mock_dlg:
            _click_at_pdf(mw.canvas, mw, (x0 + x1) / 2, (y0 + y1) / 2)
        assert not mock_dlg.called


class TestDropdownClick:
    def _click_combobox(self, mw_factory, dropdown_pdf):
        with patch.object(QMessageBox, "information"):
            mw = mw_factory(initial_path=dropdown_pdf)
        combo = next(f for f in mw._form_field_cache
                     if f.widget_type == 3)  # PDF_WIDGET_TYPE_COMBOBOX = 3
        x0, y0, x1, y1 = combo.rect
        return mw, combo, (x0 + x1) / 2, (y0 + y1) / 2

    def test_click_combobox_opens_menu_with_choices(self, mw_factory, dropdown_pdf):
        mw, combo, cx, cy = self._click_combobox(mw_factory, dropdown_pdf)
        captured = {}

        def fake_exec(self_inner, _global_pos):
            captured["actions"] = [a.text() for a in self_inner.actions()]
            return None  # user dismisses without picking

        with patch("gui.QMenu.exec", fake_exec):
            _click_at_pdf(mw.canvas, mw, cx, cy)
        assert captured["actions"] == ["Apple", "Banana", "Cherry"]
        assert mw.doc.pending_fields() == []

    def test_combobox_selection_fills_field(self, mw_factory, dropdown_pdf):
        mw, combo, cx, cy = self._click_combobox(mw_factory, dropdown_pdf)

        def fake_exec(self_inner, _global_pos):
            return next(a for a in self_inner.actions() if a.text() == "Banana")

        with patch("gui.QMenu.exec", fake_exec):
            _click_at_pdf(mw.canvas, mw, cx, cy)
        fills = mw.doc.pending_fields()
        assert len(fills) == 1
        assert fills[0].field_name == "fruit"
        assert fills[0].value == "Banana"

    def test_combobox_does_not_open_text_dialog(self, mw_factory, dropdown_pdf):
        mw, combo, cx, cy = self._click_combobox(mw_factory, dropdown_pdf)
        with patch("gui.FillFieldDialog") as mock_dlg, \
             patch("gui.QMenu.exec", lambda self_inner, _p: None):
            _click_at_pdf(mw.canvas, mw, cx, cy)
        assert not mock_dlg.called


class TestNotices:
    def test_xfa_only_notice_once_and_flips_back(self, mw_factory, simple_pdf):
        mw = mw_factory(initial_path=simple_pdf)
        # Patch the doc's detection to simulate XFA-only
        with patch.object(mw.doc, "has_widgets", return_value=False), \
             patch.object(mw.doc, "is_xfa", return_value=True), \
             patch.object(QMessageBox, "information") as mock_info:
            mw.btn_fill.setChecked(True)
            assert mock_info.call_count == 1
            # Toggle again — should not re-notice
            mw.btn_stamp.setChecked(True)
            mw.btn_fill.setChecked(True)
            assert mock_info.call_count == 1
        # Ended up back at stamp because no widgets
        assert mw.top_mode == "stamp"

    def test_no_widgets_switches_back_to_stamp(self, mw_factory, simple_pdf):
        mw = mw_factory(initial_path=simple_pdf)
        with patch.object(QMessageBox, "information") as mock_info:
            mw.btn_fill.setChecked(True)
            assert mock_info.called
        assert mw.top_mode == "stamp"
