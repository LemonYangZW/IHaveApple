"""把 prototype/assets/icon.svg 渲染成 packaging/app.ico（多尺寸）。

用法：python packaging/make-icon.py
"""
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "prototype" / "assets" / "icon.svg"
OUT = ROOT / "packaging" / "app.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int, renderer: QSvgRenderer) -> Image.Image:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    buffer = image.constBits().tobytes()
    return Image.frombytes("RGBA", (size, size), buffer, "raw", "BGRA")


def main() -> None:
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        raise SystemExit(f"SVG 无法解析：{SVG}")
    # 大图做底，Pillow 会把各尺寸写进 ICO
    frames = [render(size, renderer) for size in SIZES]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"icon: {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
