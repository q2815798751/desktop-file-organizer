"""
桌面面板组件 — 置底可拖动文件面板（不遮挡其他应用窗口），支持磁贴吸附与编组拖动。
"""
import os
import subprocess

from PyQt5.QtCore import (
    Qt, QPointF, QRect, QRectF, pyqtSignal,
)
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QMenu, QApplication,
)
from PyQt5.QtGui import (
    QColor, QPainter, QPen,
)

from themes import get as _get_theme
import icons

# ── 颜色（由主题模块驱动） ─────────────────────────────────
RADIUS = 10
FONT = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'

BG_COLOR = QColor(28, 30, 35)
BORDER_COLOR = QColor(42, 45, 52)
ACCENT_COLOR = QColor(52, 211, 153)
_TEXT_PRIMARY = "#e8e6e1"
_TEXT_SECONDARY = "#9ba0a9"
_TEXT_MUTED = "#6d7178"
_SURFACE_ALT = "#24272d"
_DANGER = "#f87171"
_DANGER_TEXT = "#261012"
_ACCENT_RGB = "52, 211, 153"


def _set_colors(c):
    global BG_COLOR, BORDER_COLOR, ACCENT_COLOR
    global _TEXT_PRIMARY, _TEXT_SECONDARY, _TEXT_MUTED, _SURFACE_ALT
    global _DANGER, _DANGER_TEXT, _ACCENT_RGB
    BG_COLOR = QColor(*c["panel_bg"])
    BORDER_COLOR = QColor(*c["panel_border"])
    ACCENT_COLOR = QColor(c["accent"])
    _TEXT_PRIMARY = c["text_primary"]
    _TEXT_SECONDARY = c["text_secondary"]
    _TEXT_MUTED = c["text_muted"]
    _SURFACE_ALT = c["bg_surface_alt"]
    _DANGER = c["danger"]
    _DANGER_TEXT = c["danger_text"]
    _ACCENT_RGB = c["accent_rgb"]


_set_colors(_get_theme())  # 默认主题


def _fs(base, scale=1.0):
    """按字号比例缩放。"""
    return max(9, int(base * scale))


def _build_panel_style(font_scale=1.0):
    """按当前主题与字号比例生成面板样式表。"""
    s = font_scale
    return f"""
QWidget {{ font-family: {FONT}; }}

QLabel#TitleLabel {{
    color: {_TEXT_PRIMARY};
    font-size: {_fs(13, s)}px;
    font-weight: 600;
    padding-left: 4px;
}}

QLabel#CountLabel {{
    color: {_TEXT_SECONDARY};
    font-size: {_fs(11, s)}px;
    padding-left: 4px;
}}

QPushButton#CollapseBtn {{
    background: transparent;
    color: {_TEXT_SECONDARY};
    border: none;
    font-size: {_fs(16, s)}px;
    min-width: 24px; max-width: 24px;
    min-height: 24px; max-height: 24px;
    border-radius: 6px;
}}
QPushButton#CollapseBtn:hover {{ background: {_SURFACE_ALT}; color: {_TEXT_PRIMARY}; }}

QPushButton#CloseBtn {{
    background: transparent;
    color: {_DANGER};
    border: none;
    font-size: {_fs(14, s)}px;
    min-width: 24px; max-width: 24px;
    min-height: 24px; max-height: 24px;
    border-radius: 6px;
}}
QPushButton#CloseBtn:hover {{ background: {_DANGER}; color: {_DANGER_TEXT}; }}

QListWidget {{
    background: transparent;
    color: {_TEXT_PRIMARY};
    border: none;
    outline: none;
    font-size: {_fs(12, s)}px;
    padding: 4px;
}}
QListWidget::item {{
    padding: 6px 8px;
    border-radius: 6px;
    margin: 1px 4px;
}}
QListWidget::item:hover {{ background: {_SURFACE_ALT}; }}
QListWidget::item:selected {{ background: rgba({_ACCENT_RGB}, 0.14); color: {_TEXT_PRIMARY}; }}

QPushButton#DragHandle {{
    background: transparent;
    color: {_TEXT_MUTED};
    border: none;
    font-size: {_fs(10, s)}px;
    min-width: 20px; max-width: 20px;
}}
"""


