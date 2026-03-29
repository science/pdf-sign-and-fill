"""GUI unit tests — TDD Red/Green cycles."""

from datetime import date

from gui import expand_variables, MAX_RECENT_IMAGES


class TestExpandVariables:
    def test_uses_date_format(self):
        result = expand_variables("{date}", {"date_format": "%Y-%m-%d"})
        assert result == date.today().strftime("%Y-%m-%d")

    def test_custom_date_format(self):
        result = expand_variables("{date}", {"date_format": "%d/%m/%Y"})
        assert result == date.today().strftime("%d/%m/%Y")

    def test_name_substitution(self):
        result = expand_variables("{name}", {"name": "Alice", "date_format": "%Y-%m-%d"})
        assert result == "Alice"

    def test_combined_template(self):
        result = expand_variables("{name} - {date}", {"name": "Bob", "date_format": "%b %d"})
        expected = f"Bob - {date.today().strftime('%b %d')}"
        assert result == expected

    def test_missing_date_format_defaults(self):
        result = expand_variables("{date}", {"name": "X"})
        # Falls back to %Y-%m-%d when date_format not in dict
        assert result == date.today().strftime("%Y-%m-%d")


class TestPerImageSizeMemory:
    def test_remember_image_size(self, main_window):
        mw = main_window
        mw.remember_image_size("/tmp/test.png", 200, 65)
        assert mw.image_sizes["/tmp/test.png"] == [200, 65]

    def test_remember_overwrites_previous(self, main_window):
        mw = main_window
        mw.remember_image_size("/tmp/test.png", 100, 50)
        mw.remember_image_size("/tmp/test.png", 200, 65)
        assert mw.image_sizes["/tmp/test.png"] == [200, 65]

    def test_get_image_size_returns_remembered(self, main_window):
        mw = main_window
        mw.image_sizes["/tmp/test.png"] = [200, 65]
        assert mw.get_image_size("/tmp/test.png") == (200, 65)

    def test_get_image_size_returns_spinbox_default(self, main_window):
        mw = main_window
        mw.img_width.setValue(150)
        mw.img_height.setValue(50)
        assert mw.get_image_size("/tmp/unknown.png") == (150, 50)

    def test_remember_updates_spinboxes_for_current_image(self, main_window):
        mw = main_window
        mw.image_path = "/tmp/test.png"
        mw.remember_image_size("/tmp/test.png", 300, 100)
        assert mw.img_width.value() == 300
        assert mw.img_height.value() == 100

    def test_remember_does_not_update_spinboxes_for_other_image(self, main_window):
        mw = main_window
        mw.image_path = "/tmp/other.png"
        mw.img_width.setValue(150)
        mw.img_height.setValue(50)
        mw.remember_image_size("/tmp/test.png", 300, 100)
        assert mw.img_width.value() == 150
        assert mw.img_height.value() == 50


class TestRecentImages:
    def test_add_recent_image(self, main_window):
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        assert mw.recent_images == ["/tmp/a.png"]

    def test_add_recent_image_deduplicates(self, main_window):
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        mw._add_recent_image("/tmp/b.png")
        mw._add_recent_image("/tmp/a.png")  # move to front
        assert mw.recent_images == ["/tmp/a.png", "/tmp/b.png"]

    def test_add_recent_image_caps_at_max(self, main_window):
        mw = main_window
        for i in range(15):
            mw._add_recent_image(f"/tmp/img{i}.png")
        assert len(mw.recent_images) == MAX_RECENT_IMAGES

    def test_remove_recent_image(self, main_window):
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        mw.image_sizes["/tmp/a.png"] = [100, 50]
        mw.remove_recent_image("/tmp/a.png")
        assert "/tmp/a.png" not in mw.recent_images
        assert "/tmp/a.png" not in mw.image_sizes

    def test_remove_resets_image_path_if_current(self, main_window):
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        mw.image_path = "/tmp/a.png"
        mw.remove_recent_image("/tmp/a.png")
        assert mw.image_path == ""

    def test_remove_keeps_image_path_if_different(self, main_window):
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        mw._add_recent_image("/tmp/b.png")
        mw.image_path = "/tmp/b.png"
        mw.remove_recent_image("/tmp/a.png")
        assert mw.image_path == "/tmp/b.png"


