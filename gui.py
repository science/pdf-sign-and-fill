import json
import locale
import os
import sys
from datetime import date

from PyQt6.QtCore import Qt, QRectF, QPointF, QPoint, QSettings, QEvent, QSize
from PyQt6.QtGui import (
    QPixmap, QPainter, QFont, QColor, QFontDatabase,
    QKeySequence, QAction, QPen, QFontMetricsF,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QScrollArea, QWidget, QToolBar,
    QFileDialog, QLabel, QInputDialog, QStatusBar, QPushButton,
    QMessageBox, QRadioButton, QSpinBox,
    QComboBox, QColorDialog, QDialog, QFormLayout, QLineEdit,
    QDialogButtonBox, QGroupBox, QVBoxLayout, QHBoxLayout,
    QStyledItemDelegate, QStyleOptionViewItem,
    QToolButton, QButtonGroup, QTextEdit, QMenu,
)

import fitz

from pdfsign.core import PdfDocument
from pdfsign.geometry import fit_image_to_bbox, normalize_bbox

DEFAULT_TEXT = f"Signed {date.today()}"

def _system_date_format():
    """Get the system locale's date format string, or a sensible default."""
    try:
        locale.setlocale(locale.LC_TIME, "")
        fmt = locale.nl_langinfo(locale.D_FMT)
        if fmt:
            return fmt
    except (locale.Error, AttributeError):
        pass
    return "%Y-%m-%d"
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

def _migrate_legacy_settings():
    """One-time migration from 'PDF Simple Signing' QSettings to 'PDF Sign & Fill'."""
    new = QSettings("PDF Sign & Fill", "PDF Sign & Fill")
    if new.allKeys():
        return
    old = QSettings("PDF Simple Signing", "PDF Simple Signing")
    if not old.allKeys():
        return
    for k in old.allKeys():
        new.setValue(k, old.value(k))
    new.sync()
    old.clear()


FIELD_FILL_COLOR = QColor(60, 130, 220, 60)
FIELD_FILL_HOVER = QColor(60, 130, 220, 100)
FIELD_FILLED_COLOR = QColor(80, 170, 100, 70)
FIELD_OUTLINE = QColor(40, 100, 200)

HANDLE_SIZE = 8  # pixels for resize handles
PAGE_TURN_ZONE = 80  # pixels for scroll-to-turn zone below/above page
PAGE_TURN_TICKS = 8  # number of scroll ticks to trigger page turn
MAX_RECENT_TEXTS = 10
MAX_RECENT_IMAGES = 10
THUMBNAIL_SIZE = 32
DEFAULT_RECENT_TEXTS = ["Signed {date}", "{name}", "{name} - {date}", "{date}"]


def expand_variables(template, settings_vars):
    """Expand {date}, {name} etc. in a template string."""
    result = template
    date_fmt = settings_vars.get("date_format", "%Y-%m-%d")
    result = result.replace("{date}", date.today().strftime(date_fmt))
    result = result.replace("{name}", settings_vars.get("name", ""))
    return result


COMMON_DATE_FORMATS = [
    ("%Y-%m-%d", "2026-03-28"),
    ("%m/%d/%Y", "03/28/2026"),
    ("%d/%m/%Y", "28/03/2026"),
    ("%B %d, %Y", "March 28, 2026"),
    ("%b %d, %Y", "Mar 28, 2026"),
    ("%d %B %Y", "28 March 2026"),
    ("%d %b %Y", "28 Mar 2026"),
    ("%m-%d-%Y", "03-28-2026"),
    ("%d.%m.%Y", "28.03.2026"),
]

DATE_FORMAT_GUIDE = (
    "<b>Common format codes:</b><br>"
    "<table cellpadding='2'>"
    "<tr><td><code>%Y</code></td><td>4-digit year (2026)</td></tr>"
    "<tr><td><code>%y</code></td><td>2-digit year (26)</td></tr>"
    "<tr><td><code>%m</code></td><td>Month number, zero-padded (03)</td></tr>"
    "<tr><td><code>%d</code></td><td>Day, zero-padded (28)</td></tr>"
    "<tr><td><code>%B</code></td><td>Full month name (March)</td></tr>"
    "<tr><td><code>%b</code></td><td>Abbreviated month (Mar)</td></tr>"
    "<tr><td><code>%A</code></td><td>Full weekday name (Saturday)</td></tr>"
    "<tr><td><code>%a</code></td><td>Abbreviated weekday (Sat)</td></tr>"
    "</table><br>"
    "Full reference: "
    "<a href='https://strftime.org/'>https://strftime.org/</a>"
)


