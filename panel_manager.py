"""
面板管理器 — 管理所有面板实例的创建、销毁、状态持久化。
"""
from PyQt5.QtCore import QObject
from desktop_panel import DesktopPanel


class PanelManager(QObject):
    """管理所有桌面面板。"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.desktop_path = config["desktop_path"]
        self.panels = {}  # category_name -> DesktopPanel

    def restore_panels(self):
        """根据配置恢复面板。"""
        saved_panels = self.config.get("panels", [])

        if not saved_panels:
            # 首次启动：为每个分类创建面板
            for i, cat in enumerate(self.config["categories"]):
                self.create_panel(cat, x=100 + i * 30, y=100 + i * 30)
        else:
            for pinfo in saved_panels:
                cat_name = pinfo.get("category")
                cat = self._find_category(cat_name)
                if cat:
                    panel = self.create_panel(
                        cat,
                        x=pinfo.get("x", 100),
                        y=pinfo.get("y", 100),
                    )
                    if pinfo.get("collapsed", False) and panel:
                        panel._collapse()

    def create_panel(self, category, x=None, y=None):
        """创建并显示一个面板。"""
        cat_name = category["name"]

        # 避免重复创建
        if cat_name in self.panels:
            existing = self.panels[cat_name]
            if not existing.isVisible():
                existing.show()
                existing.refresh_file_list()
            return existing

        panel = DesktopPanel(category, self.config, panel_manager=self, panel_id=cat_name)
        panel.panel_closed.connect(self._on_panel_closed)
        panel.position_changed.connect(self._on_panel_moved)

        if x is not None and y is not None:
            panel.show_at(x, y)
        else:
            panel.show()
            panel.resize(300, 350)

        self.panels[cat_name] = panel
        self._save_panel_states()
        return panel

    def remove_panel(self, panel):
        """移除面板。"""
        cat_name = panel.category["name"]
        if cat_name in self.panels:
            self.panels.pop(cat_name)
        panel.deleteLater()
        self._save_panel_states()

    def refresh_all(self):
        """刷新所有面板的文件列表。"""
        for panel in list(self.panels.values()):
            if panel.isVisible():
                panel.refresh_file_list()

    def show_all(self):
        for panel in self.panels.values():
            panel.show()

    def hide_all(self):
        for panel in self.panels.values():
            panel.hide()

    def apply_theme(self):
        """主题/字号变化后刷新所有面板。"""
        for panel in self.panels.values():
            panel.apply_theme()

    def set_opacity(self, opacity):
        """设置所有面板的窗口透明度（0~1）。"""
        for panel in self.panels.values():
            panel.setWindowOpacity(opacity)

    def add_category(self, name, extensions, folder):
        """添加新分类并创建面板。"""
        # 检查是否已存在
        for cat in self.config["categories"]:
            if cat["name"] == name:
                return self.create_panel(cat)

        new_cat = {
            "name": name,
            "extensions": extensions,
            "folder": folder or name,
        }
        self.config["categories"].append(new_cat)

        from config import save_config
        save_config(self.config)

        # 创建文件夹并把桌面上已有的匹配文件移入
        from file_manager import get_category_folder, _move_matching_files
        folder_path = get_category_folder(self.config, new_cat)
        import os
        os.makedirs(folder_path, exist_ok=True)
        _move_matching_files(self.desktop_path, folder_path, extensions)

        return self.create_panel(new_cat)

    def remove_category(self, category_name):
        """删除分类及对应面板。"""
        # 关闭面板
        if category_name in self.panels:
            panel = self.panels.pop(category_name)
            panel.hide()
            panel.deleteLater()

        # 从配置中移除
        self.config["categories"] = [
            c for c in self.config["categories"] if c["name"] != category_name
        ]
        self._save_panel_states()

    def rename_category(self, old_name, new_name):
        """分类改名后同步面板键，避免重启后产生重复面板。"""
        if old_name in self.panels:
            panel = self.panels.pop(old_name)
            panel.panel_id = new_name
            self.panels[new_name] = panel
        self._save_panel_states()

    # ── 内部 ─────────────────────────────────────────────

    def _find_category(self, name):
        for cat in self.config["categories"]:
            if cat["name"] == name:
                return cat
        return None

    def _on_panel_closed(self, panel):
        self.remove_panel(panel)

    def _on_panel_moved(self, panel, x, y):
        self._save_panel_states()

    def _save_panel_states(self):
        """将当前面板状态写入 config。"""
        panels_state = []
        for panel in self.panels.values():
            panels_state.append({
                "category": panel.category["name"],
                "x": panel.x(),
                "y": panel.y(),
                "collapsed": panel.is_collapsed,
            })
        self.config["panels"] = panels_state

        from config import save_config
        save_config(self.config)
