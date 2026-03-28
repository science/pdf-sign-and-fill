import os
import sys
from datetime import date

from PyQt6.QtCore import Qt, QRectF, QPointF, QSettings, QEvent
from PyQt6.QtGui import (
    QPixmap, QPainter, QFont, QColor, QFontDatabase,
    QKeySequence, QAction, QPen, QFontMetricsF,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QScrollArea, QWidget, QToolBar,
    QFileDialog, QLabel, QInputDialog, QStatusBar, QPushButton,
    QMessageBox, QRadioButton, QSpinBox,
    QComboBox, QColorDialog, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox,
)

from pdfsign.core import PdfDocument

DEFAULT_TEXT = f"Signed {date.today()}"
DEFAULT_ZOOM = 1.5
ZOOM_LEVELS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

FONTS = {
    "Liberation Sans": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "Liberation Serif": "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "Liberation Mono": "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "DejaVu Sans": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVu Serif": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "DejaVu Sans Mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
}

HANDLE_SIZE = 8  # pixels for resize handles
PAGE_TURN_ZONE = 80  # pixels for scroll-to-turn zone below/above page
PAGE_TURN_TICKS = 8  # number of scroll ticks to trigger page turn
MAX_RECENT_TEXTS = 10
DEFAULT_RECENT_TEXTS = ["Signed {date}", "{name}", "{name} - {date}", "{date}"]


def expand_variables(template, settings_vars):
    """Expand {date}, {name} etc. in a template string."""
    result = template
    result = result.replace("{date}", str(date.today()))
    result = result.replace("{name}", settings_vars.get("name", ""))
    return result


class SettingsDialog(QDialog):
    def __init__(self, parent=None, current_name=""):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QFormLayout(self)
        self.name_edit = QLineEdit(current_name)
        layout.addRow("Name:", self.name_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)


class PdfCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.base_pixmap = QPixmap()
        self._font_path_to_family = {}

        # Selection and drag state
        self.selected_index = -1  # index into doc.pending_annotations(), -1 = none
        self.dragging = False
        self.drag_offset = QPointF(0, 0)  # offset from annotation origin to click point
        self.resizing = False
        self.resize_handle = None  # which handle is being dragged

        # Page turn scroll gate
        self.turn_progress = 0  # 0 to PAGE_TURN_TICKS
        self.turn_direction = 0  # +1 = next, -1 = prev

        self.setMouseTracking(True)

    def set_page(self, png_bytes: bytes):
        self.base_pixmap = QPixmap()
        self.base_pixmap.loadFromData(png_bytes)
        self.turn_progress = 0
        self.turn_direction = 0
        # Add space below for page turn zone (and above if not first page)
        mw = self.main_window
        extra_bottom = PAGE_TURN_ZONE if (mw.doc and mw.current_page < mw.doc.page_count() - 1) else 0
        extra_top = PAGE_TURN_ZONE if (mw.doc and mw.current_page > 0) else 0
        self._page_y_offset = extra_top
        from PyQt6.QtCore import QSize
        self.setFixedSize(QSize(
            self.base_pixmap.width(),
            self.base_pixmap.height() + extra_top + extra_bottom,
        ))
        self.update()

    def register_font(self, font_path: str):
        if font_path in self._font_path_to_family:
            return
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                self._font_path_to_family[font_path] = families[0]

    def qt_family_for(self, font_path: str) -> str:
        return self._font_path_to_family.get(font_path, "Liberation Sans")

    def _ann_bbox_screen(self, ann, zoom):
        """Return screen-space bounding rect for an annotation."""
        sx = ann.x * zoom
        sy = ann.y * zoom
        if ann.type == "text":
            font_family = self.qt_family_for(ann.font_path)
            font = QFont(font_family)
            font.setPixelSize(max(1, int(ann.font_size * zoom)))
            fm = QFontMetricsF(font)
            br = fm.boundingRect(ann.text)
            # drawText uses baseline at (sx, sy), so text extends upward
            return QRectF(sx + br.x(), sy + br.y(), br.width(), br.height())
        elif ann.type == "image":
            return QRectF(sx, sy, ann.width * zoom, ann.height * zoom)
        return QRectF()

    def _get_resize_handles(self, rect):
        """Return dict of handle_name -> QRectF for an image bounding rect."""
        hs = HANDLE_SIZE
        hh = hs / 2
        cx, cy = rect.center().x(), rect.center().y()
        return {
            "tl": QRectF(rect.left() - hh, rect.top() - hh, hs, hs),
            "tr": QRectF(rect.right() - hh, rect.top() - hh, hs, hs),
            "bl": QRectF(rect.left() - hh, rect.bottom() - hh, hs, hs),
            "br": QRectF(rect.right() - hh, rect.bottom() - hh, hs, hs),
            "t": QRectF(cx - hh, rect.top() - hh, hs, hs),
            "b": QRectF(cx - hh, rect.bottom() - hh, hs, hs),
            "l": QRectF(rect.left() - hh, cy - hh, hs, hs),
            "r": QRectF(rect.right() - hh, cy - hh, hs, hs),
        }

    def _hit_test(self, pos):
        """Return (annotation_index, handle_name_or_None) for click position.
        Returns (-1, None) if nothing hit. Checks current page only."""
        mw = self.main_window
        if mw.doc is None:
            return -1, None

        zoom = mw.zoom
        offy = getattr(self, "_page_y_offset", 0)
        anns = mw.doc.pending_annotations()

        # First check resize handles on selected annotation
        if self.selected_index >= 0 and self.selected_index < len(anns):
            sel = anns[self.selected_index]
            if sel.page_num == mw.current_page and sel.type == "image":
                bbox = self._ann_bbox_screen(sel, zoom)
                bbox.translate(0, offy)
                handles = self._get_resize_handles(bbox)
                for name, hrect in handles.items():
                    if hrect.contains(pos):
                        return self.selected_index, name

        # Then check annotations (reverse order so topmost is hit first)
        for i in range(len(anns) - 1, -1, -1):
            ann = anns[i]
            if ann.page_num != mw.current_page:
                continue
            bbox = self._ann_bbox_screen(ann, zoom)
            bbox.translate(0, offy)
            if bbox.contains(pos):
                return i, None

        return -1, None

    def paintEvent(self, event):
        painter = QPainter(self)
        offy = getattr(self, "_page_y_offset", 0)

        # Fill background for turn zones
        painter.fillRect(self.rect(), QColor(220, 220, 220))

        # Draw the page
        painter.drawPixmap(0, offy, self.base_pixmap)

        mw = self.main_window
        if mw.doc is None:
            painter.end()
            return

        zoom = mw.zoom
        current_page = mw.current_page
        anns = mw.doc.pending_annotations()

        for i, ann in enumerate(anns):
            if ann.page_num != current_page:
                continue
            sx = ann.x * zoom
            sy = ann.y * zoom + offy

            if ann.type == "text":
                font_family = self.qt_family_for(ann.font_path)
                font = QFont(font_family)
                font.setPixelSize(max(1, int(ann.font_size * zoom)))
                painter.setFont(font)
                r, g, b = ann.color
                painter.setPen(QColor(int(r * 255), int(g * 255), int(b * 255)))
                painter.drawText(int(sx), int(sy), ann.text)
            elif ann.type == "image":
                pixmap = QPixmap(ann.image_path)
                target = QRectF(sx, sy, ann.width * zoom, ann.height * zoom)
                painter.drawPixmap(target.toRect(), pixmap)

            # Draw selection highlight
            if i == self.selected_index:
                bbox = self._ann_bbox_screen(ann, zoom)
                bbox.translate(0, offy)
                pen = QPen(QColor(0, 120, 215), 2, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(bbox.adjusted(-2, -2, 2, 2))

                # Draw resize handles for images
                if ann.type == "image":
                    handles = self._get_resize_handles(bbox)
                    painter.setPen(QPen(QColor(0, 120, 215), 1))
                    painter.setBrush(QColor(255, 255, 255))
                    for hrect in handles.values():
                        painter.drawRect(hrect)

        # Draw page turn zones
        page_bottom = offy + self.base_pixmap.height()
        w = self.base_pixmap.width()

        # Bottom turn zone (next page)
        if mw.doc and current_page < mw.doc.page_count() - 1:
            self._draw_turn_zone(painter, page_bottom, w, +1)

        # Top turn zone (prev page)
        if mw.doc and current_page > 0:
            self._draw_turn_zone(painter, 0, w, -1)

        painter.end()

    def _draw_turn_zone(self, painter, y_start, width, direction):
        """Draw the scroll-to-turn progress zone."""
        zone = QRectF(0, y_start, width, PAGE_TURN_ZONE)
        painter.fillRect(zone, QColor(230, 230, 230))

        # Only show progress if actively scrolling in this direction
        if self.turn_direction != direction or self.turn_progress <= 0:
            # Draw hint text
            painter.setPen(QColor(160, 160, 160))
            font = QFont("Liberation Sans", 10)
            painter.setFont(font)
            arrow = "▼" if direction > 0 else "▲"
            label = "next page" if direction > 0 else "previous page"
            painter.drawText(zone, Qt.AlignmentFlag.AlignCenter, f"{arrow}  Scroll for {label}  {arrow}")
            return

        # Draw progress bar
        progress = self.turn_progress / PAGE_TURN_TICKS
        bar_margin = 40
        bar_h = 12
        bar_y = y_start + (PAGE_TURN_ZONE - bar_h) / 2
        bar_bg = QRectF(bar_margin, bar_y, width - 2 * bar_margin, bar_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(200, 200, 200))
        painter.drawRoundedRect(bar_bg, 6, 6)

        bar_fill = QRectF(bar_margin, bar_y, (width - 2 * bar_margin) * progress, bar_h)
        painter.setBrush(QColor(0, 120, 215))
        painter.drawRoundedRect(bar_fill, 6, 6)

        # Arrow text
        painter.setPen(QColor(80, 80, 80))
        font = QFont("Liberation Sans", 10)
        painter.setFont(font)
        arrow = "▼" if direction > 0 else "▲"
        label = "next page" if direction > 0 else "previous page"
        text_rect = QRectF(0, y_start, width, (PAGE_TURN_ZONE - bar_h) / 2) if direction > 0 else \
                    QRectF(0, bar_y + bar_h, width, (PAGE_TURN_ZONE - bar_h) / 2)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, f"{arrow}  {label}  {arrow}")

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mw = self.main_window
        if mw.doc is None:
            return

        pos = event.position()
        offy = getattr(self, "_page_y_offset", 0)
        pdf_x = pos.x() / mw.zoom
        pdf_y = (pos.y() - offy) / mw.zoom

        # Hit test existing annotations first
        hit_idx, handle = self._hit_test(pos)

        if handle is not None:
            # Start resizing
            self.selected_index = hit_idx
            self.resizing = True
            self.resize_handle = handle
            self._resize_start_pos = pos
            ann = mw.doc.pending_annotations()[hit_idx]
            self._resize_start_w = ann.width
            self._resize_start_h = ann.height
            self._resize_start_x = ann.x
            self._resize_start_y = ann.y
            self.update()
            return

        if hit_idx >= 0:
            # Select and start dragging
            self.selected_index = hit_idx
            self.dragging = True
            ann = mw.doc.pending_annotations()[hit_idx]
            self.drag_offset = QPointF(
                pos.x() - ann.x * mw.zoom,
                pos.y() - (ann.y * mw.zoom + offy),
            )
            self.update()
            return

        # Nothing hit — deselect and create new annotation
        self.selected_index = -1

        if mw.mode == "text":
            template = mw.recent_combo.currentText() or DEFAULT_TEXT
            expanded = mw._expand_text(template)
            text, ok = QInputDialog.getText(
                self, "Add Text", "Text:", text=expanded,
            )
            if not ok or not text:
                self.update()
                return
            mw._add_recent_text(template)
            mw.doc.add_text(
                mw.current_page, pdf_x, pdf_y,
                text, mw.current_font_path(),
                font_size=mw.font_size.value(),
                color=mw.text_color,
            )
        elif mw.mode == "image":
            if not mw.image_path:
                path, _ = QFileDialog.getOpenFileName(
                    self, "Choose Image", "",
                    "Images (*.png *.gif *.jpg *.jpeg)",
                )
                if not path:
                    self.update()
                    return
                mw.image_path = path
                mw.image_label.setText(path.split("/")[-1])
            mw.doc.add_image(
                mw.current_page, pdf_x, pdf_y,
                mw.image_path,
                mw.img_width.value(), mw.img_height.value(),
            )

        self.update()
        mw.update_status()

    def mouseMoveEvent(self, event):
        mw = self.main_window
        if mw.doc is None:
            return

        pos = event.position()

        if self.dragging and self.selected_index >= 0:
            offy = getattr(self, "_page_y_offset", 0)
            new_x = (pos.x() - self.drag_offset.x()) / mw.zoom
            new_y = (pos.y() - self.drag_offset.y() - offy) / mw.zoom
            mw.doc.update_annotation(self.selected_index, x=new_x, y=new_y)
            self.update()
            return

        if self.resizing and self.selected_index >= 0:
            dx = (pos.x() - self._resize_start_pos.x()) / mw.zoom
            dy = (pos.y() - self._resize_start_pos.y()) / mw.zoom
            h = self.resize_handle
            new_w = self._resize_start_w
            new_h = self._resize_start_h
            new_x = self._resize_start_x
            new_y = self._resize_start_y

            is_corner = len(h) == 2  # tl, tr, bl, br
            if is_corner:
                # Proportional resize: use the axis with larger movement
                aspect = self._resize_start_w / max(self._resize_start_h, 0.01)
                # Determine delta along the dominant drag direction
                if "r" in h:
                    d = dx
                elif "l" in h:
                    d = -dx
                else:
                    d = 0
                if "b" in h:
                    d_vert = dy
                elif "t" in h:
                    d_vert = -dy
                else:
                    d_vert = 0
                # Use whichever delta is larger in magnitude
                if abs(d) >= abs(d_vert):
                    new_w = max(10, self._resize_start_w + (d if "r" in h else -d))
                    new_h = max(10, new_w / aspect)
                else:
                    new_h = max(10, self._resize_start_h + (d_vert if "b" in h else -d_vert))
                    new_w = max(10, new_h * aspect)
                # Anchor the opposite corner
                if "l" in h:
                    new_x = self._resize_start_x + (self._resize_start_w - new_w)
                if "t" in h:
                    new_y = self._resize_start_y + (self._resize_start_h - new_h)
            else:
                # Edge handles: free resize in one axis
                if h == "r":
                    new_w = max(10, self._resize_start_w + dx)
                elif h == "l":
                    new_w = max(10, self._resize_start_w - dx)
                    new_x = self._resize_start_x + (self._resize_start_w - new_w)
                elif h == "b":
                    new_h = max(10, self._resize_start_h + dy)
                elif h == "t":
                    new_h = max(10, self._resize_start_h - dy)
                    new_y = self._resize_start_y + (self._resize_start_h - new_h)

            mw.doc.update_annotation(
                self.selected_index,
                x=new_x, y=new_y, width=new_w, height=new_h,
            )
            self.update()
            return

        # Update cursor based on what's under the mouse
        hit_idx, handle = self._hit_test(pos)
        if handle in ("tl", "br"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif handle in ("tr", "bl"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif handle in ("t", "b"):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif handle in ("l", "r"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif hit_idx >= 0:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.resizing = False
            self.resize_handle = None

    def keyPressEvent(self, event):
        mw = self.main_window
        if event.key() == Qt.Key.Key_Escape:
            self.selected_index = -1
            self.update()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.selected_index >= 0 and mw.doc:
                mw.doc.remove_annotation(self.selected_index)
                self.selected_index = -1
                self.update()
                mw.update_status()
        else:
            super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Simple Signing")
        self.doc = None
        self.current_page = 0
        self.zoom = DEFAULT_ZOOM
        self.mode = "text"
        self.image_path = ""

        self.text_color = (0.0, 0.0, 0.0)

        # Canvas in scroll area
        self.canvas = PdfCanvas(self)
        self.canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Register all fonts for preview
        for font_path in FONTS.values():
            self.canvas.register_font(font_path)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.viewport().installEventFilter(self)
        self.setCentralWidget(self.scroll)

        # Toolbar
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        toolbar.addAction("Open...", self.open_file)
        toolbar.addAction("Save As...", self.save_file)

        toolbar.addSeparator()
        self.btn_prev = QPushButton("<")
        self.btn_prev.setFixedWidth(30)
        self.btn_prev.clicked.connect(self.prev_page)
        toolbar.addWidget(self.btn_prev)

        self.page_label = QLabel("No file")
        toolbar.addWidget(self.page_label)

        self.btn_next = QPushButton(">")
        self.btn_next.setFixedWidth(30)
        self.btn_next.clicked.connect(self.next_page)
        toolbar.addWidget(self.btn_next)

        toolbar.addSeparator()
        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.setFixedWidth(30)
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        toolbar.addWidget(self.btn_zoom_out)

        self.zoom_label = QLabel(f" {int(self.zoom * 100)}% ")
        toolbar.addWidget(self.zoom_label)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedWidth(30)
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        toolbar.addWidget(self.btn_zoom_in)

        toolbar.addSeparator()
        undo_action = QAction("Undo", self)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self.undo)
        toolbar.addAction(undo_action)
        toolbar.addAction("Clear All", self.clear_all)

        # Mode toggle
        toolbar.addSeparator()
        self.radio_text = QRadioButton("Text")
        self.radio_text.setChecked(True)
        self.radio_text.toggled.connect(lambda checked: self.set_mode("text") if checked else None)
        toolbar.addWidget(self.radio_text)

        self.radio_image = QRadioButton("Image")
        self.radio_image.toggled.connect(lambda checked: self.set_mode("image") if checked else None)
        toolbar.addWidget(self.radio_image)

        # Image controls
        self.image_label = QPushButton("No image")
        self.image_label.setFlat(True)
        self.image_label.setStyleSheet(
            "QPushButton { text-decoration: underline; color: palette(link); }"
            "QPushButton:hover { color: palette(highlight); }"
        )
        self.image_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.image_label.clicked.connect(self.quick_image_mode)
        toolbar.addWidget(self.image_label)
        toolbar.addAction("Choose...", self.choose_image)

        lbl_w = QLabel(" W:")
        toolbar.addWidget(lbl_w)
        self.img_width = QSpinBox()
        self.img_width.setRange(10, 600)
        self.img_width.setValue(150)
        toolbar.addWidget(self.img_width)

        lbl_h = QLabel(" H:")
        toolbar.addWidget(lbl_h)
        self.img_height = QSpinBox()
        self.img_height.setRange(10, 600)
        self.img_height.setValue(50)
        toolbar.addWidget(self.img_height)

        # Text controls toolbar (second row)
        text_toolbar = QToolBar("Text Controls")
        text_toolbar.setMovable(False)
        self.addToolBarBreak()
        self.addToolBar(text_toolbar)

        text_toolbar.addWidget(QLabel("Font: "))
        self.font_combo = QComboBox()
        self.font_combo.addItems(FONTS.keys())
        text_toolbar.addWidget(self.font_combo)

        text_toolbar.addWidget(QLabel(" Size: "))
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 72)
        self.font_size.setValue(12)
        text_toolbar.addWidget(self.font_size)

        text_toolbar.addWidget(QLabel(" "))
        self.color_btn = QPushButton("  ")
        self.color_btn.setFixedWidth(30)
        self.color_btn.setStyleSheet("background-color: black;")
        self.color_btn.clicked.connect(self.pick_color)
        text_toolbar.addWidget(self.color_btn)
        text_toolbar.addWidget(QLabel(" Color"))

        text_toolbar.addSeparator()
        text_toolbar.addWidget(QLabel(" Text: "))
        self.recent_combo = QComboBox()
        self.recent_combo.setEditable(True)
        self.recent_combo.setMinimumWidth(200)
        self.recent_combo.addItems(DEFAULT_RECENT_TEXTS)
        text_toolbar.addWidget(self.recent_combo)

        text_toolbar.addAction("Settings...", self.open_settings)

        # Keyboard shortcuts
        open_action = QAction("Open", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_file)
        self.addAction(open_action)

        save_action = QAction("Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_file)
        self.addAction(save_action)

        prev_action = QAction("Prev Page", self)
        prev_action.setShortcut(QKeySequence(Qt.Key.Key_Left))
        prev_action.triggered.connect(self.prev_page)
        self.addAction(prev_action)

        next_action = QAction("Next Page", self)
        next_action.setShortcut(QKeySequence(Qt.Key.Key_Right))
        next_action.triggered.connect(self.next_page)
        self.addAction(next_action)

        # Status bar
        self.statusBar().showMessage("Open a PDF to begin")

        # Size the window
        self.resize(900, 700)

        # Load persisted settings
        self.load_settings()

        # Auto-open file dialog on launch
        self.open_file()

    def _settings_vars(self):
        """Return dict of variable values for template expansion."""
        s = QSettings("PDF Simple Signing", "PDF Simple Signing")
        return {"name": s.value("user_name", "")}

    def _expand_text(self, template):
        return expand_variables(template, self._settings_vars())

    def _add_recent_text(self, template):
        """Add template to recent list (at top, no duplicates)."""
        items = [self.recent_combo.itemText(i) for i in range(self.recent_combo.count())]
        if template in items:
            items.remove(template)
        items.insert(0, template)
        items = items[:MAX_RECENT_TEXTS]
        self.recent_combo.clear()
        self.recent_combo.addItems(items)
        self.recent_combo.setCurrentIndex(0)

    def open_settings(self):
        s = QSettings("PDF Simple Signing", "PDF Simple Signing")
        current_name = s.value("user_name", "")
        dlg = SettingsDialog(self, current_name)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            s.setValue("user_name", dlg.name_edit.text())

    def load_settings(self):
        s = QSettings("PDF Simple Signing", "PDF Simple Signing")
        # Window geometry
        geo = s.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        # Image path
        img = s.value("image_path", "")
        if img and os.path.exists(img):
            self.image_path = img
            self.image_label.setText(img.split("/")[-1])
        # Image size
        self.img_width.setValue(int(s.value("img_width", 150)))
        self.img_height.setValue(int(s.value("img_height", 50)))
        # Font
        font_name = s.value("font_name", "Liberation Sans")
        idx = self.font_combo.findText(font_name)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.font_size.setValue(int(s.value("font_size", 12)))
        # Color
        color_str = s.value("text_color", "0,0,0")
        parts = [float(x) for x in color_str.split(",")]
        self.text_color = tuple(parts)
        r, g, b = self.text_color
        self.color_btn.setStyleSheet(
            f"background-color: rgb({int(r*255)},{int(g*255)},{int(b*255)});"
        )
        # Zoom
        zoom_val = float(s.value("zoom", DEFAULT_ZOOM))
        if zoom_val in ZOOM_LEVELS:
            self.zoom = zoom_val
            self.zoom_label.setText(f" {int(self.zoom * 100)}% ")
        # Last PDF directory
        self._last_pdf_dir = s.value("last_pdf_dir", "")
        # Recent texts
        recent = s.value("recent_texts")
        if recent and isinstance(recent, list):
            self.recent_combo.clear()
            self.recent_combo.addItems(recent)

    def save_settings(self):
        s = QSettings("PDF Simple Signing", "PDF Simple Signing")
        s.setValue("geometry", self.saveGeometry())
        s.setValue("image_path", self.image_path)
        s.setValue("img_width", self.img_width.value())
        s.setValue("img_height", self.img_height.value())
        s.setValue("font_name", self.font_combo.currentText())
        s.setValue("font_size", self.font_size.value())
        r, g, b = self.text_color
        s.setValue("text_color", f"{r},{g},{b}")
        s.setValue("zoom", self.zoom)
        s.setValue("last_pdf_dir", getattr(self, "_last_pdf_dir", ""))
        recent = [self.recent_combo.itemText(i) for i in range(self.recent_combo.count())]
        s.setValue("recent_texts", recent[:MAX_RECENT_TEXTS])

    def eventFilter(self, obj, event):
        if obj == self.scroll.viewport() and event.type() == QEvent.Type.Wheel:
            vbar = self.scroll.verticalScrollBar()
            at_bottom = vbar.value() >= vbar.maximum()
            at_top = vbar.value() <= vbar.minimum()
            delta = event.angleDelta().y()  # negative = scroll down

            if at_bottom and delta < 0 and self.doc and self.current_page < self.doc.page_count() - 1:
                # Scrolling down past bottom
                if self.canvas.turn_direction != 1:
                    self.canvas.turn_direction = 1
                    self.canvas.turn_progress = 0
                self.canvas.turn_progress += 1
                self.canvas.update()
                if self.canvas.turn_progress >= PAGE_TURN_TICKS:
                    self.next_page()
                    # Scroll to top of new page
                    self.scroll.verticalScrollBar().setValue(0)
                return True  # consume the event

            elif at_top and delta > 0 and self.doc and self.current_page > 0:
                # Scrolling up past top
                if self.canvas.turn_direction != -1:
                    self.canvas.turn_direction = -1
                    self.canvas.turn_progress = 0
                self.canvas.turn_progress += 1
                self.canvas.update()
                if self.canvas.turn_progress >= PAGE_TURN_TICKS:
                    self.prev_page()
                    # Scroll to bottom of new page
                    self.scroll.verticalScrollBar().setValue(
                        self.scroll.verticalScrollBar().maximum()
                    )
                return True  # consume the event

            else:
                # Normal scroll — reset turn progress
                if self.canvas.turn_progress > 0:
                    self.canvas.turn_progress = 0
                    self.canvas.turn_direction = 0
                    self.canvas.update()

        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)

    def open_file(self):
        start_dir = getattr(self, "_last_pdf_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", start_dir, "PDF Files (*.pdf)"
        )
        if not path:
            return
        self._last_pdf_dir = os.path.dirname(path)
        self.doc = PdfDocument(path)
        self.current_page = 0
        self.canvas.selected_index = -1
        self.setWindowTitle(f"PDF Simple Signing — {path}")
        self.refresh_page()

    def save_file(self):
        if self.doc is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF", "", "PDF Files (*.pdf)"
        )
        if not path:
            return
        self.doc.save(path)
        self.statusBar().showMessage(f"Saved to {path}")

    def set_mode(self, mode):
        self.mode = mode

    def pick_color(self):
        r, g, b = self.text_color
        initial = QColor(int(r * 255), int(g * 255), int(b * 255))
        color = QColorDialog.getColor(initial, self, "Text Color")
        if color.isValid():
            self.text_color = (color.redF(), color.greenF(), color.blueF())
            self.color_btn.setStyleSheet(f"background-color: {color.name()};")

    def current_font_path(self) -> str:
        name = self.font_combo.currentText()
        return FONTS.get(name, list(FONTS.values())[0])

    def quick_image_mode(self):
        if self.image_path and os.path.exists(self.image_path):
            self.radio_image.setChecked(True)
        else:
            self.choose_image()

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Image", "",
            "Images (*.png *.gif *.jpg *.jpeg)",
        )
        if path:
            self.image_path = path
            self.image_label.setText(path.split("/")[-1])
            self.radio_image.setChecked(True)

    def zoom_in(self):
        idx = ZOOM_LEVELS.index(self.zoom) if self.zoom in ZOOM_LEVELS else 0
        if idx < len(ZOOM_LEVELS) - 1:
            self.zoom = ZOOM_LEVELS[idx + 1]
            self.zoom_label.setText(f" {int(self.zoom * 100)}% ")
            self.canvas.selected_index = -1
            self.refresh_page()

    def zoom_out(self):
        idx = ZOOM_LEVELS.index(self.zoom) if self.zoom in ZOOM_LEVELS else 0
        if idx > 0:
            self.zoom = ZOOM_LEVELS[idx - 1]
            self.zoom_label.setText(f" {int(self.zoom * 100)}% ")
            self.canvas.selected_index = -1
            self.refresh_page()

    def undo(self):
        if self.doc and self.doc.undo():
            self.canvas.selected_index = -1
            self.canvas.update()
            self.update_status()

    def clear_all(self):
        if self.doc is None:
            return
        if not self.doc.pending_annotations():
            return
        reply = QMessageBox.question(
            self, "Clear All", "Remove all annotations?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.doc.clear()
            self.canvas.selected_index = -1
            self.canvas.update()
            self.update_status()

    def prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.canvas.selected_index = -1
            self.refresh_page()

    def next_page(self):
        if self.doc and self.current_page < self.doc.page_count() - 1:
            self.current_page += 1
            self.canvas.selected_index = -1
            self.refresh_page()

    def refresh_page(self):
        if self.doc is None:
            return
        png_bytes = self.doc.render_page(self.current_page, self.zoom)
        self.canvas.set_page(png_bytes)
        self.page_label.setText(f" Page {self.current_page + 1} / {self.doc.page_count()} ")
        self.update_status()

    def update_status(self):
        if self.doc is None:
            return
        n = len(self.doc.pending_annotations())
        sel = ""
        if self.canvas.selected_index >= 0:
            sel = f" | Selected: #{self.canvas.selected_index + 1}"
        self.statusBar().showMessage(f"{n} annotation(s) pending{sel}")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
