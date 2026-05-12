from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import NamedTuple
import os
import re

import fitz  # PyMuPDF


SUPPORTED_WIDGET_TYPES = (
    fitz.PDF_WIDGET_TYPE_TEXT,
    fitz.PDF_WIDGET_TYPE_CHECKBOX,
    fitz.PDF_WIDGET_TYPE_RADIOBUTTON,
    fitz.PDF_WIDGET_TYPE_COMBOBOX,
)

PRODUCER_TAG = "PDF Sign & Fill"


def _pdf_date_now() -> str:
    return datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%S+00'00'")


def _replace_or_inject_xmp_tag(xmp: str, tag: str, value: str) -> str:
    pattern = re.compile(rf"<{re.escape(tag)}>[^<]*</{re.escape(tag)}>")
    replacement = f"<{tag}>{value}</{tag}>"
    if pattern.search(xmp):
        return pattern.sub(replacement, xmp)
    return re.sub(
        r"(</rdf:Description>)",
        f"  {replacement}\n    \\1",
        xmp,
        count=1,
    )


class FormField(NamedTuple):
    page_num: int
    field_name: str
    rect: tuple   # (x0, y0, x1, y1)
    value: str    # current/baked-in value
    widget_type: int
    on_state: str  # checkbox/radio export value (e.g. 'Yes', 'Male'); '' for text/combobox
    choices: tuple = ()  # combobox options; () for other types


# Undo action types
@dataclass
class AddAction:
    index: int
    list_name: str = "annotations"


@dataclass
class RemoveAction:
    index: int
    annotation: object  # Annotation or FieldFill
    list_name: str = "annotations"


@dataclass
class UpdateAction:
    index: int
    old_values: dict
    list_name: str = "annotations"


@dataclass
class ClearAction:
    annotations: list


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
    # When set on a text annotation, render as a wrapped textbox with this width
    # (in PDF points). When None, text is drawn at (x, y) as a single line at the
    # baseline. In textbox mode, (x, y) is the rect's top-left instead.
    wrap_width: float | None = None


@dataclass
class FieldFill:
    field_name: str   # fully-qualified AcroForm name, globally unique in the doc
    value: str


