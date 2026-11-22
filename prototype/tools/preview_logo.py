"""渲染 Logo 预览图：标志在深 / 浅背景上的大图，以及应用图标在 256 / 64 / 32 / 16 像素下的效果。

用法：python -I tools/preview_logo.py <prototype 目录> <输出 png>
"""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

root = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
app = QGuiApplication(sys.argv)

logo = QSvgRenderer(str(root / "assets" / "logo.svg"))
icon = QSvgRenderer(str(root / "assets" / "icon.svg"))
assert logo.isValid() and icon.isValid()

W, H = 1040, 600
img = QImage(W, H, QImage.Format_ARGB32)
img.fill(QColor("#1F1922"))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)

# 标志：深色（幕布）与浅色背景
p.fillRect(QRectF(20, 20, 320, 320), QColor("#141016"))
logo.render(p, QRectF(40, 40, 280, 280))
p.fillRect(QRectF(360, 20, 320, 320), QColor("#F3EDE6"))
logo.render(p, QRectF(380, 40, 280, 280))
p.fillRect(QRectF(700, 20, 320, 320), QColor("#FFFFFF"))
icon.render(p, QRectF(740, 60, 240, 240))

# 应用图标在实际尺寸下（先渲染到对应尺寸的位图，再原样贴出，模拟真实像素）
x = 40
for size in (256, 64, 32, 16):
    small = QImage(size, size, QImage.Format_ARGB32)
    small.fill(Qt.transparent)
    sp = QPainter(small)
    sp.setRenderHint(QPainter.Antialiasing)
    icon.render(sp, QRectF(0, 0, size, size))
    sp.end()
    # 深色任务栏与浅色任务栏
    p.fillRect(QRectF(x - 10, 360, size + 20, 110), QColor("#202020"))
    p.drawImage(x, 365 + (100 - min(size, 100)) // 2, small.scaled(min(size, 100), min(size, 100), Qt.KeepAspectRatio, Qt.SmoothTransformation) if size > 100 else small)
    p.fillRect(QRectF(x - 10, 480, size + 20, 110), QColor("#F3F3F3"))
    p.drawImage(x, 485 + (100 - min(size, 100)) // 2, small.scaled(min(size, 100), min(size, 100), Qt.KeepAspectRatio, Qt.SmoothTransformation) if size > 100 else small)
    x += min(size, 100) + 60
p.end()
print("saved", img.save(str(out)))
