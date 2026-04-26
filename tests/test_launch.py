import os
import sys
from unittest.mock import patch

import pytest

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QMessageBox


@pytest.fixture
def _isolated(qapp):
    """Clear QSettings + mock file dialog so MainWindow starts cleanly without popping dialogs."""
    QSettings("PDF Sign & Fill", "PDF Sign & Fill").clear()
    with patch("gui.QFileDialog.getOpenFileName", return_value=("", "")), \
         patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        yield


class TestLoadFile:
    def test_load_file_opens_document(self, _isolated, simple_pdf):
        from gui import MainWindow
        mw = MainWindow()
        try:
            mw.load_file(simple_pdf)
            assert mw.doc is not None
            assert mw.doc.page_count() == 1
            assert mw.current_page == 0
            assert os.path.basename(simple_pdf) in mw.windowTitle()
        finally:
            if mw.doc:
                mw.doc.mark_saved()
            mw.close()

    def test_load_file_nonexistent_warns_does_not_crash(self, _isolated):
        from gui import MainWindow
        mw = MainWindow()
        try:
            with patch.object(QMessageBox, "warning") as mock_warn:
                mw.load_file("/does/not/exist.pdf")
            assert mock_warn.called
            assert mw.doc is None
        finally:
            mw.close()

    def test_load_file_non_pdf_warns(self, _isolated, tmp_path):
        from gui import MainWindow
        junk = tmp_path / "junk.pdf"
        junk.write_bytes(b"this is not a pdf")
        mw = MainWindow()
        try:
            with patch.object(QMessageBox, "warning") as mock_warn:
                mw.load_file(str(junk))
            assert mock_warn.called
            assert mw.doc is None
        finally:
            mw.close()


class TestSettingsMigration:
    def test_legacy_qsettings_migrated_on_first_run(self, qapp):
        """Old 'PDF Simple Signing' settings should copy into 'PDF Sign & Fill' on first MainWindow init."""
        legacy = QSettings("PDF Simple Signing", "PDF Simple Signing")
        new = QSettings("PDF Sign & Fill", "PDF Sign & Fill")
        new.clear()
        legacy.clear()
        legacy.setValue("font_name", "DejaVu Serif")
        legacy.setValue("user_name", "Old User")
        legacy.sync()
        with patch("gui.QFileDialog.getOpenFileName", return_value=("", "")), \
             patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            from gui import MainWindow
            mw = MainWindow()
            try:
                assert new.value("font_name") == "DejaVu Serif"
                assert new.value("user_name") == "Old User"
                # legacy keys cleared after migration
                assert not QSettings("PDF Simple Signing", "PDF Simple Signing").allKeys()
            finally:
                mw.close()

    def test_migration_is_noop_when_new_already_populated(self, qapp):
        """If new settings exist, don't clobber them with legacy values."""
        legacy = QSettings("PDF Simple Signing", "PDF Simple Signing")
        new = QSettings("PDF Sign & Fill", "PDF Sign & Fill")
        new.clear()
        legacy.clear()
        legacy.setValue("font_name", "OldFont")
        new.setValue("font_name", "NewFont")
        new.sync()
        legacy.sync()
        with patch("gui.QFileDialog.getOpenFileName", return_value=("", "")), \
             patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            from gui import MainWindow
            mw = MainWindow()
            try:
                # New value preserved; legacy not migrated and not cleared
                assert new.value("font_name") == "NewFont"
                assert legacy.value("font_name") == "OldFont"
            finally:
                mw.close()
                legacy.clear()


class TestSaveDialog:
    def test_save_as_defaults_to_current_pdf_path(self, _isolated, simple_pdf, tmp_output):
        from gui import MainWindow
        mw = MainWindow(initial_path=simple_pdf)
        try:
            with patch("gui.QFileDialog.getSaveFileName",
                       return_value=(tmp_output, "PDF Files (*.pdf)")) as mock_save:
                mw.save_file()
            assert mock_save.called
            args, _kwargs = mock_save.call_args
            # getSaveFileName(parent, caption, directory, filter) — the third arg
            # carries the suggested directory (and optional filename) for the dialog.
            assert args[2] == simple_pdf
        finally:
            if mw.doc:
                mw.doc.mark_saved()
            mw.close()


class TestMainArgvParsing:
    def test_main_with_pdf_argv_loads_it(self, qapp, simple_pdf):
        import gui
        with patch.object(sys, "argv", ["gui.py", simple_pdf]), \
             patch.object(gui, "QApplication") as mock_app_cls, \
             patch.object(gui, "MainWindow") as mock_window_cls, \
             patch.object(gui.sys, "exit"):
            mock_app_cls.return_value.exec.return_value = 0
            gui.main()
            mock_window_cls.assert_called_once_with(initial_path=simple_pdf)

    def test_main_with_no_argv_shows_empty_state(self, qapp):
        import gui
        with patch.object(sys, "argv", ["gui.py"]), \
             patch.object(gui, "QApplication") as mock_app_cls, \
             patch.object(gui, "MainWindow") as mock_window_cls, \
             patch.object(gui.sys, "exit"):
            mock_app_cls.return_value.exec.return_value = 0
            gui.main()
            mock_window_cls.assert_called_once_with(initial_path=None)

    def test_init_without_argv_does_not_open_dialog(self, qapp):
        """After refactor, __init__ should not auto-pop the Open dialog."""
        QSettings("PDF Sign & Fill", "PDF Sign & Fill").clear()
        with patch("gui.QFileDialog.getOpenFileName", return_value=("", "")) as mock_dlg, \
             patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            from gui import MainWindow
            mw = MainWindow()
            try:
                assert not mock_dlg.called, "No file dialog should pop on startup with no initial_path"
                assert mw.doc is None
            finally:
                mw.close()