class TestImageCombo:
    def test_combo_has_choose_file_first(self, main_window):
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        assert mw.image_combo.itemText(0) == "Choose file..."
        assert mw.image_combo.count() == 2  # Choose + 1 image

    def test_combo_stores_path_as_user_role(self, main_window):
        from PyQt6.QtCore import Qt
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        path = mw.image_combo.itemData(1, Qt.ItemDataRole.UserRole)
        assert path == "/tmp/a.png"

    def test_combo_choose_file_has_no_user_role(self, main_window):
        from PyQt6.QtCore import Qt
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        data = mw.image_combo.itemData(0, Qt.ItemDataRole.UserRole)
        assert data is None

    def test_selecting_image_updates_spinboxes(self, main_window):
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        mw.image_sizes["/tmp/a.png"] = [300, 100]
        mw._on_image_combo_activated(1)
        assert mw.img_width.value() == 300
        assert mw.img_height.value() == 100

    def test_selecting_image_sets_image_path(self, main_window):
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        mw._on_image_combo_activated(1)
        assert mw.image_path == "/tmp/a.png"

    def test_selecting_image_switches_to_image_mode(self, main_window):
        mw = main_window
        mw._add_recent_image("/tmp/a.png")
        mw.radio_text.setChecked(True)
        mw._on_image_combo_activated(1)
        assert mw.radio_image.isChecked()


