import sys
from datetime import date

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QFont, QColor, QFontDatabase, QKeySequence, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QScrollArea, QWidget, QToolBar,
    QFileDialog, QLabel, QInputDialog, QStatusBar, QPushButton,
    QMessageBox, QRadioButton, QSpinBox,
    QComboBox, QColorDialog,
)

from pdfsign.core import PdfDocument

DEFAULT_TEXT = f"Signed {date.today()}"
ZOOM = 1.5

FONTS = {
    "Liberation Sans": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "Liberation Serif": "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "Liberation Mono": "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "DejaVu Sans": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "DejaVu Serif": "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "DejaVu Sans Mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
}


class PdfCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.base_pixmap = QPixmap()
        self._font_path_to_family = {}  # maps font file path -> Qt family name

    def set_page(self, png_bytes: bytes):
        self.base_pixmap = QPixmap()
        self.base_pixmap.loadFromData(png_bytes)
        self.setFixedSize(self.base_pixmap.size())
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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.base_pixmap)

        doc = self.main_window.doc
        if doc is None:
            painter.end()
            return

        zoom = self.main_window.zoom
        current_page = self.main_window.current_page

        for ann in doc.pending_annotations():
            if ann.page_num != current_page:
                continue
            sx = ann.x * zoom
            sy = ann.y * zoom
            if ann.type == "text":
                font_family = self.qt_family_for(ann.font_path)
                font = QFont(font_family)
                font.setPixelSize(int(ann.font_size * zoom))
                painter.setFont(font)
                r, g, b = ann.color
                painter.setPen(QColor(int(r * 255), int(g * 255), int(b * 255)))
                painter.drawText(int(sx), int(sy), ann.text)
            elif ann.type == "image":
                pixmap = QPixmap(ann.image_path)
                target = QRectF(sx, sy, ann.width * zoom, ann.height * zoom)
                painter.drawPixmap(target.toRect(), pixmap)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        mw = self.main_window
        if mw.doc is None:
            return

        pos = event.position()
        pdf_x = pos.x() / mw.zoom
        pdf_y = pos.y() / mw.zoom

        if mw.mode == "text":
            text, ok = QInputDialog.getText(
                self, "Add Text", "Text:", text=DEFAULT_TEXT,
            )
            if not ok or not text:
                return
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Sign")
        self.doc = None
        self.current_page = 0
        self.zoom = ZOOM
        self.mode = "text"
        self.image_path = ""

        self.text_color = (0.0, 0.0, 0.0)

        # Canvas in scroll area
        self.canvas = PdfCanvas(self)
        # Register all fonts for preview
        for font_path in FONTS.values():
            self.canvas.register_font(font_path)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(False)
        self.setCentralWidget(scroll)

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
        self.image_label = QLabel("No image")
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

        # Status bar
        self.statusBar().showMessage("Open a PDF to begin")

        # Size the window
        self.resize(900, 700)

        # Auto-open file dialog on launch
        self.open_file()

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", "", "PDF Files (*.pdf)"
        )
        if not path:
            return
        self.doc = PdfDocument(path)
        self.current_page = 0
        self.setWindowTitle(f"PDF Sign — {path}")
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

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Image", "",
            "Images (*.png *.gif *.jpg *.jpeg)",
        )
        if path:
            self.image_path = path
            self.image_label.setText(path.split("/")[-1])
            self.radio_image.setChecked(True)

    def undo(self):
        if self.doc and self.doc.undo():
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
            self.canvas.update()
            self.update_status()

    def prev_page(self):
        if self.doc and self.current_page > 0:
            self.current_page -= 1
            self.refresh_page()

    def next_page(self):
        if self.doc and self.current_page < self.doc.page_count() - 1:
            self.current_page += 1
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
        self.statusBar().showMessage(f"{n} annotation(s) pending")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
