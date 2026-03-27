from dataclasses import dataclass, field
import os

import fitz  # PyMuPDF


@dataclass
class Annotation:
    type: str  # "text" or "image"
    page_num: int
    x: float
    y: float
    # Text fields
    text: str = ""
    font_path: str = ""
    font_size: float = 12.0
    color: tuple = (0.0, 0.0, 0.0)
    # Image fields
    image_path: str = ""
    width: float = 0.0
    height: float = 0.0


class PdfDocument:
    def __init__(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(f"PDF not found: {path}")
        self._path = path
        self._doc = fitz.open(path)
        self._annotations: list[Annotation] = []

    def page_count(self) -> int:
        return len(self._doc)

    def page_size(self, page_num: int) -> tuple[float, float]:
        if page_num < 0 or page_num >= len(self._doc):
            raise IndexError(f"Page {page_num} out of range (0-{len(self._doc) - 1})")
        page = self._doc[page_num]
        rect = page.rect
        return (rect.width, rect.height)

    def render_page(self, page_num: int, zoom: float = 1.0) -> bytes:
        if page_num < 0 or page_num >= len(self._doc):
            raise IndexError(f"Page {page_num} out of range (0-{len(self._doc) - 1})")
        page = self._doc[page_num]
        mat = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=mat)
        return pixmap.tobytes("png")

    def add_text(self, page_num: int, x: float, y: float, text: str,
                 font_path: str, font_size: float = 12.0,
                 color: tuple = (0.0, 0.0, 0.0)):
        if page_num < 0 or page_num >= len(self._doc):
            raise IndexError(f"Page {page_num} out of range")
        self._annotations.append(Annotation(
            type="text", page_num=page_num, x=x, y=y,
            text=text, font_path=font_path, font_size=font_size, color=color,
        ))

    def add_image(self, page_num: int, x: float, y: float,
                  image_path: str, width: float, height: float):
        if page_num < 0 or page_num >= len(self._doc):
            raise IndexError(f"Page {page_num} out of range")
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")
        self._annotations.append(Annotation(
            type="image", page_num=page_num, x=x, y=y,
            image_path=image_path, width=width, height=height,
        ))

    def pending_annotations(self) -> list[Annotation]:
        return list(self._annotations)

    def update_annotation(self, index: int, **kwargs):
        if index < 0 or index >= len(self._annotations):
            raise IndexError(f"Annotation {index} out of range (0-{len(self._annotations) - 1})")
        ann = self._annotations[index]
        for key, value in kwargs.items():
            if not hasattr(ann, key):
                raise AttributeError(f"Annotation has no field '{key}'")
            setattr(ann, key, value)

    def remove_annotation(self, index: int):
        if index < 0 or index >= len(self._annotations):
            raise IndexError(f"Annotation {index} out of range (0-{len(self._annotations) - 1})")
        self._annotations.pop(index)

    def undo(self) -> bool:
        if self._annotations:
            self._annotations.pop()
            return True
        return False

    def clear(self):
        self._annotations.clear()

    def save(self, output_path: str):
        # Open a fresh copy so we don't mutate the in-memory doc
        doc = fitz.open(self._path)
        for ann in self._annotations:
            page = doc[ann.page_num]
            if ann.type == "text":
                page.insert_text(
                    point=fitz.Point(ann.x, ann.y),
                    text=ann.text,
                    fontfile=ann.font_path,
                    fontsize=ann.font_size,
                    color=ann.color,
                )
            elif ann.type == "image":
                rect = fitz.Rect(ann.x, ann.y,
                                 ann.x + ann.width, ann.y + ann.height)
                page.insert_image(rect, filename=ann.image_path)
        doc.save(output_path, garbage=4, deflate=True)
        doc.close()
