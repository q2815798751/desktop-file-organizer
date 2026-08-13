"""
仪表盘 — 主管理控制台，提供分类管理、文件增删查、面板切换。
"""
import os
import subprocess

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QLineEdit, QSplitter,
    QMenu, QMessageBox, QInputDialog, QApplication, QComboBox,
    QHeaderView, QTreeWidget, QTreeWidgetItem, QStackedWidget,
    QAbstractItemView, QStatusBar, QMainWindow, QDialog,
    QDialogButtonBox, QSlider,
)

from themes import get as _get_theme
import icons

# ── 颜色（由主题模块驱动） ───────────────────────────────────
RADIUS = 10                   # 容器/表面圆角
RADIUS_SM = 8                 # 紧凑控件圆角
FONT = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'


def _set_colors(c):
    """按主题字典更新仪表盘配色全局变量（引用它们的样式会随之生效）。"""
    global BG_MAIN, BG_SIDEBAR, BG_SURFACE, BG_SURFACE_ALT, BORDER
    global TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED
    global ACCENT, ACCENT_RGB, ACCENT_HOVER, ACCENT_TEXT
    global DANGER, DANGER_HOVER, DANGER_TEXT
    BG_MAIN = c["bg_main"]
    BG_SIDEBAR = c["bg_sidebar"]
    BG_SURFACE = c["bg_surface"]
    BG_SURFACE_ALT = c["bg_surface_alt"]
    BORDER = c["border"]
    TEXT_PRIMARY = c["text_primary"]
    TEXT_SECONDARY = c["text_secondary"]
    TEXT_MUTED = c["text_muted"]
    ACCENT = c["accent"]
    ACCENT_RGB = c["accent_rgb"]
    ACCENT_HOVER = c["accent_hover"]
    ACCENT_TEXT = c["accent_text"]
    DANGER = c["danger"]
    DANGER_HOVER = c["danger_hover"]
    DANGER_TEXT = c["danger_text"]


_set_colors(_get_theme())  # 默认主题

# ── 全局样式 ─────────────────────────────────────────────

def _fs(base, scale=1.0):
    """按字号比例缩放，保留最小可读字号。"""
    return max(9, int(base * scale))


def _build_dashboard_style(font_scale=1.0):
    """按当前主题颜色与字号比例生成仪表盘全局样式表。"""
    s = font_scale

    return f"""
QMainWindow, QWidget#CentralWidget {{
    background: {BG_MAIN};
    font-family: {FONT};
}}

/* ── 侧边栏 ── */
QWidget#Sidebar {{
    background: {BG_SIDEBAR};
    border-right: 1px solid {BORDER};
}}

QLabel#SidebarTitle {{
    color: {TEXT_MUTED};
    font-size: {_fs(11, s)}px;
    font-weight: 600;
    padding: 16px 16px 6px 16px;
}}

QPushButton#CategoryItem {{
    background: transparent;
    color: {TEXT_SECONDARY};
    border: none;
    border-left: 3px solid transparent;
    padding: 9px 14px 9px 13px;
    text-align: left;
    font-size: {_fs(13, s)}px;
}}
QPushButton#CategoryItem:hover {{
    background: {BG_SURFACE_ALT};
    color: {TEXT_PRIMARY};
}}
QPushButton#CategoryItem:checked {{
    background: rgba({ACCENT_RGB}, 0.12);
    color: {ACCENT_HOVER};
    border-left: 3px solid {ACCENT};
    font-weight: 600;
}}

QPushButton#AddCategoryBtn {{
    background: transparent;
    color: {ACCENT};
    border: 1.5px dashed {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 9px;
    margin: 8px 12px;
    font-size: {_fs(12, s)}px;
    font-weight: 600;
}}
QPushButton#AddCategoryBtn:hover {{
    border-color: {ACCENT};
    background: rgba({ACCENT_RGB}, 0.08);
}}
QPushButton#AddCategoryBtn:pressed {{
    background: rgba({ACCENT_RGB}, 0.16);
}}

/* ── 搜索栏 ── */
QLineEdit#SearchBar {{
    background: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 8px 14px;
    font-size: {_fs(13, s)}px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
}}
QLineEdit#SearchBar:focus {{
    border: 1px solid {ACCENT};
}}

/* ── 文件树 ── */
QTreeWidget {{
    background: {BG_MAIN};
    color: {TEXT_PRIMARY};
    border: none;
    outline: none;
    font-size: {_fs(12, s)}px;
}}
QTreeWidget::item {{
    padding: 7px 8px;
    border-radius: {RADIUS_SM}px;
    margin: 1px 6px;
}}
QTreeWidget::item:hover {{
    background: {BG_SURFACE_ALT};
}}
QTreeWidget::item:selected {{
    background: rgba({ACCENT_RGB}, 0.14);
    color: {TEXT_PRIMARY};
}}
QTreeWidget::branch {{
    background: transparent;
}}
QHeaderView::section {{
    background: {BG_SIDEBAR};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 9px 12px;
    font-weight: 600;
    font-size: {_fs(11, s)}px;
}}

/* ── 操作按钮 ── */
QPushButton#ActionBtn {{
    background: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 7px 16px;
    font-size: {_fs(12, s)}px;
}}
QPushButton#ActionBtn:hover {{
    background: {BG_SURFACE_ALT};
    border-color: {TEXT_MUTED};
}}
QPushButton#ActionBtn:pressed {{
    background: {BG_MAIN};
    padding-top: 8px;
}}

QPushButton#DeleteBtn {{
    background: transparent;
    color: {DANGER};
    border: 1px solid {DANGER};
    border-radius: {RADIUS_SM}px;
    padding: 7px 16px;
    font-size: {_fs(12, s)}px;
}}
QPushButton#DeleteBtn:hover {{
    background: {DANGER};
    color: {DANGER_TEXT};
    border-color: {DANGER};
}}
QPushButton#DeleteBtn:pressed {{
    background: {DANGER_HOVER};
}}

QPushButton#PanelToggle {{
    background: {TEXT_MUTED};
    color: {BG_SIDEBAR};
    border: none;
    border-radius: {RADIUS_SM}px;
    padding: 6px 14px;
    font-size: {_fs(12, s)}px;
    font-weight: 600;
}}
QPushButton#PanelToggle:hover {{
    background: {TEXT_SECONDARY};
}}
QPushButton#PanelToggle:checked {{
    background: {ACCENT};
    color: {ACCENT_TEXT};
}}
QPushButton#PanelToggle:checked:hover {{
    background: {ACCENT_HOVER};
}}

QPushButton#SettingsBtn {{
    background: transparent;
    color: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: {RADIUS_SM}px;
    padding: 6px 14px;
    font-size: {_fs(12, s)}px;
    font-weight: 600;
}}
QPushButton#SettingsBtn:hover {{
    background: rgba({ACCENT_RGB}, 0.12);
}}

/* ── 下拉框 ── */
QComboBox {{
    background: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 4px 10px;
    font-size: {_fs(12, s)}px;
}}
QComboBox:hover {{ border-color: {TEXT_MUTED}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_SECONDARY};
}}
QComboBox QAbstractItemView {{
    background: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 4px;
    selection-background-color: {BG_SURFACE_ALT};
    selection-color: {TEXT_PRIMARY};
    outline: none;
}}

/* ── 状态栏 ── */
QStatusBar {{
    background: {BG_SIDEBAR};
    color: {TEXT_SECONDARY};
    border-top: 1px solid {BORDER};
    font-size: {_fs(11, s)}px;
    padding: 4px 12px;
}}

/* ── 弹窗与输入框（QInputDialog / QMessageBox）── */
QInputDialog, QMessageBox {{
    background: {BG_MAIN};
    font-family: {FONT};
}}
QInputDialog QLabel, QMessageBox QLabel {{
    color: {TEXT_PRIMARY};
    font-size: {_fs(12, s)}px;
}}
QInputDialog QLineEdit, QMessageBox QLineEdit {{
    background: {BG_SURFACE}; color: {TEXT_PRIMARY};
    border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
    padding: 6px 10px; font-size: {_fs(12, s)}px;
}}
QInputDialog QLineEdit:focus {{ border-color: {ACCENT}; }}

/* ── 通用按钮（弹窗确认等）── */
QPushButton {{
    background: {BG_SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_SM}px;
    padding: 7px 16px;
    font-size: {_fs(12, s)}px;
}}
QPushButton:hover {{ background: {BG_SURFACE_ALT}; border-color: {TEXT_MUTED}; }}
QPushButton:pressed {{ background: {BG_MAIN}; padding-top: 8px; }}
"""


