import os
from unittest.mock import patch

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def main_window(qapp):
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QMessageBox
    # Clear QSettings to avoid state leaking between tests
    QSettings("PDF Simple Signing", "PDF Simple Signing").clear()
    with patch("gui.QFileDialog.getOpenFileName", return_value=("", "")), \
         patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        from gui import MainWindow
        mw = MainWindow()
        # Keep window hidden during tests
        mw.hide()
        yield mw
        # Force-close without triggering dirty check dialog
        if mw.doc:
            mw.doc.mark_saved()
        mw.close()


@pytest.fixture
def simple_pdf():
    return os.path.join(FIXTURES_DIR, "simple.pdf")


@pytest.fixture
def medium_pdf():
    return os.path.join(FIXTURES_DIR, "medium.pdf")


@pytest.fixture
def signature_png():
    return os.path.join(FIXTURES_DIR, "signature.png")


@pytest.fixture
def default_font():
    return "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"


@pytest.fixture
def tmp_output(tmp_path):
    return str(tmp_path / "output.pdf")
