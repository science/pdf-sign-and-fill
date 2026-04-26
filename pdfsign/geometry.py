def normalize_bbox(p1: tuple[float, float],
                   p2: tuple[float, float]) -> tuple[float, float, float, float]:
    x1, y1 = p1
    x2, y2 = p2
    x = min(x1, x2)
    y = min(y1, y2)
    w = abs(x2 - x1)
    h = abs(y2 - y1)
    return (x, y, w, h)


def fit_image_to_bbox(img_w: float, img_h: float,
                      bbox_w: float, bbox_h: float) -> tuple[float, float]:
    if img_w <= 0 or img_h <= 0 or bbox_w <= 0 or bbox_h <= 0:
        return (0.0, 0.0)
    scale = min(bbox_w / img_w, bbox_h / img_h)
    return (img_w * scale, img_h * scale)
