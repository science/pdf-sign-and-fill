import argparse
import sys

from pdfsign.core import PdfDocument

DEFAULT_FONT = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"


def cmd_info(args):
    doc = PdfDocument(args.input)
    print(f"File: {args.input}")
    print(f"Pages: {doc.page_count()}")
    for i in range(doc.page_count()):
        w, h = doc.page_size(i)
        print(f"  Page {i}: {w:.1f} x {h:.1f} pts ({w/72:.2f} x {h/72:.2f} in)")


def cmd_render(args):
    doc = PdfDocument(args.input)
    data = doc.render_page(args.page, zoom=args.zoom)
    with open(args.output, "wb") as f:
        f.write(data)
    print(f"Rendered page {args.page} at {args.zoom}x zoom -> {args.output}")


def cmd_add_text(args):
    color = tuple(float(c) for c in args.color.split(","))
    doc = PdfDocument(args.input)
    doc.add_text(
        page_num=args.page,
        x=args.x,
        y=args.y,
        text=args.text,
        font_path=args.font or DEFAULT_FONT,
        font_size=args.font_size,
        color=color,
    )
    doc.save(args.output)
    print(f"Added text '{args.text}' on page {args.page} at ({args.x}, {args.y}) -> {args.output}")


def cmd_add_image(args):
    doc = PdfDocument(args.input)
    doc.add_image(
        page_num=args.page,
        x=args.x,
        y=args.y,
        image_path=args.image,
        width=args.width,
        height=args.height,
    )
    doc.save(args.output)
    print(f"Added image on page {args.page} at ({args.x}, {args.y}) {args.width}x{args.height} -> {args.output}")


def parse_color(s):
    """Parse color string like '1,0,0' or '0.5,0.5,0.5' into tuple."""
    parts = s.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Color must be R,G,B with values 0.0-1.0")
    return tuple(float(p) for p in parts)


def main():
    parser = argparse.ArgumentParser(
        prog="pdfsign",
        description="Stamp text and images onto PDFs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # info
    p_info = sub.add_parser("info", help="Show PDF info")
    p_info.add_argument("input", help="Input PDF file")

    # render
    p_render = sub.add_parser("render", help="Render a page as PNG")
    p_render.add_argument("input", help="Input PDF file")
    p_render.add_argument("output", help="Output PNG file")
    p_render.add_argument("--page", type=int, default=0, help="Page number (default: 0)")
    p_render.add_argument("--zoom", type=float, default=1.0, help="Zoom factor (default: 1.0)")

    # add-text
    p_text = sub.add_parser("add-text", help="Add text to a PDF")
    p_text.add_argument("input", help="Input PDF file")
    p_text.add_argument("output", help="Output PDF file")
    p_text.add_argument("--text", required=True, help="Text to add")
    p_text.add_argument("--page", type=int, default=0, help="Page number (default: 0)")
    p_text.add_argument("--x", type=float, required=True, help="X position in PDF points")
    p_text.add_argument("--y", type=float, required=True, help="Y position in PDF points")
    p_text.add_argument("--font", default=None, help=f"Font file path (default: {DEFAULT_FONT})")
    p_text.add_argument("--font-size", type=float, default=12.0, help="Font size (default: 12)")
    p_text.add_argument("--color", default="0,0,0", help="RGB color as R,G,B floats 0-1 (default: 0,0,0)")

    # add-image
    p_img = sub.add_parser("add-image", help="Add image to a PDF")
    p_img.add_argument("input", help="Input PDF file")
    p_img.add_argument("output", help="Output PDF file")
    p_img.add_argument("--image", required=True, help="Image file (PNG/GIF)")
    p_img.add_argument("--page", type=int, default=0, help="Page number (default: 0)")
    p_img.add_argument("--x", type=float, required=True, help="X position in PDF points")
    p_img.add_argument("--y", type=float, required=True, help="Y position in PDF points")
    p_img.add_argument("--width", type=float, required=True, help="Image width in PDF points")
    p_img.add_argument("--height", type=float, required=True, help="Image height in PDF points")

    args = parser.parse_args()
    commands = {
        "info": cmd_info,
        "render": cmd_render,
        "add-text": cmd_add_text,
        "add-image": cmd_add_image,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
