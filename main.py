"""
主程序入口 — 系统托盘、仪表盘、桌面面板协调。
启动后：桌面面板自动显示，双击托盘图标打开仪表盘。
"""
import sys
import os

# PyInstaller 打包后以 exe 目录为项目根
if getattr(sys, "frozen", False):
    PROJECT_DIR = os.path.dirname(sys.executable)
else:
    PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from PyQt5.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu,
)
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen
from PyQt5.QtCore import Qt, QTimer

from config import load_config, get_auto_start, set_auto_start
from file_manager import init_folders, get_desktop_path, arrange_desktop_icons
from file_watcher import DesktopWatcher
from panel_manager import PanelManager
from dashboard import Dashboard
from themes import get as _get_theme
import icons


# ── 托盘图标生成 ─────────────────────────────────────────

def _create_tray_icon(colors):
    """文件夹图标，配色取自当前主题。"""
    accent = QColor(colors["accent"])
    hover = QColor(colors["accent_hover"])
    dark = QColor(colors["accent_text"])
    base = QColor("#1b1d22")
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(base)
    painter.drawRoundedRect(2, 2, 60, 60, 15, 15)
    painter.setBrush(hover)
    painter.drawRoundedRect(16, 17, 19, 10, 3, 3)
    painter.setBrush(accent)
    painter.drawRoundedRect(12, 23, 40, 27, 6, 6)
    painter.setPen(QPen(dark, 2, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(20, 31, 44, 31)
    painter.drawLine(20, 36, 44, 36)
    painter.end()
    return QIcon(pixmap)


# ── 托盘菜单样式 ─────────────────────────────────────────

TRAY_FONT = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'


def _build_menu_style(colors):
    """按当前主题生成托盘菜单样式表。"""
    return f"""
QMenu {{
    background: {colors["bg_surface"]};
    color: {colors["text_primary"]};
    border: 1px solid {colors["border"]};
    border-radius: 10px;
    padding: 6px;
    font-family: {TRAY_FONT};
}}
QMenu::item {{
    padding: 9px 32px 9px 18px;
    border-radius: 6px;
}}
QMenu::item:selected {{ background: {colors["bg_surface_alt"]}; }}
QMenu::separator {{
    height: 1px;
    background: {colors["border"]};
    margin: 4px 8px;
}}
"""


# ── 主应用 ───────────────────────────────────────────────

class MainApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        # 配置
        self.config = load_config()
        self.desktop_path = get_desktop_path(self.config)

        # 初始化分类文件夹（分类文件夹位于桌面外的存储目录，桌面保持整洁）
        init_folders(self.config)

        # 自动排列桌面图标
        arrange_desktop_icons()

        # 面板管理器
        self.panel_manager = PanelManager(self.config)

        # 仪表盘
        self.dashboard = Dashboard(self.config, self.panel_manager)
        self.dashboard.panels_toggled.connect(self._on_panels_toggled)
        self.dashboard.category_added.connect(self._on_category_changed)
        self.dashboard.category_removed.connect(self._on_category_changed)
        self.dashboard.file_deleted.connect(self._on_file_changed)
        self.dashboard.file_renamed.connect(self._on_file_changed)
        self.dashboard.theme_changed.connect(self._rebuild_tray_ui)

        # 文件监控
        self.watcher = DesktopWatcher(self.desktop_path, self.config)
        self.watcher.refresh_requested.connect(self._on_watcher_refresh)
        self.watcher.start()

        # 托盘
        self._setup_tray()

        # 启动时显示桌面面板
        self.panel_manager.restore_panels()

        # 延迟刷新确保面板初始数据正确
        QTimer.singleShot(1500, self._initial_refresh)

    # ═══════════════════════════════════════════════════════
    # 托盘
    # ═══════════════════════════════════════════════════════

    def _theme(self):
        return _get_theme(self.config.get("theme"))

    def _setup_tray(self):
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(_create_tray_icon(self._theme()))
        self.tray.setToolTip("桌面文件收纳")

        self._build_tray_menu()

        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _rebuild_tray_ui(self):
        """主题变化后刷新托盘图标与菜单样式。"""
        if hasattr(self, "tray"):
            self.tray.setIcon(_create_tray_icon(self._theme()))
            self._build_tray_menu()

    def _build_tray_menu(self):
        menu = QMenu()
        menu.setStyleSheet(_build_menu_style(self._theme()))

        c = self._theme()

        # 打开仪表盘
        dash_action = menu.addAction("打开仪表盘")
        dash_action.setIcon(icons.dashboard(c["text_secondary"]))
        dash_action.triggered.connect(self._show_dashboard)

        menu.addSeparator()

        # 显示/隐藏桌面面板
        show_action = menu.addAction("显示桌面面板")
        show_action.setIcon(icons.eye(c["text_secondary"]))
        show_action.triggered.connect(self.panel_manager.show_all)

        hide_action = menu.addAction("隐藏桌面面板")
        hide_action.setIcon(icons.eye_off(c["text_secondary"]))
        hide_action.triggered.connect(self.panel_manager.hide_all)

        menu.addSeparator()

        # 新建分类
        new_action = menu.addAction("新建分类")
        new_action.setIcon(icons.plus(c["accent"]))
        new_action.triggered.connect(self._on_new_category_from_tray)

        menu.addSeparator()

        # 开机自启
        self._auto_start_action = menu.addAction("开机自启")
        self._auto_start_action.setCheckable(True)
        self._auto_start_action.setChecked(get_auto_start())
        self._auto_start_action.triggered.connect(self._toggle_auto_start)

        # 刷新所有
        refresh_action = menu.addAction("刷新全部")
        refresh_action.setIcon(icons.refresh(c["text_secondary"]))
        refresh_action.triggered.connect(self._full_refresh)

        menu.addSeparator()

        # 退出
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._on_quit)

        self.tray.setContextMenu(menu)

    def _on_tray_activated(self, reason):
        """双击托盘 → 打开仪表盘。"""
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_dashboard()

    def _show_dashboard(self):
        self.dashboard.show()
        self.dashboard.raise_()
        self.dashboard.activateWindow()
        self.dashboard.refresh_all_data()

    def _on_new_category_from_tray(self):
        """从托盘菜单新建分类 → 打开仪表盘并触发新建。"""
        self._show_dashboard()
        self.dashboard._on_add_category()

    # ═══════════════════════════════════════════════════════
    # 信号处理
    # ═══════════════════════════════════════════════════════

    def _on_panels_toggled(self, visible):
        """仪表盘中切换桌面面板开关。"""
        if visible:
            self.panel_manager.show_all()
        else:
            self.panel_manager.hide_all()

    def _on_category_changed(self, name):
        """分类变更后刷新面板。"""
        self.panel_manager.refresh_all()
        # 重新加载面板管理器中的 categories 引用
        self.panel_manager.config = self.config

    def _on_file_changed(self, name):
        """文件增删后刷新面板。"""
        self.panel_manager.refresh_all()

    def _on_watcher_refresh(self):
        """文件监控发现变化 → 刷新面板和仪表盘。"""
        self.panel_manager.refresh_all()
        if self.dashboard.isVisible():
            self.dashboard.refresh_current()

    def _initial_refresh(self):
        self.panel_manager.refresh_all()
        if self.dashboard.isVisible():
            self.dashboard.refresh_all_data()

    def _full_refresh(self):
        self.panel_manager.refresh_all()
        self.dashboard.refresh_all_data()

    def _toggle_auto_start(self, enabled):
        set_auto_start(enabled)
        self._auto_start_action.setChecked(get_auto_start())

    def _on_quit(self):
        self.watcher.stop()
        self.panel_manager.hide_all()
        self.dashboard.close()
        self.tray.hide()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec_())


def main():
    app = MainApp()
    app.run()


if __name__ == "__main__":
    main()