def _rects_touch(a, b, tol=1):
    """两矩形是否共享一条边缘（水平或垂直相邻）。"""
    overlap_x = not (a.right() < b.left() - tol or b.right() < a.left() - tol)
    overlap_y = not (a.bottom() < b.top() - tol or b.bottom() < a.top() - tol)
    edge_x = min(abs(a.right() - b.left()), abs(b.right() - a.left())) <= tol
    edge_y = min(abs(a.bottom() - b.top()), abs(b.bottom() - a.top())) <= tol
    return (overlap_x and edge_y) or (overlap_y and edge_x)


class DesktopPanel(QWidget):
    """桌面图层可拖动文件面板，支持磁贴吸附与编组拖动。"""

    panel_closed = pyqtSignal(object)
    position_changed = pyqtSignal(object, int, int)

    SNAP_THRESHOLD = 14  # 磁吸阈值（像素）

    def __init__(self, category, config, panel_manager=None, panel_id=None):
        super().__init__()
        self.category = category
        self.config = config
        self.panel_manager = panel_manager
        self.panel_id = panel_id or category["name"]
        self._collapsed = False
        self._drag_pos = None
        self._drag_group = None  # 编组拖动：本次拖动的面板组
        self._expanded_height = 0

        # 应用主题配色 + 字号 + 透明度
        _set_colors(_get_theme(config.get("theme")))
        self._font_scale = float(config.get("font_scale", 1.0) or 1.0)

        self._setup_ui()
        self._apply_styles()
        self.setWindowOpacity(float(config.get("panel_opacity", 1.0) or 1.0))
        self._refresh_title_icon()
        self.refresh_file_list()

    # ═══════════════════════════════════════════════════════
    # 绘制
    # ═══════════════════════════════════════════════════════

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect())
        margin = 6
        content_rect = rect.adjusted(margin, margin + 2, -margin, -margin)

        # 阴影（按底色色调着色，避免纯黑）
        for i in range(6):
            alpha = 16 - i * 2
            offset = i + 1
            sr = content_rect.translated(0, offset)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(6, 8, 12, alpha))
            painter.drawRoundedRect(sr, RADIUS, RADIUS)

        # 面板背景
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(BG_COLOR)
        painter.drawRoundedRect(content_rect, RADIUS, RADIUS)

        # 顶部强调色条
        strip = QRectF(content_rect.left() + 2, content_rect.top() + 2,
                       content_rect.width() - 4, 3)
        painter.setPen(Qt.NoPen)
        painter.setBrush(ACCENT_COLOR)
        painter.drawRoundedRect(strip, 2, 2)

        # 标题栏底部分隔线
        line_y = content_rect.top() + 42
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.drawLine(
            QPointF(content_rect.left() + RADIUS, line_y),
            QPointF(content_rect.right() - RADIUS, line_y),
        )
        painter.end()

    # ═══════════════════════════════════════════════════════
    # UI
    # ═══════════════════════════════════════════════════════

    def _setup_ui(self):
        self.setObjectName("DesktopPanel")
        # 置底（WindowStaysOnBottomHint）：面板位于所有普通应用窗口之下，
        # 配合 WA_ShowWithoutActivating（点击不激活抢焦点），不遮挡其他应用。
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
            | Qt.WindowStaysOnBottomHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMinimumWidth(260)
        self.setMaximumWidth(380)
        # 接受从资源管理器拖入的文件/文件夹，实现"拖拽收纳"
        self.setAcceptDrops(True)

        m = 8
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(m, m + 2, m, m)
        self._main_layout.setSpacing(0)

        # ── 标题栏 ──
        self._title_bar = QWidget()
        self._title_bar.setObjectName("TitleBar")
        self._title_bar.setStyleSheet("background: transparent;")
        self._title_bar.setFixedHeight(42)
        tl = QHBoxLayout(self._title_bar)
        tl.setContentsMargins(10, 0, 6, 0)

        dh = QPushButton("⋮⋮")
        dh.setObjectName("DragHandle")
        dh.setCursor(Qt.OpenHandCursor)
        tl.addWidget(dh)

        # 分类图标
        self._title_icon = QLabel()
        self._title_icon.setFixedSize(15, 15)
        tl.addWidget(self._title_icon)

        self._title_label = QLabel(self.category["name"])
        self._title_label.setObjectName("TitleLabel")
        tl.addWidget(self._title_label)

        self._count_label = QLabel("(0)")
        self._count_label.setObjectName("CountLabel")
        tl.addWidget(self._count_label)
        tl.addStretch()

        self._collapse_btn = QPushButton("−")
        self._collapse_btn.setObjectName("CollapseBtn")
        self._collapse_btn.setToolTip("折叠/展开")
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        tl.addWidget(self._collapse_btn)

        cb = QPushButton("✕")
        cb.setObjectName("CloseBtn")
        cb.setToolTip("关闭面板")
        cb.clicked.connect(self._on_close)
        tl.addWidget(cb)

        self._main_layout.addWidget(self._title_bar)

        # ── 内容区 ──
        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(self._content)
        cl.setContentsMargins(4, 4, 4, 8)

        self._file_list = QListWidget()
        self._file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._file_list.doubleClicked.connect(self._on_file_double_click)
        self._file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._file_list.customContextMenuRequested.connect(self._on_context_menu)
        cl.addWidget(self._file_list)

        self._main_layout.addWidget(self._content)

        # 拖动事件
        self._title_bar.mousePressEvent = self._on_title_press
        self._title_bar.mouseMoveEvent = self._on_title_move
        self._title_bar.mouseReleaseEvent = self._on_title_release

    def _apply_styles(self):
        self.setStyleSheet(_build_panel_style(self._font_scale))

    def apply_theme(self):
        """主题/字号变化后重建样式并应用透明度。"""
        _set_colors(_get_theme(self.config.get("theme")))
        self._font_scale = float(self.config.get("font_scale", 1.0) or 1.0)
        self._apply_styles()
        self._refresh_title_icon()
        self.refresh_file_list()  # 重新着色文件行图标
        self.setWindowOpacity(float(self.config.get("panel_opacity", 1.0) or 1.0))

    # ═══════════════════════════════════════════════════════
    # 文件列表
    # ═══════════════════════════════════════════════════════

    def refresh_file_list(self):
        from file_manager import get_files_in_category

        self._file_list.clear()
        files = get_files_in_category(self.config, self.category)

        # 有子类型的分类（如 办公文件）在面板里标注 Word/Excel/PDF
        subtypes = self.category.get("subtypes") or {}
        ext_to_sub = {}
        for sub_name, exts in subtypes.items():
            for e in exts:
                ext_to_sub[e] = sub_name

        for full_path, name, mtime in files:
            time_str = mtime.strftime("%Y-%m-%d %H:%M")
            is_dir = os.path.isdir(full_path)
            ext = os.path.splitext(name)[1].lower().lstrip(".")
            sub_tag = ext_to_sub.get(ext, "")
            if is_dir:
                display = f"{name}\n文件夹 · {time_str}"
                tooltip = f"{name}\n文件夹 · 修改: {time_str}"
            elif sub_tag:
                display = f"{name}\n{sub_tag} · {time_str}"
                tooltip = f"{name}\n{sub_tag} · 修改: {time_str}"
            else:
                display = f"{name}\n{time_str}"
                tooltip = f"{name}\n修改: {time_str}"
            item = QListWidgetItem(display)
            item.setIcon(self._row_icon(full_path, name))
            item.setData(Qt.UserRole, full_path)
            item.setToolTip(tooltip)
            self._file_list.addItem(item)

        if not files:
            empty = QListWidgetItem("暂无文件")
            empty.setFlags(Qt.NoItemFlags)
            empty.setTextAlignment(Qt.AlignCenter)
            empty.setForeground(QColor(_TEXT_MUTED))
            self._file_list.addItem(empty)

        self._count_label.setText(f"({len(files)})")

    def _row_icon(self, full_path, name):
        """按类型返回文件行图标。"""
        if os.path.isdir(full_path):
            return icons.folder(_TEXT_SECONDARY)
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext in ("jpg", "jpeg", "png", "gif", "bmp", "svg", "webp"):
            return icons.image(_TEXT_SECONDARY)
        if ext in ("zip", "rar", "7z", "tar", "gz"):
            return icons.archive(_TEXT_SECONDARY)
        if ext in ("txt", "md", "log"):
            return icons.text_doc(_TEXT_SECONDARY)
        return icons.doc(_TEXT_SECONDARY)

    def _refresh_title_icon(self):
        pm = icons.folder(_TEXT_SECONDARY).pixmap(15, 15)
        self._title_icon.setPixmap(pm)

    # ═══════════════════════════════════════════════════════
    # 拖拽收纳
    # ═══════════════════════════════════════════════════════

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        """把拖入的文件/文件夹移动进本面板的分类。"""
        from file_manager import move_into_category

        moved = 0
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and move_into_category(self.config, self.category, p):
                moved += 1
        if moved:
            self.refresh_file_list()
            if self.panel_manager:
                self.panel_manager.refresh_all()
        event.acceptProposedAction()

    def _on_file_double_click(self, index):
        item = self._file_list.itemFromIndex(index)
        if item:
            fp = item.data(Qt.UserRole)
            if fp and os.path.exists(fp):
                os.startfile(fp)

    def _on_context_menu(self, pos):
        item = self._file_list.itemAt(pos)
        if not item:
            return
        fp = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background:#1e2025;color:{_TEXT_PRIMARY};border:1px solid #2a2d34;
                    border-radius:8px;padding:4px; font-family: {FONT}; }}
            QMenu::item {{ padding:6px 20px;border-radius:4px; }}
            QMenu::item:selected {{ background:{_SURFACE_ALT}; color:{_TEXT_PRIMARY}; }}
        """)
        a1 = menu.addAction("打开文件")
        a1.triggered.connect(lambda: os.startfile(fp))
        a2 = menu.addAction("打开所在文件夹")
        a2.triggered.connect(lambda: subprocess.Popen(["explorer", "/select," + fp]))
        menu.addSeparator()
        a3 = menu.addAction("复制路径")
        a3.triggered.connect(lambda: QApplication.clipboard().setText(fp))
        menu.exec_(self._file_list.mapToGlobal(pos))

    # ═══════════════════════════════════════════════════════
    # 折叠
    # ═══════════════════════════════════════════════════════

    def _toggle_collapse(self):
        if self._collapsed:
            self._expand()
        else:
            self._collapse()

    def _collapse(self):
        if self._collapsed:
            return
        self._collapsed = True
        self._collapse_btn.setText("＋")
        self._collapse_btn.setToolTip("展开")
        self._expanded_height = self.height()
        self._content.setVisible(False)
        self.setFixedHeight(self._title_bar.height() + 18)

    def _expand(self):
        if not self._collapsed:
            return
        self._collapsed = False
        self._collapse_btn.setText("−")
        self._collapse_btn.setToolTip("折叠")
        self._content.setVisible(True)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.resize(self.width(), max(self._expanded_height, 200))

    @property
    def is_collapsed(self):
        return self._collapsed

    # ═══════════════════════════════════════════════════════
    # 拖动 + 磁吸 + 编组
    # ═══════════════════════════════════════════════════════

    def _on_title_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            self._drag_group = self._compute_group()
            self._title_bar.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def _on_title_move(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            target = event.globalPos() - self._drag_pos
            target = self._snap(target)            # 屏幕边缘吸附
            target = self._snap_to_panels(target)  # 磁贴吸附（组外面板）
            delta = target - self.pos()
            self.move(target)
            for other in (self._drag_group or []):
                if other is not self:
                    other.move(other.pos() + delta)
            event.accept()

    def _on_title_release(self, event):
        self._drag_pos = None
        self._drag_group = None
        self._title_bar.setCursor(Qt.ArrowCursor)
        self.position_changed.emit(self, self.x(), self.y())

    def _other_panels(self):
        if self.panel_manager is None:
            return []
        return [p for p in self.panel_manager.panels.values() if p is not self]

    def _compute_group(self):
        """BFS：返回与当前面板边缘相接的面板组（含自身），用于编组拖动。"""
        panels = self._other_panels()
        group = []
        frontier = [self]
        seen = {id(self)}
        while frontier:
            cur = frontier.pop()
            group.append(cur)
            crect = QRect(cur.pos(), cur.size())
            for p in panels:
                if id(p) in seen or not p.isVisible():
                    continue
                if _rects_touch(crect, QRect(p.pos(), p.size()), tol=2):
                    seen.add(id(p))
                    frontier.append(p)
        return group

    def _snap_to_panels(self, pos):
        """磁贴吸附：把候选左上角吸附到组外面板的边缘（多轮迭代处理连锁）。"""
        rect = QRect(pos, self.size())
        group = self._drag_group or [self]
        for _ in range(4):
            moved = False
            for other in self._other_panels():
                if other in group or not other.isVisible():
                    continue
                moved = self._try_snap(rect, QRect(other.pos(), other.size())) or moved
            if not moved:
                break
        return rect.topLeft()

    def _try_snap(self, rect, orect):
        """尝试将 rect 吸附到 orect 的边缘；返回是否发生移动。"""
        t = self.SNAP_THRESHOLD
        moved = False
        # 四边对齐
        if abs(rect.top() - orect.top()) <= t:
            rect.moveTop(orect.top()); moved = True
        if abs(rect.left() - orect.left()) <= t:
            rect.moveLeft(orect.left()); moved = True
        if abs(rect.right() - orect.right()) <= t:
            rect.moveRight(orect.right()); moved = True
        if abs(rect.bottom() - orect.bottom()) <= t:
            rect.moveBottom(orect.bottom()); moved = True
        # 边缘相接（左右成行 / 上下成列）
        if abs(rect.left() - orect.right()) <= t:
            rect.moveLeft(orect.right()); moved = True
        if abs(rect.right() - orect.left()) <= t:
            rect.moveRight(orect.left()); moved = True
        if abs(rect.top() - orect.bottom()) <= t:
            rect.moveTop(orect.bottom()); moved = True
        if abs(rect.bottom() - orect.top()) <= t:
            rect.moveBottom(orect.top()); moved = True
        return moved

    def _snap(self, pos, threshold=15):
        """吸附到屏幕工作区边缘。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return pos
        g = screen.availableGeometry()
        if abs(pos.x() - g.left()) < threshold:
            pos.setX(g.left())
        elif abs(pos.x() + self.width() - g.right()) < threshold:
            pos.setX(g.right() - self.width())
        if abs(pos.y() - g.top()) < threshold:
            pos.setY(g.top())
        return pos

    # ═══════════════════════════════════════════════════════
    # 生命周期
    # ═══════════════════════════════════════════════════════

    def _on_close(self):
        self.hide()
        self.panel_closed.emit(self)

    def show_at(self, x, y, width=300, height=350):
        self.resize(width, height)
        self.move(x, y)
        self.show()

    def closeEvent(self, event):
        super().closeEvent(event)
