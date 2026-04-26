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
    QSettings("PDF Sign & Fill", "PDF Sign & Fill").clear()
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


@pytest.fixture
def form_pdf(tmp_path):
    """Minimal 2-field AcroForm PDF for API-shape unit tests."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(fitz.Point(72, 90), "Name:", fontsize=11)
    page.insert_text(fitz.Point(72, 150), "Email:", fontsize=11)
    for name, y in [("given_name", 100), ("email", 160)]:
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_value = ""
        w.rect = fitz.Rect(130, y, 400, y + 24)
        w.text_maxlen = 100
        page.add_widget(w)
    out = tmp_path / "form.pdf"
    doc.save(str(out))
    doc.close()
    return str(out)


@pytest.fixture
def multipage_form_pdf(tmp_path):
    """Two pages with the same field_name on each — exercises cross-page propagation."""
    import fitz
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page(width=612, height=792)
        w = fitz.Widget()
        w.field_name = "last_name"
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_value = ""
        w.rect = fitz.Rect(130, 100, 400, 124)
        w.text_maxlen = 100
        page.add_widget(w)
    out = tmp_path / "multipage.pdf"
    doc.save(str(out))
    doc.close()
    return str(out)


@pytest.fixture
def complex_form_pdf(tmp_path):
    """Copy of the D&D character sheet to tmp_path — never mutate the source."""
    import shutil
    src = os.path.join(FIXTURES_DIR, "complex-form.pdf")
    dst = str(tmp_path / "complex-form.pdf")
    shutil.copy(src, dst)
    return dst


@pytest.fixture
def complex_form_with_defaults_pdf(tmp_path):
    """D&D sheet pre-filled with default values (e.g. CharacterName='Sub1217's Character').
    Used to test the original-value pre-population and clearing of baked-in defaults."""
    import shutil
    src = os.path.join(FIXTURES_DIR, "complex-form-with-duplicate-edits.pdf")
    dst = str(tmp_path / "complex-form-with-duplicate-edits.pdf")
    shutil.copy(src, dst)
    return dst


@pytest.fixture
def radio_pdf(tmp_path):
    """1-page form with a 3-button radio group named 'color' (Red/Green/Blue).

    PyMuPDF's add_widget collapses all radios in a group to on_state='Yes', so
    we post-process each widget's AP/N dictionary to rename the on-state to a
    distinct export value.
    """
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for y in (100, 140, 180):
        w = fitz.Widget()
        w.field_name = "color"
        w.field_type = fitz.PDF_WIDGET_TYPE_RADIOBUTTON
        w.field_value = "Off"
        w.rect = fitz.Rect(100, y, 120, y + 20)
        page.add_widget(w)
    labels = ["Red", "Green", "Blue"]
    radios = [w for p in doc for w in (p.widgets() or [])
              if w.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON]
    for w, label in zip(radios, labels):
        apn_type, apn_val = doc.xref_get_key(w.xref, "AP/N")
        if apn_type == "dict":
            doc.xref_set_key(w.xref, "AP/N", apn_val.replace("/Yes", f"/{label}"))
        doc.xref_set_key(w.xref, "AS", "/Off")
    out = tmp_path / "radio.pdf"
    doc.save(str(out))
    doc.close()
    return str(out)


@pytest.fixture
def dropdown_pdf(tmp_path):
    """1-page form with a combobox 'fruit' offering Apple/Banana/Cherry."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    w = fitz.Widget()
    w.field_name = "fruit"
    w.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
    w.choice_values = ["Apple", "Banana", "Cherry"]
    w.field_value = ""
    w.rect = fitz.Rect(100, 100, 300, 124)
    page.add_widget(w)
    out = tmp_path / "dropdown.pdf"
    doc.save(str(out))
    doc.close()
    return str(out)


@pytest.fixture
def form_pdf_with_default(tmp_path):
    """Form PDF where given_name has a baked-in default value 'DEFAULT_NAME'."""
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for name, y, default in [("given_name", 100, "DEFAULT_NAME"), ("email", 160, "")]:
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_value = default
        w.rect = fitz.Rect(130, y, 400, y + 24)
        w.text_maxlen = 100
        page.add_widget(w)
    out = tmp_path / "form_default.pdf"
    doc.save(str(out))
    doc.close()
    return str(out)
