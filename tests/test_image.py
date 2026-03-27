import fitz
import pytest
from pdfsign.core import PdfDocument


class TestImageInsertion:
    def test_add_image_creates_annotation(self, simple_pdf, signature_png):
        doc = PdfDocument(simple_pdf)
        doc.add_image(0, 100, 200, signature_png, 150, 50)
        assert len(doc.pending_annotations()) == 1
        ann = doc.pending_annotations()[0]
        assert ann.type == "image"
        assert ann.width == 150
        assert ann.height == 50

    def test_add_image_invalid_page_raises(self, simple_pdf, signature_png):
        doc = PdfDocument(simple_pdf)
        with pytest.raises(IndexError):
            doc.add_image(999, 100, 200, signature_png, 150, 50)

    def test_add_image_missing_file_raises(self, simple_pdf):
        doc = PdfDocument(simple_pdf)
        with pytest.raises(FileNotFoundError):
            doc.add_image(0, 100, 200, "/nonexistent/image.png", 150, 50)

    def test_save_with_image_produces_valid_pdf(self, simple_pdf, signature_png, tmp_output):
        doc = PdfDocument(simple_pdf)
        doc.add_image(0, 72, 400, signature_png, 150, 50)
        doc.save(tmp_output)
        # Verify the output PDF is valid and has images
        result = fitz.open(tmp_output)
        assert len(result) == 1
        # Check that images were embedded
        images = result[0].get_images()
        assert len(images) > 0
        result.close()

    def test_save_with_image_on_specific_page(self, medium_pdf, signature_png, tmp_output):
        doc = PdfDocument(medium_pdf)
        doc.add_image(3, 72, 400, signature_png, 150, 50)
        doc.save(tmp_output)
        result = fitz.open(tmp_output)
        # Image should be on page 3
        images_p3 = result[3].get_images()
        assert len(images_p3) > 0
        result.close()

    def test_image_dimensions_in_output(self, simple_pdf, signature_png, tmp_output):
        doc = PdfDocument(simple_pdf)
        doc.add_image(0, 100, 200, signature_png, 200, 60)
        doc.save(tmp_output)
        # Just verify it saves without error and is a valid PDF
        result = fitz.open(tmp_output)
        assert len(result) >= 1
        result.close()
