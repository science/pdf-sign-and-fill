import pytest

from pdfsign.geometry import fit_image_to_bbox, normalize_bbox


class TestNormalizeBbox:
    @pytest.mark.parametrize("p1,p2", [
        ((10, 20), (50, 80)),   # top-left to bottom-right
        ((50, 80), (10, 20)),   # bottom-right to top-left
        ((50, 20), (10, 80)),   # top-right to bottom-left
        ((10, 80), (50, 20)),   # bottom-left to top-right
    ])
    def test_all_directions_yield_same_rect(self, p1, p2):
        x, y, w, h = normalize_bbox(p1, p2)
        assert (x, y, w, h) == (10, 20, 40, 60)

    def test_zero_size_drag(self):
        assert normalize_bbox((10, 10), (10, 10)) == (10, 10, 0, 0)


class TestFitImageToBbox:
    def test_wide_image_into_tall_bbox_is_width_bound(self):
        # 200x100 image into 100x200 bbox → scale = min(0.5, 2.0) = 0.5
        out_w, out_h = fit_image_to_bbox(200, 100, 100, 200)
        assert out_w == pytest.approx(100)
        assert out_h == pytest.approx(50)

    def test_tall_image_into_wide_bbox_is_height_bound(self):
        # 100x200 image into 200x100 bbox → scale = min(2.0, 0.5) = 0.5
        out_w, out_h = fit_image_to_bbox(100, 200, 200, 100)
        assert out_w == pytest.approx(50)
        assert out_h == pytest.approx(100)

    def test_exact_aspect_match_fills_bbox(self):
        out_w, out_h = fit_image_to_bbox(100, 50, 200, 100)
        assert out_w == pytest.approx(200)
        assert out_h == pytest.approx(100)

    def test_preserves_aspect_ratio(self):
        out_w, out_h = fit_image_to_bbox(300, 100, 50, 80)
        assert out_w / out_h == pytest.approx(300 / 100, rel=1e-6)

    def test_zero_dim_returns_zero(self):
        assert fit_image_to_bbox(0, 100, 50, 50) == (0.0, 0.0)
        assert fit_image_to_bbox(100, 100, 0, 50) == (0.0, 0.0)