class PdfDocument:
    def __init__(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(f"PDF not found: {path}")
        self._path = path
        self._doc = fitz.open(path)
        self._annotations: list[Annotation] = []
        self._fields: list[FieldFill] = []
        self._undo_stack: list = []
        self._saved_at_depth: int = 0
        self._edit_snapshot: dict | None = None
        self._edit_index: int | None = None

    @property
    def path(self) -> str:
        return self._path

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
                 color: tuple = (0.0, 0.0, 0.0), *,
                 wrap_width: float | None = None):
        if page_num < 0 or page_num >= len(self._doc):
            raise IndexError(f"Page {page_num} out of range")
        self._annotations.append(Annotation(
            type="text", page_num=page_num, x=x, y=y,
            text=text, font_path=font_path, font_size=font_size, color=color,
            wrap_width=wrap_width,
        ))
        self._undo_stack.append(AddAction(len(self._annotations) - 1))

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
        self._undo_stack.append(AddAction(len(self._annotations) - 1))

    def pending_annotations(self) -> list[Annotation]:
        return list(self._annotations)

    def pending_fields(self) -> list[FieldFill]:
        return list(self._fields)

    def has_widgets(self) -> bool:
        return any(list(page.widgets() or []) for page in self._doc)

    def is_xfa(self) -> bool:
        try:
            root_xref = self._doc.pdf_catalog()
            val = self._doc.xref_get_key(root_xref, "AcroForm")
        except Exception:
            return False
        return val is not None and val[0] == "dict" and "/XFA" in val[1]

    def form_fields(self) -> list[FormField]:
        """Enumerate fillable widgets (text, checkbox, radio).

        For radios, each member of the group appears as a separate FormField
        entry sharing the same field_name but with a distinct rect and on_state.
        """
        out = []
        for page_num, page in enumerate(self._doc):
            for w in (page.widgets() or []):
                if w.field_type not in SUPPORTED_WIDGET_TYPES:
                    continue
                r = w.rect
                on_state = ""
                choices: tuple = ()
                if w.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                    try:
                        on_state = w.on_state() or ""
                    except Exception:
                        on_state = ""
                    if on_state is True:  # PyMuPDF returns True for not-yet-saved radios
                        on_state = ""
                elif w.field_type == fitz.PDF_WIDGET_TYPE_COMBOBOX:
                    choices = tuple(w.choice_values or ())
                out.append(FormField(
                    page_num=page_num,
                    field_name=w.field_name,
                    rect=(r.x0, r.y0, r.x1, r.y1),
                    value=w.field_value or "",
                    widget_type=w.field_type,
                    on_state=on_state,
                    choices=choices,
                ))
        return out

    def fill_field(self, field_name: str, value: str):
        """Fill a form field by name. Empty value forces the widget blank on save,
        overriding any default value baked into the source PDF."""
        existing_idx = next(
            (i for i, f in enumerate(self._fields) if f.field_name == field_name),
            None,
        )
        if existing_idx is not None:
            old = self._fields[existing_idx].value
            if old == value:
                return
            self._undo_stack.append(
                UpdateAction(existing_idx, {"value": old}, list_name="fields")
            )
            self._fields[existing_idx].value = value
        else:
            self._fields.append(FieldFill(field_name=field_name, value=value))
            self._undo_stack.append(AddAction(len(self._fields) - 1, list_name="fields"))

    def begin_edit(self, index: int):
        """Snapshot annotation state before a drag/resize series."""
        if index < 0 or index >= len(self._annotations):
            raise IndexError(f"Annotation {index} out of range (0-{len(self._annotations) - 1})")
        # Auto-commit any uncommitted previous edit
        if self._edit_snapshot is not None:
            self.commit_edit()
        self._edit_index = index
        self._edit_snapshot = vars(self._annotations[index]).copy()

    def commit_edit(self):
        """Push an UpdateAction if the annotation changed since begin_edit."""
        if self._edit_snapshot is None:
            return
        index = self._edit_index
        ann = self._annotations[index]
        current = vars(ann)
        if current != self._edit_snapshot:
            self._undo_stack.append(UpdateAction(index, self._edit_snapshot))
        self._edit_snapshot = None
        self._edit_index = None

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
        annotation = self._annotations.pop(index)
        self._undo_stack.append(RemoveAction(index, annotation))

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        action = self._undo_stack.pop()
        if isinstance(action, ClearAction):
            self._annotations = list(action.annotations)
            return True
        target = self._fields if getattr(action, "list_name", "annotations") == "fields" else self._annotations
        if isinstance(action, AddAction):
            target.pop(action.index)
        elif isinstance(action, RemoveAction):
            target.insert(action.index, action.annotation)
        elif isinstance(action, UpdateAction):
            item = target[action.index]
            for key, value in action.old_values.items():
                setattr(item, key, value)
        return True

    def clear(self):
        if self._annotations:
            self._undo_stack.append(ClearAction(list(self._annotations)))
        self._annotations.clear()

    @property
    def is_dirty(self) -> bool:
        return len(self._undo_stack) != self._saved_at_depth

    def mark_saved(self):
        self._saved_at_depth = len(self._undo_stack)

    def save(self, output_path: str):
        # Open a fresh copy so we don't mutate the in-memory doc
        doc = fitz.open(self._path)
        for ann in self._annotations:
            page = doc[ann.page_num]
            if ann.type == "text":
                if ann.wrap_width is None:
                    page.insert_text(
                        point=fitz.Point(ann.x, ann.y),
                        text=ann.text,
                        fontfile=ann.font_path,
                        fontsize=ann.font_size,
                        color=ann.color,
                    )
                else:
                    rect = fitz.Rect(
                        ann.x, ann.y,
                        ann.x + ann.wrap_width, page.rect.height,
                    )
                    page.insert_textbox(
                        rect, ann.text,
                        fontfile=ann.font_path,
                        fontsize=ann.font_size,
                        color=ann.color,
                        align=fitz.TEXT_ALIGN_LEFT,
                    )
            elif ann.type == "image":
                rect = fitz.Rect(ann.x, ann.y,
                                 ann.x + ann.width, ann.y + ann.height)
                page.insert_image(rect, filename=ann.image_path)
        if self._fields:
            pending_by_name = {f.field_name: f.value for f in self._fields}
            radio_parent_xrefs: set[int] = set()
            for page in doc:
                for w in (page.widgets() or []):
                    if w.field_type not in SUPPORTED_WIDGET_TYPES:
                        continue
                    if w.field_name not in pending_by_name:
                        continue
                    new_value = pending_by_name[w.field_name]
                    if w.field_type == fitz.PDF_WIDGET_TYPE_TEXT and new_value == "":
                        # PyMuPDF's update() silently ignores empty values for text,
                        # leaving any baked-in default in /V. Clear /V and /AP directly.
                        doc.xref_set_key(w.xref, "V", "()")
                        doc.xref_set_key(w.xref, "AP", "null")
                    elif w.field_type == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                        # Each child radio's /AS must name its on_state when selected,
                        # /Off otherwise. The parent's /V is set once after the loop.
                        try:
                            this_on = w.on_state() or ""
                        except Exception:
                            this_on = ""
                        if this_on == new_value:
                            doc.xref_set_key(w.xref, "AS", f"/{new_value}")
                        else:
                            doc.xref_set_key(w.xref, "AS", "/Off")
                        # Remember parent xref so we can write /V after the loop
                        ptype, pval = doc.xref_get_key(w.xref, "Parent")
                        if ptype == "xref":
                            radio_parent_xrefs.add((int(pval.split()[0]), new_value))
                    else:
                        w.field_value = new_value
                        w.update()
            for parent_xref, value in radio_parent_xrefs:
                doc.xref_set_key(parent_xref, "V", f"/{value}")
        now_pdf = _pdf_date_now()
        meta = doc.metadata or {}
        meta["modDate"] = now_pdf
        meta["producer"] = PRODUCER_TAG
        doc.set_metadata(meta)
        xmp = doc.get_xml_metadata()
        if xmp:
            iso_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            xmp = _replace_or_inject_xmp_tag(xmp, "xmp:ModifyDate", iso_now)
            xmp = _replace_or_inject_xmp_tag(xmp, "xmp:MetadataDate", iso_now)
            xmp = _replace_or_inject_xmp_tag(xmp, "pdf:Producer", PRODUCER_TAG)
            doc.set_xml_metadata(xmp)
        same_file = (
            os.path.exists(output_path)
            and os.path.samefile(output_path, self._path)
        )
        if same_file:
            # PyMuPDF refuses non-incremental save back to the open path. Write
            # to a sibling temp file then atomically replace, preserving the
            # full-rewrite + garbage-collection semantics.
            tmp_path = output_path + ".tmp"
            try:
                doc.save(tmp_path, garbage=4, deflate=True)
                doc.close()
                os.replace(tmp_path, output_path)
            except Exception:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise
        else:
            doc.save(output_path, garbage=4, deflate=True)
            doc.close()