class SettingsDialog(QDialog):
    def __init__(self, parent=None, current_name="", current_date_format=""):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        # Name field
        name_group = QGroupBox("Name")
        name_layout = QFormLayout()
        self.name_edit = QLineEdit(current_name)
        name_layout.addRow("Your name:", self.name_edit)
        name_group.setLayout(name_layout)
        layout.addWidget(name_group)

        # Date format field
        date_group = QGroupBox("Date Format")
        date_layout = QVBoxLayout()

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))
        self.date_combo = QComboBox()
        self.date_combo.setEditable(True)
        self.date_combo.setMinimumWidth(200)
        # Populate with common formats showing preview
        for fmt, example in COMMON_DATE_FORMATS:
            self.date_combo.addItem(f"{fmt}  →  {example}", fmt)
        # Set current value
        if current_date_format:
            idx = self.date_combo.findData(current_date_format)
            if idx >= 0:
                self.date_combo.setCurrentIndex(idx)
            else:
                # Custom format not in presets — show it raw
                self.date_combo.setEditText(current_date_format)
        fmt_row.addWidget(self.date_combo)
        date_layout.addLayout(fmt_row)

        # Live preview
        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("Preview:"))
        self.date_preview = QLabel()
        self.date_preview.setStyleSheet("font-weight: bold;")
        preview_row.addWidget(self.date_preview)
        preview_row.addStretch()
        date_layout.addLayout(preview_row)

        # Guide
        guide_label = QLabel(DATE_FORMAT_GUIDE)
        guide_label.setOpenExternalLinks(True)
        guide_label.setWordWrap(True)
        date_layout.addWidget(guide_label)

        date_group.setLayout(date_layout)
        layout.addWidget(date_group)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Wire up live preview
        self.date_combo.currentIndexChanged.connect(self._update_preview)
        self.date_combo.currentTextChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self):
        fmt = self.get_date_format()
        try:
            preview = date.today().strftime(fmt)
        except (ValueError, TypeError):
            preview = "(invalid format)"
        self.date_preview.setText(preview)

    def get_date_format(self):
        """Return the raw strftime format string (not the display text with arrow)."""
        # If a preset is selected, use its data
        data = self.date_combo.currentData()
        if data:
            return data
        # Otherwise parse custom text — strip any "→ example" portion
        text = self.date_combo.currentText().strip()
        if "→" in text:
            text = text.split("→")[0].strip()
        return text if text else "%Y-%m-%d"


