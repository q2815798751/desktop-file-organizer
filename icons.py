"""
图标库 — QPainter 手绘矢量线条图标，替换 emoji。

统一风格：16×16 网格、约 1.4px 描边、圆角端点、随主题颜色渲染。
所有图标为线条风格，颜色由调用方传入（取当前主题的强调色/文字色）。
"""
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap, QIcon, QPainterPath

_GRID = 16


def _ln(p, x1, y1, x2, y2):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _render(draw_fn, color, size=16):
    """在 size×size 透明画布上按 16 网格绘制线条图标。"""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.scale(size / _GRID, size / _GRID)
    draw_fn(p)
    p.end()
    return QIcon(pix)


def _folder_path():
    path = QPainterPath()
    path.moveTo(2, 13)
    path.lineTo(2, 5)
    path.lineTo(5, 5)
    path.lineTo(6, 3.2)
    path.lineTo(11, 3.2)
    path.lineTo(12, 5)
    path.lineTo(14, 5)
    path.lineTo(14, 13)
    path.closeSubpath()
    return path


def folder(color, size=16):
    def f(p):
        p.drawPath(_folder_path())
    return _render(f, color, size)


def folder_new(color, size=16):
    def f(p):
        p.drawPath(_folder_path())
        _ln(p, 11.2, 8.2, 11.2, 11.8)
        _ln(p, 9.4, 10, 13, 10)
    return _render(f, color, size)


def doc(color, size=16):
    def f(p):
        path = QPainterPath()
        path.moveTo(4, 2)
        path.lineTo(10, 2)
        path.lineTo(13, 5)
        path.lineTo(13, 14)
        path.lineTo(4, 14)
        path.closeSubpath()
        p.drawPath(path)
        _ln(p, 10, 2, 10, 5)
        _ln(p, 10, 5, 13, 5)
        _ln(p, 6, 9, 11, 9)
        _ln(p, 6, 11.4, 11, 11.4)
    return _render(f, color, size)


def text_doc(color, size=16):
    def f(p):
        p.drawRect(QRectF(4, 2, 8, 12))
        _ln(p, 6, 6, 10, 6)
        _ln(p, 6, 8.5, 10, 8.5)
        _ln(p, 6, 11, 10, 11)
    return _render(f, color, size)


def image(color, size=16):
    def f(p):
        p.drawRect(QRectF(2, 3, 12, 10))
        p.drawEllipse(QPointF(6.5, 6.5), 1.4, 1.4)
        path = QPainterPath()
        path.moveTo(4, 11)
        path.lineTo(7, 7.5)
        path.lineTo(9.5, 10)
        path.lineTo(11.5, 7.5)
        p.drawPath(path)
    return _render(f, color, size)


def archive(color, size=16):
    def f(p):
        p.drawRect(QRectF(3, 5, 10, 8))
        _ln(p, 3, 5, 6, 3)
        _ln(p, 13, 5, 10, 3)
        _ln(p, 6, 3, 10, 3)
        _ln(p, 4.5, 9, 11.5, 9)
    return _render(f, color, size)


def search(color, size=16):
    def f(p):
        p.drawEllipse(QPointF(6.8, 6.8), 3.4, 3.4)
        _ln(p, 9.5, 9.5, 13.5, 13.5)
    return _render(f, color, size)


def settings(color, size=16):
    """设置：三条滑杆 + 控制点。"""
    def f(p):
        _ln(p, 3, 4, 13, 4)
        _ln(p, 3, 8.5, 13, 8.5)
        _ln(p, 3, 13, 13, 13)
        _ln(p, 6, 2.2, 6, 5.8)
        _ln(p, 10.5, 6.7, 10.5, 10.3)
        _ln(p, 5, 11.2, 5, 14.8)
    return _render(f, color, size)


def refresh(color, size=16):
    def f(p):
        p.drawArc(QRectF(3.2, 3.2, 9.6, 9.6), 30 * 16, 280 * 16)
        _ln(p, 11.8, 5, 13.8, 5.2)
        _ln(p, 11.8, 5, 11.6, 3)
    return _render(f, color, size)


def trash(color, size=16):
    def f(p):
        _ln(p, 4, 4, 12, 4)
        _ln(p, 6, 4, 6, 2.2)
        _ln(p, 10, 4, 10, 2.2)
        _ln(p, 6, 2.2, 10, 2.2)
        _ln(p, 5, 6, 5, 12)
        _ln(p, 11, 6, 11, 12)
        _ln(p, 5, 12, 11, 12)
        _ln(p, 7.2, 6, 7.2, 12)
        _ln(p, 9.4, 6, 9.4, 12)
    return _render(f, color, size)


def pencil(color, size=16):
    def f(p):
        _ln(p, 3, 12.5, 10, 5.5)
        _ln(p, 11.5, 4, 13.5, 2)
        _ln(p, 10, 5.5, 11.5, 4)
    return _render(f, color, size)


def dashboard(color, size=16):
    def f(p):
        p.drawRect(QRectF(2, 2, 5, 5))
        p.drawRect(QRectF(9, 2, 5, 5))
        p.drawRect(QRectF(2, 9, 5, 5))
        p.drawRect(QRectF(9, 9, 5, 5))
    return _render(f, color, size)


def eye(color, size=16):
    def f(p):
        p.drawEllipse(QRectF(3, 4.8, 10, 6.4))
        p.drawEllipse(QRectF(6.8, 7, 2.4, 2.4))
    return _render(f, color, size)


def eye_off(color, size=16):
    def f(p):
        p.drawEllipse(QRectF(3, 4.8, 10, 6.4))
        _ln(p, 2.8, 12.5, 13.2, 3.5)
    return _render(f, color, size)


def plus(color, size=16):
    def f(p):
        _ln(p, 8, 3, 8, 13)
        _ln(p, 3, 8, 13, 8)
    return _render(f, color, size)
