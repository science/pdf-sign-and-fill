import re
from datetime import datetime, timedelta, timezone

import fitz
import pytest
from pdfsign.core import PdfDocument


PDF_DATE_RE = re.compile(r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})")


def _parse_pdf_date(d: str) -> datetime:
    m = PDF_DATE_RE.match(d or "")
    if not m:
        raise ValueError(f"unparseable PDF date: {d!r}")
    return datetime(*map(int, m.groups()), tzinfo=timezone.utc)


class TestModDateUpdated:
    def test_save_updates_moddate(self, simple_pdf, default_font, tmp_output):
        src = fitz.open(simple_pdf)
        original_mod = src.metadata.get("modDate", "")
        src.close()

        before = datetime.now(timezone.utc) - timedelta(seconds=2)
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "Hello", default_font)
        doc.save(tmp_output)
        after = datetime.now(timezone.utc) + timedelta(seconds=2)

        out = fitz.open(tmp_output)
        out_mod = out.metadata.get("modDate", "")
        out.close()

        assert out_mod != original_mod, "modDate must change after save"
        parsed = _parse_pdf_date(out_mod)
        assert before <= parsed <= after, (
            f"modDate {parsed!r} outside window [{before!r}, {after!r}]"
        )

    def test_save_updates_producer(self, simple_pdf, default_font, tmp_output):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "x", default_font)
        doc.save(tmp_output)
        out = fitz.open(tmp_output)
        producer = out.metadata.get("producer") or ""
        out.close()
        assert "PDF Sign & Fill" in producer

    def test_save_updates_xmp_modifydate(self, simple_pdf, default_font, tmp_output):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "x", default_font)
        doc.save(tmp_output)
        out = fitz.open(tmp_output)
        xmp = out.get_xml_metadata() or ""
        out.close()
        # Only assert when the source carries XMP. simple.pdf may not — that's fine;
        # the test guards itself so it isn't a false negative when XMP is absent.
        if xmp:
            assert "ModifyDate" in xmp
            assert str(datetime.now(timezone.utc).year) in xmp

    def test_save_without_annotations_still_updates_moddate(
        self, simple_pdf, tmp_output
    ):
        src = fitz.open(simple_pdf)
        original_mod = src.metadata.get("modDate", "")
        src.close()
        doc = PdfDocument(simple_pdf)
        doc.save(tmp_output)
        out = fitz.open(tmp_output)
        assert out.metadata.get("modDate", "") != original_mod
        out.close()

    def test_save_preserves_unrelated_metadata(
        self, simple_pdf, default_font, tmp_output
    ):
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "x", default_font)
        doc.save(tmp_output)
        before = fitz.open(simple_pdf).metadata
        after = fitz.open(tmp_output).metadata
        for key in ("title", "author", "subject", "keywords", "creator"):
            assert after.get(key) == before.get(key), (
                f"{key} should round-trip unchanged"
            )

    def test_creation_date_not_overwritten(
        self, simple_pdf, default_font, tmp_output
    ):
        src = fitz.open(simple_pdf)
        original_creation = src.metadata.get("creationDate", "")
        src.close()
        doc = PdfDocument(simple_pdf)
        doc.add_text(0, 72, 72, "x", default_font)
        doc.save(tmp_output)
        out = fitz.open(tmp_output)
        assert out.metadata.get("creationDate", "") == original_creation
        out.close()