class ImageItemDelegate(QStyledItemDelegate):
    """Custom delegate for image combo: thumbnail + filename + delete button."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._thumb_cache = {}

    def _get_thumbnail(self, path):
        if path not in self._thumb_cache:
            pm = QPixmap(path)
            if pm.isNull():
                pm = QPixmap(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
                pm.fill(QColor(200, 200, 200))
            else:
                pm = pm.scaled(
                    THUMBNAIL_SIZE, THUMBNAIL_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self._thumb_cache[path] = pm
        return self._thumb_cache[path]

    def invalidate_thumbnail(self, path):
        self._thumb_cache.pop(path, None)

    def sizeHint(self, option, index):
        if index.row() == 0:
            return super().sizeHint(option, index)
        return QSize(option.rect.width(), THUMBNAIL_SIZE + 8)

    def paint(self, painter, option, index):
        # Draw background (selection/hover highlight)
        style = option.widget.style() if option.widget else None
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if style:
            style.drawPrimitive(style.PrimitiveElement.PE_PanelItemViewItem, opt, painter, option.widget)

        if index.row() == 0:
            # "Choose file..." — draw as plain text
            painter.setPen(option.palette.color(option.palette.ColorRole.Text))
            text_rect = option.rect.adjusted(6, 0, 0, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, "Choose file...")
            return

        path = index.data(Qt.ItemDataRole.UserRole)
        if not path:
            super().paint(painter, option, index)
            return

        rect = option.rect
        margin = 4

        # Thumbnail
        thumb = self._get_thumbnail(path)
        thumb_x = rect.left() + margin
        thumb_y = rect.top() + (rect.height() - thumb.height()) // 2
        painter.drawPixmap(thumb_x, thumb_y, thumb)

        # Filename
        text_x = thumb_x + THUMBNAIL_SIZE + margin * 2
        filename = os.path.basename(path)
        painter.setPen(option.palette.color(option.palette.ColorRole.Text))
        painter.drawText(
            text_x, rect.top(), rect.width() - text_x - 28, rect.height(),
            Qt.AlignmentFlag.AlignVCenter, filename,
        )

        # Delete X button
        x_rect = self._x_button_rect(rect)
        painter.setPen(QColor(150, 150, 150))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(x_rect, Qt.AlignmentFlag.AlignCenter, "✕")

    def _x_button_rect(self, item_rect):
        return QRectF(
            item_rect.right() - 24,
            item_rect.top() + (item_rect.height() - 16) / 2,
            20, 16,
        )

    def editorEvent(self, event, model, option, index):
        if index.row() == 0:
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            x_rect = self._x_button_rect(option.rect)
            if x_rect.contains(event.position()):
                path = index.data(Qt.ItemDataRole.UserRole)
                if path:
                    self.main_window.remove_recent_image(path)
                return True
        return False


class FillFieldDialog(QDialog):
    """Multi-line dialog for editing a form field's value.

    Pre-populated with the field's current value (a pending fill or the original
    PDF default). Three buttons: OK saves whatever is in the box (empty included,
    which forces the field blank on save); Clear empties and accepts in one click;
    Cancel makes no changes.
    """

    def __init__(self, parent, field_name: str, initial_value: str):
        super().__init__(parent)
        self.setWindowTitle(f"Fill: {field_name}")
        self.resize(500, 260)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Value for {field_name}:"))
        self.text_edit = QTextEdit()
        self.text_edit.setAcceptRichText(False)
        self.text_edit.setPlainText(initial_value)
        layout.addWidget(self.text_edit)
        button_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        clear_btn = QPushButton("Clear")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        clear_btn.clicked.connect(self._on_clear)
        cancel_btn.clicked.connect(self.reject)
        button_row.addStretch()
        button_row.addWidget(ok_btn)
        button_row.addWidget(clear_btn)
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)
        cursor = self.text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.text_edit.setTextCursor(cursor)
        self.text_edit.setFocus()

    def _on_clear(self):
        self.text_edit.clear()
        self.accept()

    def value(self) -> str:
        return self.text_edit.toPlainText()


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

        # Drag-to-draw bounding-box state (stamp mode, empty area)
        self.bbox_press_screen: QPointF | None = None
        self.bbox_current_screen: QPointF | None = None
        self.bbox_active = False  # flips True once drag passes startDragDistance

        # Page turn scroll gate
        self.turn_progress = 0  # 0 to PAGE_TURN_TICKS
        self.turn_direction = 0  # +1 = next, -1 = prev

        self._hover_field: str | None = None  # field_name under cursor in Fill mode

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
            if ann.wrap_width is not None:
                # Textbox mode: (ann.x, ann.y) is top-left; bbox is wrap_width
                # wide and as tall as the wrapped layout.
                wrap_w_screen = ann.wrap_width * zoom
                flags = int(
                    Qt.TextFlag.TextWordWrap
                    | Qt.AlignmentFlag.AlignTop
                    | Qt.AlignmentFlag.AlignLeft
                )
                layout = fm.boundingRect(
                    QRectF(0, 0, wrap_w_screen, 1e6), flags, ann.text
                )
                return QRectF(sx, sy, wrap_w_screen, layout.height())
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
                if ann.wrap_width is not None:
                    rect_w = ann.wrap_width * zoom
                    page_h_screen = self.base_pixmap.height()
                    rect = QRectF(sx, sy, rect_w, max(0, page_h_screen - (sy - offy)))
                    flags = int(
                        Qt.TextFlag.TextWordWrap
                        | Qt.AlignmentFlag.AlignTop
                        | Qt.AlignmentFlag.AlignLeft
                    )
                    painter.drawText(rect, flags, ann.text)
                else:
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

        # Drag-to-draw bbox rubber band (stamp mode)
        if (self.bbox_press_screen is not None
                and self.bbox_current_screen is not None
                and self.bbox_active):
            rubber = QRectF(self.bbox_press_screen, self.bbox_current_screen).normalized()
            painter.setPen(QPen(QColor(0, 120, 215), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rubber)

        # Fill mode: draw form-field overlays on the current page
        if mw.top_mode == "fill":
            fills_by_name = {f.field_name: f.value for f in mw.doc.pending_fields()}
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for ff in mw._form_field_cache:
                if ff.page_num != current_page:
                    continue
                fx0, fy0, fx1, fy1 = ff.rect
                screen = QRectF(
                    fx0 * zoom,
                    fy0 * zoom + offy,
                    (fx1 - fx0) * zoom,
                    (fy1 - fy0) * zoom,
                )
                effective = fills_by_name.get(ff.field_name, ff.value)
                if ff.widget_type in (fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_COMBOBOX):
                    is_filled = ff.field_name in fills_by_name
                    if is_filled:
                        painter.fillRect(screen, QColor(255, 255, 255))
                        painter.fillRect(screen, FIELD_FILLED_COLOR)
                    elif self._hover_field == ff.field_name:
                        painter.fillRect(screen, FIELD_FILL_HOVER)
                    else:
                        painter.fillRect(screen, FIELD_FILL_COLOR)
                    painter.setPen(QPen(FIELD_OUTLINE, 1))
                    painter.drawRect(screen)
                    if is_filled and fills_by_name[ff.field_name]:
                        painter.setPen(QColor(0, 0, 0))
                        font = QFont()
                        font.setPixelSize(max(8, int(min(screen.height() * 0.7, 18))))
                        painter.setFont(font)
                        painter.drawText(
                            screen.adjusted(4, 0, -4, 0),
                            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                            fills_by_name[ff.field_name],
                        )
                else:
                    # Checkbox / radio: only "on" if the effective value matches this
                    # widget's own on_state (radios in a group differ by on_state).
                    is_on = bool(ff.on_state) and effective == ff.on_state
                    if self._hover_field == ff.field_name:
                        painter.fillRect(screen, FIELD_FILL_HOVER)
                    else:
                        painter.fillRect(screen, FIELD_FILL_COLOR)
                    painter.setPen(QPen(FIELD_OUTLINE, 1))
                    painter.drawRect(screen)
                    if is_on:
                        painter.fillRect(screen.adjusted(2, 2, -2, -2), FIELD_FILLED_COLOR)
                        painter.setPen(QPen(QColor(0, 0, 0), 2))
                        font = QFont()
                        font.setPixelSize(max(10, int(min(screen.height() * 0.8, 22))))
                        painter.setFont(font)
                        glyph = "✓" if ff.widget_type == fitz.PDF_WIDGET_TYPE_CHECKBOX else "●"
                        painter.drawText(
                            screen,
                            int(Qt.AlignmentFlag.AlignCenter),
                            glyph,
                        )

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

        if mw.top_mode == "fill":
            self._mouse_press_fill(pdf_x, pdf_y)
            return

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
            mw.doc.begin_edit(hit_idx)
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
            mw.doc.begin_edit(hit_idx)
            self.update()
            return

        # Nothing hit — start a potential drag-draw. Defer placement until
        # release, so a tiny drag (below startDragDistance) can fall through to
        # the existing click-to-place behavior.
        self.selected_index = -1
        self.bbox_press_screen = pos
        self.bbox_current_screen = pos
        self.bbox_active = False
        self.update()

    def _place_at_click(self, page_num, pdf_x, pdf_y):
        mw = self.main_window
        if mw.mode == "text":
            template = mw.recent_combo.currentText() or DEFAULT_TEXT
            expanded = mw._expand_text(template)
            text, ok = QInputDialog.getText(
                self, "Add Text", "Text:", text=expanded,
            )
            if not ok or not text:
                return
            mw._add_recent_text(template)
            mw.doc.add_text(
                page_num, pdf_x, pdf_y,
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
                    return
                mw.image_path = path
                mw._add_recent_image(path)
            w, h = mw.get_image_size(mw.image_path)
            mw.doc.add_image(
                page_num, pdf_x, pdf_y,
                mw.image_path, w, h,
            )

    def _place_with_bbox(self, page_num, x, y, w, h):
        mw = self.main_window
        if mw.mode == "text":
            template = mw.recent_combo.currentText() or DEFAULT_TEXT
            expanded = mw._expand_text(template)
            text, ok = QInputDialog.getText(
                self, "Add Text", "Text:", text=expanded,
            )
            if not ok or not text:
                return
            mw._add_recent_text(template)
            mw.doc.add_text(
                page_num, x, y,
                text, mw.current_font_path(),
                font_size=mw.font_size.value(),
                color=mw.text_color,
                wrap_width=w,
            )
        elif mw.mode == "image":
            if not mw.image_path:
                path, _ = QFileDialog.getOpenFileName(
                    self, "Choose Image", "",
                    "Images (*.png *.gif *.jpg *.jpeg)",
                )
                if not path:
                    return
                mw.image_path = path
                mw._add_recent_image(path)
            pm = QPixmap(mw.image_path)
            if pm.isNull():
                return
            fit_w, fit_h = fit_image_to_bbox(pm.width(), pm.height(), w, h)
            if fit_w < 1 or fit_h < 1:
                return
            # Note: deliberately do not call mw.remember_image_size — drag-draw
            # placement must not change the per-image-path remembered default.
            mw.doc.add_image(page_num, x, y, mw.image_path, fit_w, fit_h)

    def _mouse_press_fill(self, pdf_x, pdf_y):
        mw = self.main_window
        hit = self._hit_field(pdf_x, pdf_y)
        if hit is None:
            return
        if hit.widget_type == fitz.PDF_WIDGET_TYPE_TEXT:
            self._open_text_fill_dialog(hit)
        elif hit.widget_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
            current = self._effective_field_value(hit)
            new = "Off" if current == hit.on_state else (hit.on_state or "Yes")
            mw.doc.fill_field(hit.field_name, new)
            self.update()
            mw.update_status()
        elif hit.widget_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
            # Always select this radio (its on_state); siblings deselect on save.
            if hit.on_state:
                mw.doc.fill_field(hit.field_name, hit.on_state)
                self.update()
                mw.update_status()
        elif hit.widget_type == fitz.PDF_WIDGET_TYPE_COMBOBOX:
            self._open_combobox_menu(hit, pdf_x, pdf_y)

    def _open_combobox_menu(self, ff, pdf_x, pdf_y):
        mw = self.main_window
        if not ff.choices:
            mw.statusBar().showMessage(f"Dropdown {ff.field_name!r} has no options")
            return
        menu = QMenu(self)
        current = self._effective_field_value(ff)
        for opt in ff.choices:
            act = menu.addAction(opt)
            act.setCheckable(True)
            if opt == current:
                act.setChecked(True)
        offy = getattr(self, "_page_y_offset", 0)
        screen_pt = QPoint(int(pdf_x * mw.zoom), int(pdf_y * mw.zoom + offy))
        chosen = menu.exec(self.mapToGlobal(screen_pt))
        if chosen is None:
            return
        new_value = chosen.text()
        mw.doc.fill_field(ff.field_name, new_value)
        self.update()
        mw.update_status()

    def _open_text_fill_dialog(self, ff):
        mw = self.main_window
        pending = next(
            (f for f in mw.doc.pending_fields() if f.field_name == ff.field_name),
            None,
        )
        current = pending.value if pending is not None else ff.value
        dlg = FillFieldDialog(self, ff.field_name, current)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_value = dlg.value()
        if pending is None and new_value == current:
            return
        mw.doc.fill_field(ff.field_name, new_value)
        self.update()
        mw.update_status()

    def _effective_field_value(self, ff):
        """Pending value if set, else the original baked-in value."""
        mw = self.main_window
        pending = next(
            (f for f in mw.doc.pending_fields() if f.field_name == ff.field_name),
            None,
        )
        return pending.value if pending is not None else ff.value

    def _hit_field(self, pdf_x, pdf_y):
        """Return the FormField under the PDF-space point on the current page, or None."""
        mw = self.main_window
        for ff in mw._form_field_cache:
            if ff.page_num != mw.current_page:
                continue
            x0, y0, x1, y1 = ff.rect
            if x0 <= pdf_x <= x1 and y0 <= pdf_y <= y1:
                return ff
        return None

    def mouseMoveEvent(self, event):
        mw = self.main_window
        if mw.doc is None:
            return

        pos = event.position()

        if mw.top_mode == "fill":
            offy = getattr(self, "_page_y_offset", 0)
            pdf_x = pos.x() / mw.zoom
            pdf_y = (pos.y() - offy) / mw.zoom
            hit = self._hit_field(pdf_x, pdf_y)
            new_hover = hit.field_name if hit is not None else None
            if new_hover != self._hover_field:
                self._hover_field = new_hover
                self.update()
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if new_hover else Qt.CursorShape.ArrowCursor
            )
            return

        if self.bbox_press_screen is not None:
            self.bbox_current_screen = pos
            if not self.bbox_active:
                delta = pos - self.bbox_press_screen
                if delta.manhattanLength() >= QApplication.startDragDistance():
                    self.bbox_active = True
            self.update()
            return

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
                # d and d_vert are already normalized to "outward" direction
                if abs(d) >= abs(d_vert):
                    new_w = max(10, self._resize_start_w + d)
                    new_h = max(10, new_w / aspect)
                else:
                    new_h = max(10, self._resize_start_h + d_vert)
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
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mw = self.main_window

        if self.bbox_press_screen is not None:
            press = self.bbox_press_screen
            current = self.bbox_current_screen
            active = self.bbox_active
            self.bbox_press_screen = None
            self.bbox_current_screen = None
            self.bbox_active = False
            if mw.doc is None:
                self.update()
                return
            offy = getattr(self, "_page_y_offset", 0)
            px1 = press.x() / mw.zoom
            py1 = (press.y() - offy) / mw.zoom
            if not active:
                self._place_at_click(mw.current_page, px1, py1)
            else:
                px2 = current.x() / mw.zoom
                py2 = (current.y() - offy) / mw.zoom
                x, y, w, h = normalize_bbox((px1, py1), (px2, py2))
                self._place_with_bbox(mw.current_page, x, y, w, h)
            self.update()
            mw.update_status()
            return

        was_dragging = self.dragging
        was_resizing = self.resizing
        self.dragging = False
        self.resizing = False
        self.resize_handle = None

        if (was_dragging or was_resizing) and mw.doc:
            mw.doc.commit_edit()

        if was_resizing and self.selected_index >= 0:
            if mw.doc:
                anns = mw.doc.pending_annotations()
                if self.selected_index < len(anns):
                    ann = anns[self.selected_index]
                    if ann.type == "image":
                        mw.remember_image_size(ann.image_path, ann.width, ann.height)

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
    def __init__(self, initial_path: str | None = None):
        super().__init__()
        _migrate_legacy_settings()
        self.setWindowTitle("PDF Sign & Fill")
        self.doc = None
        self.current_page = 0
        self.zoom = DEFAULT_ZOOM
        self.mode = "text"
        self.top_mode = "stamp"     # "stamp" or "fill"
        self._form_field_cache = []  # list[(page_num, field_name, rect_tuple, original_value)]
        self._xfa_notice_shown = False
        self.image_path = ""
        self.image_sizes = {}       # {path: [w, h]} — per-image remembered sizes
        self.recent_images = []     # ordered list of recent image paths
        self._updating_spinboxes = False

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

        # Top-level mode toggle (Stamp / Fill)
        self.btn_stamp = QToolButton()
        self.btn_stamp.setText("Stamp")
        self.btn_stamp.setCheckable(True)
        self.btn_stamp.setChecked(True)
        self.btn_stamp.setStyleSheet("QToolButton:checked { background: #ffe3b3; }")
        self.btn_fill = QToolButton()
        self.btn_fill.setText("Fill")
        self.btn_fill.setCheckable(True)
        self.btn_fill.setStyleSheet("QToolButton:checked { background: #d8e8ff; }")
        self._top_mode_group = QButtonGroup(self)
        self._top_mode_group.setExclusive(True)
        self._top_mode_group.addButton(self.btn_stamp)
        self._top_mode_group.addButton(self.btn_fill)
        toolbar.addWidget(self.btn_stamp)
        toolbar.addWidget(self.btn_fill)
        self.btn_stamp.toggled.connect(lambda on: self.set_top_mode("stamp") if on else None)
        self.btn_fill.toggled.connect(lambda on: self.set_top_mode("fill") if on else None)
        toolbar.addSeparator()

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

        # Image size controls (image selection moved to Row 2 combo)
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

        self.img_width.valueChanged.connect(self._on_size_spinbox_changed)
        self.img_height.valueChanged.connect(self._on_size_spinbox_changed)

        # Text controls toolbar (second row)
        text_toolbar = QToolBar("Text Controls")
        text_toolbar.setMovable(False)
        self.addToolBarBreak()
        self.addToolBar(text_toolbar)
        self.text_toolbar = text_toolbar

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

        text_toolbar.addSeparator()
        text_toolbar.addWidget(QLabel(" Image: "))
        self.image_combo = QComboBox()
        self.image_combo.setMinimumWidth(200)
        self._image_delegate = ImageItemDelegate(self, self.image_combo)
        self.image_combo.setItemDelegate(self._image_delegate)
        self.image_combo.addItem("Choose file...")
        self.image_combo.activated.connect(self._on_image_combo_activated)
        text_toolbar.addWidget(self.image_combo)

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

        if initial_path:
            self.load_file(initial_path)

    def _settings_vars(self):
        """Return dict of variable values for template expansion."""
        s = QSettings("PDF Sign & Fill", "PDF Sign & Fill")
        return {
            "name": s.value("user_name", ""),
            "date_format": s.value("date_format", _system_date_format()),
        }

    def _expand_text(self, template):
        return expand_variables(template, self._settings_vars())

    def remember_image_size(self, path, width, height):
        """Store per-image dimensions. Update spinboxes if this is the current image."""
        self.image_sizes[path] = [width, height]
        if path == self.image_path:
            self._updating_spinboxes = True
            self.img_width.setValue(int(width))
            self.img_height.setValue(int(height))
            self._updating_spinboxes = False

    def get_image_size(self, path):
        """Return remembered (w, h) for path, or fall back to spinbox values."""
        if path in self.image_sizes:
            w, h = self.image_sizes[path]
            return (w, h)
        return (self.img_width.value(), self.img_height.value())

    def _add_recent_image(self, path):
        """Add image path to recent list (front, dedup, capped)."""
        if path in self.recent_images:
            self.recent_images.remove(path)
        self.recent_images.insert(0, path)
        self.recent_images = self.recent_images[:MAX_RECENT_IMAGES]
        if hasattr(self, "image_combo"):
            self._rebuild_image_combo()

    def remove_recent_image(self, path):
        """Remove image from recent list and size memory."""
        if path in self.recent_images:
            self.recent_images.remove(path)
        self.image_sizes.pop(path, None)
        if self.image_path == path:
            self.image_path = ""
        if hasattr(self, "image_combo"):
            self._rebuild_image_combo()

    def _rebuild_image_combo(self):
        """Rebuild image combo from recent_images list."""
        if not hasattr(self, "image_combo"):
            return
        self.image_combo.clear()
        self.image_combo.addItem("Choose file...")
        for path in self.recent_images:
            self.image_combo.addItem(os.path.basename(path))
            self.image_combo.setItemData(
                self.image_combo.count() - 1, path, Qt.ItemDataRole.UserRole
            )

    def _on_image_combo_activated(self, index):
        """Handle image combo selection."""
        if index == 0:
            self.choose_image()
            return
        path = self.image_combo.itemData(index, Qt.ItemDataRole.UserRole)
        if path:
            self.image_path = path
            w, h = self.get_image_size(path)
            self._updating_spinboxes = True
            self.img_width.setValue(int(w))
            self.img_height.setValue(int(h))
            self._updating_spinboxes = False
            self.radio_image.setChecked(True)

    def _on_size_spinbox_changed(self):
        """When spinboxes change manually, update per-image memory."""
        if self._updating_spinboxes:
            return
        if self.image_path:
            self.image_sizes[self.image_path] = [
                self.img_width.value(), self.img_height.value()
            ]

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
        s = QSettings("PDF Sign & Fill", "PDF Sign & Fill")
        current_name = s.value("user_name", "")
        current_date_fmt = s.value("date_format", _system_date_format())
        dlg = SettingsDialog(self, current_name, current_date_fmt)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            s.setValue("user_name", dlg.name_edit.text())
            s.setValue("date_format", dlg.get_date_format())

    def load_settings(self):
        s = QSettings("PDF Sign & Fill", "PDF Sign & Fill")
        # Window geometry
        geo = s.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        # Recent images list
        raw = s.value("recent_images", "[]")
        try:
            self.recent_images = json.loads(raw) if isinstance(raw, str) else []
        except (json.JSONDecodeError, TypeError):
            self.recent_images = []
        self.recent_images = [p for p in self.recent_images if os.path.exists(p)]
        # Per-image sizes
        raw = s.value("image_sizes", "{}")
        try:
            self.image_sizes = json.loads(raw) if isinstance(raw, str) else {}
        except (json.JSONDecodeError, TypeError):
            self.image_sizes = {}
        # Image path (backward compat)
        img = s.value("image_path", "")
        if img and os.path.exists(img):
            self.image_path = img
            if img not in self.recent_images:
                self.recent_images.insert(0, img)
        # Rebuild image combo
        self._rebuild_image_combo()
        # Image size — use per-image memory if available
        if self.image_path and self.image_path in self.image_sizes:
            w, h = self.image_sizes[self.image_path]
            self.img_width.setValue(int(w))
            self.img_height.setValue(int(h))
        else:
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
        s = QSettings("PDF Sign & Fill", "PDF Sign & Fill")
        s.setValue("geometry", self.saveGeometry())
        s.setValue("image_path", self.image_path)
        s.setValue("recent_images", json.dumps(self.recent_images[:MAX_RECENT_IMAGES]))
        s.setValue("image_sizes", json.dumps(self.image_sizes))
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
        if self.doc and self.doc.is_dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved annotation changes. Close without saving?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.save_settings()
        super().closeEvent(event)

    def open_file(self):
        if self.doc and self.doc.is_dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved annotation changes. Open a new file without saving?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        start_dir = getattr(self, "_last_pdf_dir", "")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", start_dir, "PDF Files (*.pdf)"
        )
        if not path:
            return
        self.load_file(path)

    def load_file(self, path: str):
        """Load a PDF by path, without any dialog. Warn on failure, no crash."""
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "Open PDF", f"File not found: {path}")
            return
        try:
            doc = PdfDocument(path)
        except (fitz.FileDataError, RuntimeError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Open PDF", f"Could not open PDF: {e}")
            return
        self.doc = doc
        self.current_page = 0
        self.canvas.selected_index = -1
        self._last_pdf_dir = os.path.dirname(path)
        self.setWindowTitle(f"PDF Sign & Fill — {os.path.basename(path)}")
        self.refresh_page()
        self._after_document_loaded()

    def _after_document_loaded(self):
        """Hook called after a document is successfully loaded."""
        self._form_field_cache = self.doc.form_fields()
        self._xfa_notice_shown = False
        # Auto-select mode based on whether the PDF has fillable widgets
        if self.doc.has_widgets():
            self.btn_fill.setChecked(True)
        else:
            self.btn_stamp.setChecked(True)

    def save_file(self):
        if self.doc is None:
            return
        suggested = self.doc.path
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF", suggested, "PDF Files (*.pdf)"
        )
        if not path:
            return
        self.doc.save(path)
        self.doc.mark_saved()
        self.statusBar().showMessage(f"Saved to {path}")

    def set_mode(self, mode):
        self.mode = mode

    def set_top_mode(self, new_mode):
        self.top_mode = new_mode
        self.text_toolbar.setEnabled(new_mode == "stamp")
        self.canvas.selected_index = -1
        if new_mode == "fill" and self.doc is not None:
            has_widgets = self.doc.has_widgets()
            is_xfa = self.doc.is_xfa()
            if not has_widgets:
                if not self._xfa_notice_shown:
                    if is_xfa:
                        msg = ("This PDF uses XFA (Adobe LiveCycle) forms, which aren't "
                               "supported. Use Stamp mode to add values on top.")
                    else:
                        msg = "This PDF has no fillable form fields. Use Stamp mode."
                    QMessageBox.information(self, "Fill mode", msg)
                    self._xfa_notice_shown = True
                self.btn_stamp.setChecked(True)
                return
            if is_xfa and not self._xfa_notice_shown:
                QMessageBox.information(
                    self, "Fill mode",
                    "This PDF includes XFA content. Fill mode will work with the "
                    "standard fields; XFA-only content can't be filled — use Stamp "
                    "mode for that.",
                )
                self._xfa_notice_shown = True
        self.canvas.update()
        self.update_status()

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

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Image", "",
            "Images (*.png *.gif *.jpg *.jpeg)",
        )
        if path:
            self.image_path = path
            self._add_recent_image(path)
            # Select the newly chosen image in the combo (index 1, after "Choose file...")
            idx = self.image_combo.findData(path, Qt.ItemDataRole.UserRole)
            if idx >= 0:
                self.image_combo.setCurrentIndex(idx)
            # Auto-populate spinboxes from per-image memory
            w, h = self.get_image_size(path)
            self._updating_spinboxes = True
            self.img_width.setValue(int(w))
            self.img_height.setValue(int(h))
            self._updating_spinboxes = False
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
        if self.top_mode == "fill":
            names_on_page = {
                ff.field_name for ff in self._form_field_cache
                if ff.page_num == self.current_page
            }
            filled_names = {f.field_name for f in self.doc.pending_fields()}
            n_fields = len(names_on_page)
            n_filled = len(names_on_page & filled_names)
            self.statusBar().showMessage(
                f"Fill mode — {n_filled}/{n_fields} fields filled on this page"
            )
            return
        n = len(self.doc.pending_annotations())
        sel = ""
        if self.canvas.selected_index >= 0:
            sel = f" | Selected: #{self.canvas.selected_index + 1}"
        self.statusBar().showMessage(f"{n} annotation(s) pending{sel}")


def main():
    app = QApplication(sys.argv)
    initial_path = sys.argv[1] if len(sys.argv) > 1 else None
    window = MainWindow(initial_path=initial_path)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
