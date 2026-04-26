"""Core API tests for AcroForm text-field filling."""
import fitz
import pytest

from pdfsign.core import PdfDocument


class TestDetection:
    def test_form_pdf_has_widgets(self, form_pdf):
        doc = PdfDocument(form_pdf)
        assert doc.has_widgets() is True
        fields = doc.form_fields()
        names = sorted(row[1] for row in fields)
        assert names == ["email", "given_name"]

    def test_simple_pdf_has_no_widgets(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        assert doc.has_widgets() is False
        assert doc.form_fields() == []

    def test_xfa_detection_false_on_acroform_only(self, form_pdf):
        doc = PdfDocument(form_pdf)
        assert doc.is_xfa() is False

    def test_xfa_detection_false_on_non_form_pdf(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        assert doc.is_xfa() is False


class TestFillField:
    def test_fill_field_adds_pending(self, form_pdf):
        doc = PdfDocument(form_pdf)
        doc.fill_field("given_name", "Alice")
        fills = doc.pending_fields()
        assert len(fills) == 1
        assert fills[0].field_name == "given_name"
        assert fills[0].value == "Alice"

    def test_fill_field_dedupes_by_name_and_tracks_update(self, form_pdf):
        doc = PdfDocument(form_pdf)
        doc.fill_field("given_name", "Alice")
        doc.fill_field("given_name", "Bob")
        fills = doc.pending_fields()
        assert len(fills) == 1
        assert fills[0].value == "Bob"
        # undo once -> "Alice"
        doc.undo()
        assert doc.pending_fields()[0].value == "Alice"
        # undo again -> empty
        doc.undo()
        assert doc.pending_fields() == []

    def test_fill_field_empty_creates_blank_pending(self, form_pdf):
        """Empty value is a valid fill: it forces the widget blank on save,
        overriding any baked-in default. Prior 'empty=remove' semantics is gone."""
        doc = PdfDocument(form_pdf)
        doc.fill_field("given_name", "Alice")
        doc.fill_field("given_name", "")
        fills = doc.pending_fields()
        assert len(fills) == 1
        assert fills[0].value == ""
        # Undo restores "Alice"
        doc.undo()
        assert doc.pending_fields()[0].value == "Alice"

    def test_fill_field_empty_when_none_pending_creates_pending(self, form_pdf):
        doc = PdfDocument(form_pdf)
        doc.fill_field("given_name", "")
        fills = doc.pending_fields()
        assert len(fills) == 1
        assert fills[0].value == ""
        # Undo removes
        assert doc.undo() is True
        assert doc.pending_fields() == []

    def test_fill_field_same_value_is_noop(self, form_pdf):
        """Filling with the same pending value twice should not push a duplicate undo entry."""
        doc = PdfDocument(form_pdf)
        doc.fill_field("given_name", "Alice")
        doc.fill_field("given_name", "Alice")
        assert doc.undo() is True  # only one undo entry exists
        assert doc.undo() is False


class TestSave:
    def test_save_writes_field_value(self, form_pdf, tmp_output):
        doc = PdfDocument(form_pdf)
        doc.fill_field("given_name", "Alice")
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            values = {w.field_name: w.field_value for p in reopened for w in (p.widgets() or [])}
        finally:
            reopened.close()
        assert values["given_name"] == "Alice"

    def test_save_preserves_interactivity(self, form_pdf, tmp_output):
        doc = PdfDocument(form_pdf)
        doc.fill_field("given_name", "Alice")
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            types = set()
            for p in reopened:
                for w in (p.widgets() or []):
                    types.add(w.field_type)
            assert fitz.PDF_WIDGET_TYPE_TEXT in types
        finally:
            reopened.close()

    def test_fill_unknown_field_is_noop_on_save(self, form_pdf, tmp_output):
        doc = PdfDocument(form_pdf)
        doc.fill_field("nonexistent_field", "x")
        doc.save(tmp_output)  # should not raise

    def test_save_clears_baked_in_default(self, form_pdf_with_default, tmp_output):
        """Filling with empty must clear an existing default value baked into the widget,
        not leave it visually 'typed over'. This is the xref-based clear path."""
        doc = PdfDocument(form_pdf_with_default)
        # Sanity: the original has DEFAULT_NAME
        original = next(f.value for f in doc.form_fields() if f.field_name == "given_name")
        assert original == "DEFAULT_NAME"
        doc.fill_field("given_name", "")
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            for p in reopened:
                for w in (p.widgets() or []):
                    if w.field_name == "given_name":
                        assert w.field_value == ""
        finally:
            reopened.close()

    def test_save_overrides_baked_in_default_with_new_text(self, form_pdf_with_default, tmp_output):
        """Filling with non-empty must replace (not overlay) any baked-in default value."""
        doc = PdfDocument(form_pdf_with_default)
        doc.fill_field("given_name", "REPLACED")
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            for p in reopened:
                for w in (p.widgets() or []):
                    if w.field_name == "given_name":
                        assert w.field_value == "REPLACED"
                        # The text rendered in the field region must be only the new value
                        words = p.get_text("words", clip=w.rect)
                        rendered = " ".join(x[4] for x in words)
                        assert "DEFAULT_NAME" not in rendered
                        assert "REPLACED" in rendered
        finally:
            reopened.close()

    def test_save_propagates_to_all_widget_occurrences(self, multipage_form_pdf, tmp_output):
        doc = PdfDocument(multipage_form_pdf)
        doc.fill_field("last_name", "Smith")
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            values_per_page = []
            for page in reopened:
                for w in (page.widgets() or []):
                    if w.field_name == "last_name":
                        values_per_page.append(w.field_value)
        finally:
            reopened.close()
        assert len(values_per_page) == 2
        assert all(v == "Smith" for v in values_per_page)


class TestCheckboxFill:
    def test_complex_form_includes_checkboxes(self, complex_form_pdf):
        doc = PdfDocument(complex_form_pdf)
        cbs = [f for f in doc.form_fields() if f.widget_type == fitz.PDF_WIDGET_TYPE_CHECKBOX]
        assert len(cbs) == 151
        # All checkboxes have a non-empty on_state value
        assert all(cb.on_state for cb in cbs)

    def test_fill_checkbox_yes_persists(self, complex_form_pdf, tmp_output):
        doc = PdfDocument(complex_form_pdf)
        cb = next(f for f in doc.form_fields() if f.widget_type == fitz.PDF_WIDGET_TYPE_CHECKBOX)
        doc.fill_field(cb.field_name, cb.on_state)
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            w = next(w for p in reopened for w in (p.widgets() or []) if w.field_name == cb.field_name)
            assert w.field_value == cb.on_state
        finally:
            reopened.close()

    def test_fill_checkbox_off_persists(self, complex_form_pdf, tmp_output):
        # First set Yes, then turn it Off — verify Off persists across save
        doc = PdfDocument(complex_form_pdf)
        cb = next(f for f in doc.form_fields() if f.widget_type == fitz.PDF_WIDGET_TYPE_CHECKBOX)
        doc.fill_field(cb.field_name, cb.on_state)
        doc.fill_field(cb.field_name, "Off")
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            w = next(w for p in reopened for w in (p.widgets() or []) if w.field_name == cb.field_name)
            assert w.field_value in ("Off", "")
        finally:
            reopened.close()


class TestRadioFill:
    def test_radio_group_enumerates_each_button(self, radio_pdf):
        doc = PdfDocument(radio_pdf)
        radios = [f for f in doc.form_fields() if f.widget_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON]
        assert len(radios) == 3
        # All share the same field_name (radio group), distinct on_states
        assert {r.field_name for r in radios} == {"color"}
        assert {r.on_state for r in radios} == {"Red", "Green", "Blue"}

    def test_radio_select_one_persists(self, radio_pdf, tmp_output):
        doc = PdfDocument(radio_pdf)
        radios = [f for f in doc.form_fields() if f.widget_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON]
        green = next(r for r in radios if r.on_state == "Green")
        doc.fill_field(green.field_name, green.on_state)
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            # Snapshot per-widget state inside the page iteration so weakrefs stay valid.
            states = []
            for p in reopened:
                for w in (p.widgets() or []):
                    if w.field_name == "color":
                        states.append((w.field_value, w.on_state()))
        finally:
            reopened.close()
        on = [(v, on_state) for v, on_state in states if v not in ("", "Off")]
        assert len(on) == 1, f"Expected exactly one selected radio, got states={states}"
        assert on[0] == ("Green", "Green")

    def test_radio_change_selection(self, radio_pdf, tmp_output):
        doc = PdfDocument(radio_pdf)
        doc.fill_field("color", "Red")
        doc.fill_field("color", "Blue")  # switch
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            states = []
            for p in reopened:
                for w in (p.widgets() or []):
                    if w.field_name == "color":
                        states.append((w.field_value, w.on_state()))
        finally:
            reopened.close()
        on = [(v, on_state) for v, on_state in states if v not in ("", "Off")]
        assert len(on) == 1
        assert on[0] == ("Blue", "Blue")


class TestDropdownFill:
    def test_dropdown_enumerates_with_choices(self, dropdown_pdf):
        doc = PdfDocument(dropdown_pdf)
        fields = doc.form_fields()
        combo = next(f for f in fields if f.widget_type == fitz.PDF_WIDGET_TYPE_COMBOBOX)
        assert combo.field_name == "fruit"
        assert combo.choices == ("Apple", "Banana", "Cherry")

    def test_dropdown_fill_persists(self, dropdown_pdf, tmp_output):
        doc = PdfDocument(dropdown_pdf)
        doc.fill_field("fruit", "Banana")
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            for p in reopened:
                for w in (p.widgets() or []):
                    if w.field_name == "fruit":
                        assert w.field_value == "Banana"
        finally:
            reopened.close()


class TestIntegrationWithStamps:
    def test_clear_does_not_touch_fields(self, form_pdf, default_font):
        doc = PdfDocument(form_pdf)
        doc.add_text(0, 100, 100, "stamp", default_font)
        doc.fill_field("given_name", "Alice")
        doc.clear()
        assert doc.pending_annotations() == []
        assert len(doc.pending_fields()) == 1

    def test_is_dirty_tracks_field_fills(self, form_pdf, tmp_output):
        doc = PdfDocument(form_pdf)
        assert doc.is_dirty is False
        doc.fill_field("given_name", "Alice")
        assert doc.is_dirty is True
        doc.save(tmp_output)
        doc.mark_saved()
        assert doc.is_dirty is False


class TestComplexForm:
    """Real-world tests against the D&D character sheet (2 pages, 260 text + 151 checkboxes)."""

    def test_has_widgets(self, complex_form_pdf):
        doc = PdfDocument(complex_form_pdf)
        assert doc.has_widgets() is True

    def test_is_not_xfa(self, complex_form_pdf):
        doc = PdfDocument(complex_form_pdf)
        assert doc.is_xfa() is False

    def test_enumerates_text_and_checkbox_fields(self, complex_form_pdf):
        doc = PdfDocument(complex_form_pdf)
        fields = doc.form_fields()
        # 411 total widgets = 260 text + 151 checkboxes (radios none in this fixture)
        assert len(fields) == 411
        text_count = sum(1 for f in fields if f.widget_type == fitz.PDF_WIDGET_TYPE_TEXT)
        cb_count = sum(1 for f in fields if f.widget_type == fitz.PDF_WIDGET_TYPE_CHECKBOX)
        assert text_count == 260
        assert cb_count == 151
        for f in fields:
            assert isinstance(f.page_num, int)
            assert isinstance(f.field_name, str) and f.field_name
            assert len(f.rect) == 4
            assert isinstance(f.value, str)
            assert f.widget_type in (fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_CHECKBOX)

    def test_roundtrip_fill(self, complex_form_pdf, tmp_output):
        doc = PdfDocument(complex_form_pdf)
        fields = [f for f in doc.form_fields() if f.widget_type == fitz.PDF_WIDGET_TYPE_TEXT]
        target_name = fields[0].field_name
        doc.fill_field(target_name, "ROUNDTRIP-TEST")
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            found = None
            still_text = False
            for page in reopened:
                for w in (page.widgets() or []):
                    if w.field_name == target_name:
                        found = w.field_value
                        still_text = (w.field_type == fitz.PDF_WIDGET_TYPE_TEXT)
                        break
                if found is not None:
                    break
        finally:
            reopened.close()
        assert found == "ROUNDTRIP-TEST"
        assert still_text

    def test_complex_form_with_defaults_replaces_cleanly(self, complex_form_with_defaults_pdf, tmp_output):
        """The duplicate-edits fixture has 167 pre-filled defaults. Replacing one
        must produce only the new text in the rendered field region — no overlay."""
        doc = PdfDocument(complex_form_with_defaults_pdf)
        # Sanity: CharacterName has a default
        fields = doc.form_fields()
        char_name = next(f.value for f in fields if f.field_name == "CharacterName")
        assert "Sub1217" in char_name  # known content from the fixture
        doc.fill_field("CharacterName", "REPLACED_HERO")
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            for p in reopened:
                for w in (p.widgets() or []):
                    if w.field_name == "CharacterName":
                        assert w.field_value == "REPLACED_HERO"
                        words = p.get_text("words", clip=w.rect)
                        rendered = " ".join(x[4] for x in words)
                        assert "Sub1217" not in rendered
                        assert "REPLACED_HERO" in rendered
        finally:
            reopened.close()

    def test_complex_form_with_defaults_clear_blanks_field(self, complex_form_with_defaults_pdf, tmp_output):
        """Clearing (empty fill) on a field with a baked-in default must leave it blank."""
        doc = PdfDocument(complex_form_with_defaults_pdf)
        doc.fill_field("CharacterName", "")
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            for p in reopened:
                for w in (p.widgets() or []):
                    if w.field_name == "CharacterName":
                        assert w.field_value == ""
                        words = p.get_text("words", clip=w.rect)
                        rendered = " ".join(x[4] for x in words)
                        assert "Sub1217" not in rendered
        finally:
            reopened.close()

    def test_many_fills(self, complex_form_pdf, tmp_output):
        doc = PdfDocument(complex_form_pdf)
        fields = [f for f in doc.form_fields() if f.widget_type == fitz.PDF_WIDGET_TYPE_TEXT]
        targets = {fields[i].field_name: f"val-{i}" for i in range(10)}
        for name, val in targets.items():
            doc.fill_field(name, val)
        doc.save(tmp_output)
        reopened = fitz.open(tmp_output)
        try:
            values = {}
            for page in reopened:
                for w in (page.widgets() or []):
                    if w.field_name in targets:
                        values[w.field_name] = w.field_value
        finally:
            reopened.close()
        for name, expected in targets.items():
            assert values.get(name) == expected, f"Field {name!r} expected {expected!r}, got {values.get(name)!r}"