class TestResizeMemory:
    def test_resize_remembers_image_size(self, main_window, signature_png, simple_pdf):
        from pdfsign.core import PdfDocument
        mw = main_window
        mw.doc = PdfDocument(simple_pdf)
        mw.current_page = 0
        mw.image_path = str(signature_png)
        mw.doc.add_image(0, 100, 100, str(signature_png), 150, 50)
        mw.doc.update_annotation(0, width=250, height=80)
        # Simulate what mouseReleaseEvent should do after resize
        ann = mw.doc.pending_annotations()[0]
        mw.remember_image_size(ann.image_path, ann.width, ann.height)
        assert mw.image_sizes[str(signature_png)] == [250, 80]

    def test_mouserelease_after_resize_stores_size(self, main_window, signature_png, simple_pdf):
        """After canvas resize, the size is stored in image_sizes."""
        from PyQt6.QtCore import Qt, QPointF
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QEvent
        from pdfsign.core import PdfDocument

        mw = main_window
        mw.doc = PdfDocument(simple_pdf)
        mw.current_page = 0
        mw.refresh_page()
        mw.doc.add_image(0, 100, 100, str(signature_png), 150, 50)
        # Set up canvas as if resize just happened
        mw.canvas.selected_index = 0
        mw.canvas.resizing = True
        mw.canvas.resize_handle = "br"
        # Update the annotation to new size
        mw.doc.update_annotation(0, width=200, height=70)
        # Simulate mouse release
        event = QMouseEvent(
            QEvent.Type.MouseButtonRelease,
            QPointF(0, 0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        mw.canvas.mouseReleaseEvent(event)
        assert mw.image_sizes[str(signature_png)] == [200, 70]


class TestCornerResizeDirection:
    """Regression: left-side corner handles (tl, bl) resize in wrong direction.

    Dragging tl/bl handle outward (left) should grow the image, but it shrinks.
    Right-side handles (tr, br) work correctly.
    """

    def _setup_resize(self, main_window, signature_png, simple_pdf, handle, start_x, start_y):
        from PyQt6.QtCore import QPointF
        from pdfsign.core import PdfDocument

        mw = main_window
        mw.doc = PdfDocument(simple_pdf)
        mw.current_page = 0
        mw.zoom = 1.0
        mw.refresh_page()
        # Place image at (100, 100), size 150x50
        mw.doc.add_image(0, 100, 100, str(signature_png), 150, 50)
        canvas = mw.canvas
        canvas.selected_index = 0
        canvas.resizing = True
        canvas.resize_handle = handle
        canvas._resize_start_pos = QPointF(start_x, start_y)
        canvas._resize_start_w = 150
        canvas._resize_start_h = 50
        canvas._resize_start_x = 100
        canvas._resize_start_y = 100
        return mw

    def _do_move(self, mw, x, y):
        from PyQt6.QtCore import Qt, QPointF, QEvent
        from PyQt6.QtGui import QMouseEvent

        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(x, y),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        mw.canvas.mouseMoveEvent(event)
        return mw.doc.pending_annotations()[0]

    def test_br_drag_right_grows(self, main_window, signature_png, simple_pdf):
        """Bottom-right handle: drag right should grow width."""
        mw = self._setup_resize(main_window, signature_png, simple_pdf, "br", 250, 150)
        ann = self._do_move(mw, 290, 150)  # drag 40px right
        assert ann.width > 150, f"Expected width > 150, got {ann.width}"

    def test_br_drag_left_shrinks(self, main_window, signature_png, simple_pdf):
        """Bottom-right handle: drag left should shrink width."""
        mw = self._setup_resize(main_window, signature_png, simple_pdf, "br", 250, 150)
        ann = self._do_move(mw, 210, 150)  # drag 40px left
        assert ann.width < 150, f"Expected width < 150, got {ann.width}"

    def test_tl_drag_left_grows(self, main_window, signature_png, simple_pdf):
        """Top-left handle: drag left should GROW width (expanding leftward)."""
        mw = self._setup_resize(main_window, signature_png, simple_pdf, "tl", 100, 100)
        ann = self._do_move(mw, 60, 100)  # drag 40px left
        assert ann.width > 150, f"Expected width > 150, got {ann.width}"

    def test_tl_drag_right_shrinks(self, main_window, signature_png, simple_pdf):
        """Top-left handle: drag right should SHRINK width."""
        mw = self._setup_resize(main_window, signature_png, simple_pdf, "tl", 100, 100)
        ann = self._do_move(mw, 140, 100)  # drag 40px right
        assert ann.width < 150, f"Expected width < 150, got {ann.width}"

    def test_bl_drag_left_grows(self, main_window, signature_png, simple_pdf):
        """Bottom-left handle: drag left should GROW width."""
        mw = self._setup_resize(main_window, signature_png, simple_pdf, "bl", 100, 150)
        ann = self._do_move(mw, 60, 150)  # drag 40px left
        assert ann.width > 150, f"Expected width > 150, got {ann.width}"

    def test_tr_drag_up_grows(self, main_window, signature_png, simple_pdf):
        """Top-right handle: drag up should GROW height."""
        mw = self._setup_resize(main_window, signature_png, simple_pdf, "tr", 250, 100)
        ann = self._do_move(mw, 250, 60)  # drag 40px up
        assert ann.height > 50, f"Expected height > 50, got {ann.height}"


class TestSettingsRoundTrip:
    def test_image_sizes_persist(self, main_window):
        mw = main_window
        mw.image_sizes = {"/tmp/a.png": [200, 65]}
        mw.recent_images = ["/tmp/a.png"]
        mw.save_settings()
        # Reset and reload
        mw.image_sizes = {}
        mw.recent_images = []
        mw.load_settings()
        assert mw.image_sizes.get("/tmp/a.png") == [200, 65]

    def test_recent_images_filters_nonexistent(self, main_window, signature_png):
        mw = main_window
        mw.recent_images = [str(signature_png), "/tmp/nonexistent.png"]
        mw.save_settings()
        mw.recent_images = []
        mw.load_settings()
        assert str(signature_png) in mw.recent_images
        assert "/tmp/nonexistent.png" not in mw.recent_images

    def test_backward_compat_image_path(self, main_window, signature_png):
        """Old image_path key should be added to recent_images if not present."""
        from PyQt6.QtCore import QSettings
        mw = main_window
        mw.recent_images = []
        mw.image_path = str(signature_png)
        mw.save_settings()
        # Clear recent_images in settings to simulate old format
        s = QSettings("PDF Simple Signing", "PDF Simple Signing")
        s.setValue("recent_images", "[]")
        mw.recent_images = []
        mw.load_settings()
        assert str(signature_png) in mw.recent_images


class TestSpinboxWiring:
    def test_spinbox_width_change_updates_image_sizes(self, main_window):
        mw = main_window
        mw.image_path = "/tmp/a.png"
        mw.image_sizes["/tmp/a.png"] = [150, 50]
        mw.img_width.setValue(200)
        assert mw.image_sizes["/tmp/a.png"][0] == 200

    def test_spinbox_height_change_updates_image_sizes(self, main_window):
        mw = main_window
        mw.image_path = "/tmp/a.png"
        mw.image_sizes["/tmp/a.png"] = [150, 50]
        mw.img_height.setValue(80)
        assert mw.image_sizes["/tmp/a.png"][1] == 80

    def test_spinbox_no_update_when_no_image(self, main_window):
        mw = main_window
        mw.image_path = ""
        mw.img_width.setValue(200)
        assert "" not in mw.image_sizes

    def test_spinbox_guard_prevents_recursive_update(self, main_window):
        """Programmatic spinbox changes via remember_image_size should not re-trigger."""
        mw = main_window
        mw.image_path = "/tmp/a.png"
        mw.remember_image_size("/tmp/a.png", 300, 100)
        assert mw.image_sizes["/tmp/a.png"] == [300, 100]