class _DropTree(QTreeWidget):
    """支持外部文件拖放的文件树（拖入 → 进当前分类）。"""
    on_drop = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        if self.on_drop:
            self.on_drop(paths)
        event.acceptProposedAction()


class _DropLabel(QLabel):
    """支持外部文件拖放的空状态页。"""
    on_drop = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        if self.on_drop:
            self.on_drop(paths)
        event.acceptProposedAction()


class _DropCategoryList(QListWidget):
    """支持外部文件拖放的分类列表（拖到某项 → 进该分类）。"""
    on_drop_category = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        item = self.itemAt(event.pos())
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        if item and self.on_drop_category:
            self.on_drop_category(item.data(Qt.UserRole), paths)
        event.acceptProposedAction()


class Dashboard(QMainWindow):
    """文件管理仪表盘主窗口。"""

    # 信号：通知外部（main）刷新面板等
    panels_toggled = pyqtSignal(bool)
    category_added = pyqtSignal(str)
    category_removed = pyqtSignal(str)
    file_deleted = pyqtSignal(str)       # category_name
    file_renamed = pyqtSignal(str)
    theme_changed = pyqtSignal()         # 主题变化（供托盘等刷新）

    def __init__(self, config, panel_manager):
        super().__init__()
        self.config = config
        self.panel_manager = panel_manager
        self.desktop_path = config["desktop_path"]
        self._current_category = None
        self._current_subtype = None  # 办公文件等分类的内部子类型筛选
        self._all_files_cache = []  # [(full_path, name, mtime, category_name)]

        # 应用当前主题与字号
        self._apply_theme(_get_theme(config.get("theme")))

        self._setup_ui()
        self._load_categories()

        # 默认选中第一个分类
        if self.config["categories"]:
            self._select_category(self.config["categories"][0]["name"])

    # ═══════════════════════════════════════════════════════
    # UI 构建
    # ═══════════════════════════════════════════════════════

    def _setup_ui(self):
        self.setWindowTitle("桌面文件收纳 — 仪表盘")
        self.setMinimumSize(860, 560)
        self.resize(960, 640)
        self.setStyleSheet(_build_dashboard_style(self._font_scale))

        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 顶部搜索栏 ──
        self._search_bar = QLineEdit()
        self._search_bar.setObjectName("SearchBar")
        self._search_bar.setPlaceholderText("搜索文件…")
        self._search_bar.setFixedHeight(40)
        self._search_bar.textChanged.connect(self._on_search)
        search_wrapper = QWidget()
        search_wrapper.setStyleSheet(f"background: {BG_MAIN};")
        sl = QHBoxLayout(search_wrapper)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.addWidget(self._search_bar)

        # 面板开关
        self._panel_toggle_btn = QPushButton("● 桌面面板已开启")
        self._panel_toggle_btn.setObjectName("PanelToggle")
        self._panel_toggle_btn.setCheckable(True)
        self._panel_toggle_btn.setChecked(True)
        self._panel_toggle_btn.clicked.connect(self._toggle_panels)
        sl.addWidget(self._panel_toggle_btn)

        # 设置
        self._settings_btn = QPushButton("设置")
        self._settings_btn.setObjectName("SettingsBtn")
        self._settings_btn.setIconSize(QSize(15, 15))
        self._settings_btn.clicked.connect(self._open_settings)
        sl.addWidget(self._settings_btn)

        main_layout.addWidget(search_wrapper)

        # ── 主体：侧边栏 + 文件区 ──
        splitter = QSplitter(Qt.Horizontal)

        # 左侧边栏
        self._sidebar = QWidget()
        self._sidebar.setObjectName("Sidebar")
        self._sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        lbl = QLabel("分  类")
        lbl.setObjectName("SidebarTitle")
        sidebar_layout.addWidget(lbl)

        self._category_list = _DropCategoryList()
        self._category_list.on_drop_category = self._absorb_drops_to_category
        self._category_list.setStyleSheet(self._category_list_style())
        self._category_list.currentRowChanged.connect(self._on_category_changed)
        self._category_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._category_list.customContextMenuRequested.connect(self._on_category_context_menu)
        sidebar_layout.addWidget(self._category_list, 1)

        self._add_cat_btn = QPushButton("新建分类")
        self._add_cat_btn.setObjectName("AddCategoryBtn")
        self._add_cat_btn.setIconSize(QSize(15, 15))
        self._add_cat_btn.clicked.connect(self._on_add_category)
        sidebar_layout.addWidget(self._add_cat_btn)
        sidebar_layout.addSpacing(8)

        splitter.addWidget(self._sidebar)

        # 右侧文件区
        right = QWidget()
        right.setStyleSheet(f"background: {BG_MAIN};")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 8, 12, 12)

        # 标题行
        header_row = QHBoxLayout()
        self._category_title = QLabel("选择分类")
        self._category_title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: {_fs(20, self._font_scale)}px; font-weight: 700;"
        )
        header_row.addWidget(self._category_title)
        header_row.addStretch()

        # 分类内部子类型筛选（如 办公文件 的 Word/Excel/PDF）
        self._type_filter = QComboBox()
        self._type_filter.setFixedHeight(28)
        self._type_filter.setEnabled(False)
        self._type_filter.currentIndexChanged.connect(self._on_type_filter_changed)
        header_row.addWidget(self._type_filter)

        self._file_count_label = QLabel("")
        self._file_count_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {_fs(12, self._font_scale)}px;"
        )
        header_row.addWidget(self._file_count_label)
        right_layout.addLayout(header_row)

        # 文件列表
        self._file_tree = _DropTree()
        self._file_tree.on_drop = self._absorb_drops_to_current
        self._file_tree.setColumnCount(3)
        self._file_tree.setHeaderLabels(["文件名", "修改时间", "大小"])
        self._file_tree.setRootIsDecorated(False)
        self._file_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._file_tree.setAlternatingRowColors(False)
        self._file_tree.setIndentation(0)
        self._file_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._file_tree.customContextMenuRequested.connect(self._on_file_context_menu)
        self._file_tree.doubleClicked.connect(self._on_file_double_click)
        self._file_tree.header().setStretchLastSection(False)
        self._file_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._file_tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self._file_tree.header().setSectionResizeMode(2, QHeaderView.Fixed)
        self._file_tree.header().resizeSection(1, 160)
        self._file_tree.header().resizeSection(2, 80)

        # 文件区（树 + 空状态页）
        self._file_stack = QStackedWidget()
        self._file_stack.addWidget(self._file_tree)

        self._empty_label = _DropLabel("此分类暂无文件")
        self._empty_label.on_drop = self._absorb_drops_to_current
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: {_fs(13, self._font_scale)}px; padding: 32px;"
        )
        self._file_stack.addWidget(self._empty_label)

        right_layout.addWidget(self._file_stack, 1)

        # 操作按钮行（图标 + 文字，无 emoji）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._open_btn = QPushButton("打开文件")
        self._open_btn.setObjectName("ActionBtn")
        self._open_btn.clicked.connect(self._on_open_selected)
        btn_row.addWidget(self._open_btn)

        self._folder_btn = QPushButton("打开文件夹")
        self._folder_btn.setObjectName("ActionBtn")
        self._folder_btn.clicked.connect(self._on_show_in_folder)
        btn_row.addWidget(self._folder_btn)

        self._rename_btn = QPushButton("重命名")
        self._rename_btn.setObjectName("ActionBtn")
        self._rename_btn.clicked.connect(self._on_rename_file)
        btn_row.addWidget(self._rename_btn)

        self._newfolder_btn = QPushButton("新建文件夹")
        self._newfolder_btn.setObjectName("ActionBtn")
        self._newfolder_btn.clicked.connect(self._on_new_folder)
        btn_row.addWidget(self._newfolder_btn)

        self._delete_btn = QPushButton("删除")
        self._delete_btn.setObjectName("DeleteBtn")
        self._delete_btn.clicked.connect(self._on_delete_files)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.setObjectName("ActionBtn")
        self._refresh_btn.clicked.connect(self.refresh_current)
        btn_row.addWidget(self._refresh_btn)

        for b in (self._open_btn, self._folder_btn, self._rename_btn,
                  self._newfolder_btn, self._delete_btn, self._refresh_btn):
            b.setIconSize(QSize(15, 15))
        self._apply_button_icons()

        right_layout.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, 1)

        # ── 状态栏 ──
        self._status_bar = QStatusBar()
        self._status_bar.setStyleSheet(f"""
            QStatusBar {{
                background: {BG_SIDEBAR};
                color: {TEXT_SECONDARY};
                border-top: 1px solid {BORDER};
                font-size: {_fs(11, self._font_scale)}px;
                padding: 4px 12px;
            }}
        """)
        self.setStatusBar(self._status_bar)
        self._update_status()

    # ═══════════════════════════════════════════════════════
    # 主题 / 设置
    # ═══════════════════════════════════════════════════════

    def _category_list_style(self):
        s = self._font_scale
        return f"""
            QListWidget {{
                background: transparent;
                color: {TEXT_SECONDARY};
                border: none;
                outline: none;
                font-size: {_fs(13, s)}px;
            }}
            QListWidget::item {{
                padding: 10px 14px 10px 13px;
                border-left: 3px solid transparent;
            }}
            QListWidget::item:hover {{ background: {BG_SURFACE_ALT}; color: {TEXT_PRIMARY}; }}
            QListWidget::item:selected {{
                background: rgba({ACCENT_RGB}, 0.12);
                color: {ACCENT_HOVER};
                border-left: 3px solid {ACCENT};
                font-weight: 600;
            }}
        """

    def _apply_theme(self, colors):
        """更新配色全局与字号，并重建已创建控件的样式。"""
        _set_colors(colors)
        self._font_scale = float(self.config.get("font_scale", 1.0) or 1.0)
        if hasattr(self, "_category_list"):
            self._reapply_styles()

    def _apply_button_icons(self):
        """按当前主题颜色设置按钮图标（换主题时刷新）。"""
        if not hasattr(self, "_open_btn"):
            return
        self._open_btn.setIcon(icons.doc(TEXT_SECONDARY))
        self._folder_btn.setIcon(icons.folder(TEXT_SECONDARY))
        self._rename_btn.setIcon(icons.pencil(TEXT_SECONDARY))
        self._newfolder_btn.setIcon(icons.folder_new(TEXT_SECONDARY))
        self._delete_btn.setIcon(icons.trash(DANGER))
        self._refresh_btn.setIcon(icons.refresh(TEXT_SECONDARY))
        if hasattr(self, "_settings_btn"):
            self._settings_btn.setIcon(icons.settings(ACCENT))
        if hasattr(self, "_add_cat_btn"):
            self._add_cat_btn.setIcon(icons.plus(ACCENT))

    def _reapply_styles(self):
        """主题/字号变化后重建所有依赖配色的样式。"""
        s = self._font_scale
        self.setStyleSheet(_build_dashboard_style(s))
        self._category_list.setStyleSheet(self._category_list_style())
        self._category_title.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: {_fs(20, s)}px; font-weight: 700;"
        )
        self._file_count_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {_fs(12, s)}px;"
        )
        self._empty_label.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: {_fs(13, s)}px; padding: 32px;"
        )
        self._status_bar.setStyleSheet(f"""
            QStatusBar {{
                background: {BG_SIDEBAR};
                color: {TEXT_SECONDARY};
                border-top: 1px solid {BORDER};
                font-size: {_fs(11, s)}px;
                padding: 4px 12px;
            }}
        """)
        # 刷新图标颜色（按钮 / 分类 / 文件）
        self._apply_button_icons()
        cur = self._current_category["name"] if self._current_category else None
        self._load_categories()
        if cur:
            self._select_category(cur)

    def _settings_dialog_style(self):
        s = self._font_scale
        return f"""
            QDialog {{ background: {BG_MAIN}; }}
            QLabel {{ color: {TEXT_PRIMARY}; font-size: {_fs(12, s)}px; }}
            QComboBox {{
                background: {BG_SURFACE}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
                padding: 5px 10px; font-size: {_fs(12, s)}px;
            }}
            QComboBox QAbstractItemView {{
                background: {BG_SURFACE}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                selection-background-color: {BG_SURFACE_ALT};
                selection-color: {TEXT_PRIMARY};
            }}
            QSlider::groove:horizontal {{
                height: 4px; background: {BORDER}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px; height: 14px; margin: -5px 0;
                background: {ACCENT}; border-radius: 7px;
            }}
            QPushButton {{
                background: {BG_SURFACE}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
                padding: 7px 16px; font-size: {_fs(12, s)}px;
            }}
            QPushButton:hover {{ background: {BG_SURFACE_ALT}; }}
        """

    def _open_settings(self):
        """设置面板：主题 / 面板透明度 / 字体大小，改动即时生效并持久化。"""
        from themes import THEMES

        dlg = QDialog(self)
        dlg.setWindowTitle("设置")
        dlg.setFixedWidth(360)
        dlg.setStyleSheet(self._settings_dialog_style())

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        layout.addWidget(QLabel("主题"))
        theme_combo = QComboBox()
        for key, t in THEMES.items():
            theme_combo.addItem(t["label"], key)
        cur = self.config.get("theme")
        theme_combo.setCurrentIndex(list(THEMES.keys()).index(cur) if cur in THEMES else 0)
        layout.addWidget(theme_combo)

        layout.addWidget(QLabel("面板透明度"))
        op_slider = QSlider(Qt.Horizontal)
        op_slider.setRange(50, 100)
        op_slider.setValue(int(float(self.config.get("panel_opacity", 1.0)) * 100))
        op_val = QLabel(f"{op_slider.value()}%")
        op_row = QHBoxLayout()
        op_row.addWidget(op_slider, 1)
        op_row.addWidget(op_val)
        layout.addLayout(op_row)

        layout.addWidget(QLabel("字体大小"))
        fs_combo = QComboBox()
        fs_combo.addItem("小", 0.85)
        fs_combo.addItem("中", 1.0)
        fs_combo.addItem("大", 1.15)
        cur_fs = round(float(self.config.get("font_scale", 1.0) or 1.0), 2)
        fs_combo.setCurrentIndex({0.85: 0, 1.0: 1, 1.15: 2}.get(cur_fs, 1))
        layout.addWidget(fs_combo)

        btn_box = QDialogButtonBox()
        close_btn = btn_box.addButton("关闭", QDialogButtonBox.RejectRole)
        close_btn.setObjectName("GhostBtn")
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)

        def on_theme(idx):
            key = theme_combo.itemData(idx)
            self.config["theme"] = key
            self._apply_theme(_get_theme(key))
            self._save_config()
            if self.panel_manager:
                self.panel_manager.apply_theme()
            self.theme_changed.emit()

        def on_opacity(v):
            val = v / 100.0
            op_val.setText(f"{v}%")
            self.config["panel_opacity"] = val
            self._save_config()
            if self.panel_manager:
                self.panel_manager.set_opacity(val)

        def on_font(idx):
            scale = fs_combo.itemData(idx)
            self.config["font_scale"] = scale
            self._apply_theme(_get_theme(self.config.get("theme")))
            self._save_config()
            if self.panel_manager:
                self.panel_manager.apply_theme()

        theme_combo.currentIndexChanged.connect(on_theme)
        op_slider.valueChanged.connect(on_opacity)
        fs_combo.currentIndexChanged.connect(on_font)

        dlg.exec_()

    # ═══════════════════════════════════════════════════════
    # 分类管理
    # ═══════════════════════════════════════════════════════

    def _load_categories(self):
        self._category_list.clear()
        from file_manager import get_files_in_category

        for cat in self.config["categories"]:
            count = len(get_files_in_category(self.config, cat))
            item = QListWidgetItem(f"{cat['name']}  {count}")
            item.setData(Qt.UserRole, cat["name"])
            item.setIcon(icons.folder(TEXT_SECONDARY))
            self._category_list.addItem(item)

    def _select_category(self, name):
        """程序化选中某个分类。"""
        for i in range(self._category_list.count()):
            item = self._category_list.item(i)
            if item.data(Qt.UserRole) == name:
                self._category_list.setCurrentRow(i)
                return

    def _on_category_changed(self, row):
        if row < 0:
            return
        name = self._category_list.item(row).data(Qt.UserRole)
        cat = self._find_category(name)
        if cat:
            self._current_category = cat
            self._category_title.setText(name)
            self._setup_type_filter(cat)
            self._load_files(cat)
            self._update_status()

    def _setup_type_filter(self, cat):
        """按分类的子类型配置填充筛选下拉框。"""
        self._type_filter.blockSignals(True)
        self._type_filter.clear()
        subtypes = cat.get("subtypes") if cat else None
        if subtypes:
            self._type_filter.addItem("全部类型")
            for sub_name in subtypes:
                self._type_filter.addItem(sub_name)
            self._type_filter.setEnabled(True)
        else:
            self._type_filter.addItem("全部类型")
            self._type_filter.setEnabled(False)
        self._current_subtype = None
        self._type_filter.blockSignals(False)

    def _on_type_filter_changed(self, index):
        """子类型筛选变化后刷新文件列表。"""
        if index <= 0 or not self._current_category:
            self._current_subtype = None
        else:
            subtypes = self._current_category.get("subtypes")
            if subtypes:
                keys = list(subtypes.keys())
                if index - 1 < len(keys):
                    self._current_subtype = keys[index - 1]
        self.refresh_current()

    def _on_category_context_menu(self, pos):
        item = self._category_list.itemAt(pos)
        if not item:
            return
        cat_name = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet(self._menu_style())

        edit_action = menu.addAction("编辑分类")
        edit_action.triggered.connect(lambda: self._on_edit_category(cat_name))

        del_action = menu.addAction("删除分类")
        del_action.triggered.connect(lambda: self._on_remove_category(cat_name))

        menu.exec_(self._category_list.mapToGlobal(pos))

    def _on_add_category(self):
        from PyQt5.QtWidgets import QDialog, QFormLayout, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle("新建分类")
        dlg.setFixedSize(360, 220)
        dlg.setStyleSheet(f"""
            QDialog {{ background: {BG_MAIN}; }}
            QLabel {{ color: {TEXT_PRIMARY}; font-size: {_fs(12, self._font_scale)}px; }}
            QLineEdit {{
                background: {BG_SURFACE}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
                padding: 6px 10px; font-size: {_fs(12, self._font_scale)}px;
            }}
            QLineEdit:focus {{ border-color: {ACCENT}; }}
            QPushButton#PrimaryBtn {{
                background: {ACCENT}; color: {ACCENT_TEXT};
                border: none; border-radius: {RADIUS_SM}px;
                padding: 8px 18px; font-weight: 600;
            }}
            QPushButton#PrimaryBtn:hover {{ background: {ACCENT_HOVER}; }}
            QPushButton#GhostBtn {{
                background: transparent; color: {TEXT_SECONDARY};
                border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
                padding: 8px 18px;
            }}
            QPushButton#GhostBtn:hover {{
                background: {BG_SURFACE_ALT}; color: {TEXT_PRIMARY};
            }}
        """)

        layout = QFormLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("例如：代码文件")
        layout.addRow("分类名称：", name_edit)

        ext_edit = QLineEdit()
        ext_edit.setPlaceholderText("例如：py, java, cpp, js")
        layout.addRow("文件扩展名：", ext_edit)

        folder_edit = QLineEdit()
        folder_edit.setPlaceholderText("留空则使用分类名称")
        layout.addRow("子文件夹名：", folder_edit)

        btn_box = QDialogButtonBox()
        create_btn = btn_box.addButton("创建", QDialogButtonBox.AcceptRole)
        cancel_btn = btn_box.addButton("取消", QDialogButtonBox.RejectRole)
        create_btn.setObjectName("PrimaryBtn")
        cancel_btn.setObjectName("GhostBtn")
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        layout.addRow(btn_box)

        if dlg.exec_() == QDialog.Accepted:
            name = name_edit.text().strip()
            extensions = [
                e.strip().lower().lstrip(".")
                for e in ext_edit.text().split(",") if e.strip()
            ]
            folder = folder_edit.text().strip()

            if not name:
                QMessageBox.warning(self, "提示", "请输入分类名称。")
                return
            if not extensions:
                QMessageBox.warning(self, "提示", "请至少输入一个扩展名。")
                return
            if self._find_category(name):
                QMessageBox.warning(self, "提示", f"分类「{name}」已存在。")
                return

            # 添加分类
            new_cat = {"name": name, "extensions": extensions, "folder": folder or name}
            self.config["categories"].append(new_cat)
            self._save_config()

            # 创建文件夹
            from file_manager import get_category_folder, _move_matching_files
            folder_path = get_category_folder(self.config, new_cat)
            os.makedirs(folder_path, exist_ok=True)
            _move_matching_files(self.desktop_path, folder_path, extensions)

            # 刷新 UI
            self._load_categories()
            self._select_category(name)
            self._update_status()

            # 如果面板已开启，创建对应面板
            if self._panel_toggle_btn.isChecked():
                self.panel_manager.add_category(name, extensions, folder)

            self.category_added.emit(name)

    def _on_edit_category(self, cat_name):
        cat = self._find_category(cat_name)
        if not cat:
            return

        new_name, ok = QInputDialog.getText(
            self, "编辑分类", "分类名称：", text=cat["name"]
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()

        # 改名冲突检查（与其它分类重名会导致面板状态损坏）
        other = self._find_category(new_name)
        if other is not None and other is not cat:
            QMessageBox.warning(self, "提示", f"分类「{new_name}」已存在。")
            return

        new_ext, ok2 = QInputDialog.getText(
            self, "编辑分类", "扩展名（逗号分隔）：",
            text=", ".join(cat["extensions"])
        )
        if not ok2:
            return

        new_exts = [
            e.strip().lower().lstrip(".")
            for e in new_ext.split(",") if e.strip()
        ]
        if not new_exts:
            QMessageBox.warning(self, "提示", "请至少保留一个扩展名。")
            return

        old_name = cat["name"]
        cat["name"] = new_name
        cat["extensions"] = new_exts
        self._save_config()

        # 同步面板键，避免改名后重启产生重复面板
        if old_name != new_name:
            self.panel_manager.rename_category(old_name, new_name)

        self._load_categories()
        self._select_category(cat["name"])
        self.refresh_current()

    def _on_remove_category(self, cat_name):
        reply = QMessageBox.question(
            self, "确认删除",
            f"删除分类「{cat_name}」？\n\n"
            f"注意：分类文件夹及其中的文件不会被删除，\n"
            f"但面板配置会被移除。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.config["categories"] = [
            c for c in self.config["categories"] if c["name"] != cat_name
        ]
        self._save_config()

        # 移除面板
        self.panel_manager.remove_category(cat_name)

        self._load_categories()
        if self.config["categories"]:
            self._select_category(self.config["categories"][0]["name"])
        else:
            self._file_tree.clear()
            self._category_title.setText("无分类")
        self._update_status()
        self.category_removed.emit(cat_name)

    # ═══════════════════════════════════════════════════════
    # 文件列表
    # ═══════════════════════════════════════════════════════

    def _load_files(self, category):
        from file_manager import get_files_in_category

        self._file_tree.clear()
        self._all_files_cache = []

        files = get_files_in_category(self.config, category)

        # 应用子类型筛选（如 办公文件 → Word/Excel/PDF）
        if self._current_subtype and category.get("subtypes"):
            sub_exts = category["subtypes"].get(self._current_subtype, [])
            if sub_exts:
                files = [
                    f for f in files
                    if os.path.splitext(f[1])[1].lower().lstrip(".") in sub_exts
                ]

        # 如果没有文件，也尝试从桌面匹配（首次启动时文件可能还在桌面）
        if not files:
            self._file_tree.clear()
            self._file_count_label.setText("0 个文件")
            self._show_empty("此分类暂无文件\n\n把文件放到桌面即可自动归类")
            return

        self._file_stack.setCurrentWidget(self._file_tree)
        for full_path, name, mtime in files:
            is_dir = os.path.isdir(full_path)
            display_name = name
            if is_dir:
                size_str = "文件夹"
            else:
                size_str = self._format_size(os.path.getsize(full_path))
            time_str = mtime.strftime("%Y-%m-%d %H:%M")

            tree_item = QTreeWidgetItem()
            tree_item.setText(0, display_name)
            tree_item.setText(1, time_str)
            tree_item.setText(2, size_str)
            tree_item.setIcon(0, self._type_icon(full_path, name))
            tree_item.setData(0, Qt.UserRole, full_path)
            tree_item.setToolTip(0, f"{display_name}\n路径: {full_path}\n修改: {time_str}")

            self._file_tree.addTopLevelItem(tree_item)
            self._all_files_cache.append(
                (full_path, name, mtime, category["name"])
            )

        self._file_count_label.setText(f"{len(files)} 项")
        self._update_status()

    def _show_empty(self, text):
        """切换到空状态页。"""
        self._empty_label.setText(text)
        self._file_stack.setCurrentWidget(self._empty_label)

    def _on_new_folder(self):
        """在当前分类的存储文件夹里新建子文件夹。"""
        if not self._current_category:
            return
        name, ok = QInputDialog.getText(
            self, "新建文件夹", "文件夹名称：", text="新建文件夹"
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        from file_manager import get_category_folder
        folder = get_category_folder(self.config, self._current_category)
        path = os.path.join(folder, name)
        if os.path.exists(path):
            QMessageBox.warning(self, "提示", f"已存在同名文件夹「{name}」。")
            return
        try:
            os.makedirs(path)
        except OSError as e:
            QMessageBox.critical(self, "错误", f"创建失败：{e}")
            return
        self.refresh_current()
        if self.panel_manager:
            self.panel_manager.refresh_all()

    # ── 拖拽收纳 ──

    def _absorb_drops_to_current(self, paths):
        """把拖入的文件/文件夹收纳到当前分类。"""
        if self._current_category:
            self._absorb_drops(self._current_category, paths)

    def _absorb_drops_to_category(self, cat_name, paths):
        """把拖入的文件/文件夹收纳到指定分类（侧边栏拖放）。"""
        cat = self._find_category(cat_name)
        if cat:
            self._absorb_drops(cat, paths)

    def _absorb_drops(self, category, paths):
        """执行拖拽收纳：把 paths 移入 category 的存储文件夹。"""
        from file_manager import move_into_category

        moved = 0
        for p in paths:
            if p and move_into_category(self.config, category, p):
                moved += 1
        if moved:
            self.refresh_current()
            if self.panel_manager:
                self.panel_manager.refresh_all()

    def refresh_current(self):
        """刷新当前分类的文件列表。"""
        if self._current_category:
            self._load_files(self._current_category)

    def refresh_all_data(self):
        """完全刷新：分类列表 + 文件列表。"""
        self._load_categories()
        if self._current_category:
            self._load_files(self._current_category)
        self._update_status()

    # ═══════════════════════════════════════════════════════
    # 搜索
    # ═══════════════════════════════════════════════════════

    def _on_search(self, text):
        if not text.strip():
            # 恢复当前分类显示
            if self._current_category:
                self._load_files(self._current_category)
            return

        # 在所有文件中搜索
        self._file_tree.clear()
        query = text.lower().strip()

        all_results = []
        for cat in self.config["categories"]:
            from file_manager import get_files_in_category
            files = get_files_in_category(self.config, cat)
            for full_path, name, mtime in files:
                if query in name.lower():
                    all_results.append((full_path, name, mtime, cat["name"]))

        all_results.sort(key=lambda x: x[2], reverse=True)

        for full_path, name, mtime, cat_name in all_results:
            is_dir = os.path.isdir(full_path)
            display_name = name
            if is_dir:
                size_str = "文件夹"
            else:
                size_str = self._format_size(os.path.getsize(full_path))
            time_str = mtime.strftime("%Y-%m-%d %H:%M")

            tree_item = QTreeWidgetItem()
            tree_item.setText(0, display_name)
            tree_item.setText(1, time_str)
            tree_item.setText(2, size_str)
            tree_item.setIcon(0, self._type_icon(full_path, name))
            tree_item.setData(0, Qt.UserRole, full_path)
            tree_item.setToolTip(0, f"{display_name}\n分类: {cat_name}\n修改: {time_str}")
            self._file_tree.addTopLevelItem(tree_item)

        if all_results:
            self._file_stack.setCurrentWidget(self._file_tree)
        else:
            self._show_empty(f"未找到「{query}」相关的文件")
        self._file_count_label.setText(f"搜索到 {len(all_results)} 个文件")

    # ═══════════════════════════════════════════════════════
    # 文件操作
    # ═══════════════════════════════════════════════════════

    def _get_selected_paths(self):
        """获取当前选中的文件路径列表。"""
        paths = []
        for item in self._file_tree.selectedItems():
            fp = item.data(0, Qt.UserRole)
            if fp:
                paths.append(fp)
        return paths

    def _on_open_selected(self):
        for fp in self._get_selected_paths():
            if os.path.exists(fp):
                os.startfile(fp)

    def _on_show_in_folder(self):
        paths = self._get_selected_paths()
        if paths:
            subprocess.Popen(["explorer", "/select," + paths[0]])

    def _on_file_double_click(self, index):
        item = self._file_tree.itemFromIndex(index)
        if item:
            fp = item.data(0, Qt.UserRole)
            if fp and os.path.exists(fp):
                os.startfile(fp)

    def _on_rename_file(self):
        paths = self._get_selected_paths()
        if not paths:
            return
        fp = paths[0]
        old_name = os.path.basename(fp)

        new_name, ok = QInputDialog.getText(
            self, "重命名文件", "新文件名：", text=old_name
        )
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return

        new_name = new_name.strip()
        dir_path = os.path.dirname(fp)
        new_path = os.path.join(dir_path, new_name)

        if os.path.exists(new_path):
            QMessageBox.warning(self, "错误", f"文件「{new_name}」已存在。")
            return

        try:
            os.rename(fp, new_path)
            self.refresh_current()
            self.panel_manager.refresh_all()
            self.file_renamed.emit(self._current_category["name"] if self._current_category else "")
        except OSError as e:
            QMessageBox.critical(self, "错误", f"重命名失败：{e}")

    def _on_delete_files(self):
        paths = self._get_selected_paths()
        if not paths:
            return

        names = "\n".join(f"  • {os.path.basename(p)}" for p in paths)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除以下 {len(paths)} 个文件？\n\n{names}\n\n"
            f"文件将被移入回收站。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        deleted = 0
        for fp in paths:
            try:
                # 移入回收站而非永久删除
                _send_to_recycle_bin(fp)
                deleted += 1
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败：{fp}\n{e}")

        self.refresh_current()
        self.panel_manager.refresh_all()
        if self._current_category:
            self.file_deleted.emit(self._current_category["name"])

    def _on_file_context_menu(self, pos):
        item = self._file_tree.itemAt(pos)
        if not item:
            return
        fp = item.data(0, Qt.UserRole)
        if not fp:
            return

        menu = QMenu(self)
        menu.setStyleSheet(self._menu_style())

        a1 = menu.addAction("打开")
        a1.setIcon(icons.doc(TEXT_SECONDARY))
        a1.triggered.connect(lambda: os.startfile(fp))

        a2 = menu.addAction("打开文件夹")
        a2.setIcon(icons.folder(TEXT_SECONDARY))
        a2.triggered.connect(lambda: subprocess.Popen(["explorer", "/select," + fp]))

        menu.addSeparator()

        a3 = menu.addAction("重命名")
        a3.setIcon(icons.pencil(TEXT_SECONDARY))
        a3.triggered.connect(self._on_rename_file)

        a4 = menu.addAction("删除")
        a4.setIcon(icons.trash(DANGER))
        a4.setStyleSheet(f"color: {DANGER};")
        a4.triggered.connect(self._on_delete_files)

        menu.addSeparator()

        a5 = menu.addAction("复制路径")
        a5.triggered.connect(lambda: QApplication.clipboard().setText(fp))

        menu.exec_(self._file_tree.mapToGlobal(pos))

    # ═══════════════════════════════════════════════════════
    # 面板切换
    # ═══════════════════════════════════════════════════════

    def _toggle_panels(self, checked):
        # 开关配色由 QSS 的 #PanelToggle:checked 控制，这里只改文案
        if checked:
            self.panel_manager.show_all()
            self._panel_toggle_btn.setText("● 桌面面板已开启")
        else:
            self.panel_manager.hide_all()
            self._panel_toggle_btn.setText("○ 桌面面板已关闭")
        self.panels_toggled.emit(checked)

    # ═══════════════════════════════════════════════════════
    # 工具方法
    # ═══════════════════════════════════════════════════════

    def _find_category(self, name):
        for c in self.config["categories"]:
            if c["name"] == name:
                return c
        return None

    def _save_config(self):
        from config import save_config
        save_config(self.config)

    def _update_status(self):
        total_cats = len(self.config["categories"])
        # 统计所有分类文件夹中的文件总数
        actual_total = 0
        for cat in self.config["categories"]:
            from file_manager import get_category_folder
            folder = get_category_folder(self.config, cat)
            if os.path.isdir(folder):
                actual_total += len([
                    f for f in os.listdir(folder)
                    if os.path.isfile(os.path.join(folder, f))
                ])

        panels_on = self._panel_toggle_btn.isChecked()
        self._status_bar.showMessage(
            f"  {total_cats} 个分类 | {actual_total} 个文件 | "
            f"桌面面板: {'● 开启' if panels_on else '○ 关闭'}"
        )

    def _type_icon(self, full_path, name):
        """按文件/文件夹类型返回图标（随主题文字色）。"""
        if os.path.isdir(full_path):
            return icons.folder(TEXT_SECONDARY)
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext in ("jpg", "jpeg", "png", "gif", "bmp", "svg", "webp"):
            return icons.image(TEXT_SECONDARY)
        if ext in ("zip", "rar", "7z", "tar", "gz"):
            return icons.archive(TEXT_SECONDARY)
        if ext in ("txt", "md", "log"):
            return icons.text_doc(TEXT_SECONDARY)
        return icons.doc(TEXT_SECONDARY)

    @staticmethod
    def _format_size(size_bytes):
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    @staticmethod
    def _menu_style():
        return f"""
            QMenu {{ background:{BG_SURFACE}; color:{TEXT_PRIMARY};
                    border:1px solid {BORDER}; border-radius:{RADIUS_SM}px; padding:4px;
                    font-family: {FONT}; }}
            QMenu::item {{ padding: 8px 24px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {BG_SURFACE_ALT}; color: {TEXT_PRIMARY}; }}
            QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
        """

    def closeEvent(self, event):
        """关闭仪表盘时隐藏到托盘而非退出。"""
        self.hide()
        event.ignore()


def _send_to_recycle_bin(file_path):
    """将文件移入 Windows 回收站。"""
    import ctypes
    from ctypes import wintypes

    SHERB_NOCONFIRMATION = 0x00000001
    SHERB_NOPROGRESSUI = 0x00000002
    SHERB_NOSOUND = 0x00000004

    # 需要双终止符
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", wintypes.USHORT),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x40

    shfile = SHFILEOPSTRUCTW()
    shfile.hwnd = None
    shfile.wFunc = FO_DELETE
    shfile.pFrom = file_path + "\0\0"
    shfile.pTo = None
    shfile.fFlags = (
        FOF_ALLOWUNDO
        | SHERB_NOCONFIRMATION
        | SHERB_NOPROGRESSUI
        | SHERB_NOSOUND
    )

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(shfile))
    if result != 0:
        raise OSError(f"SHFileOperation failed with code {result}")
