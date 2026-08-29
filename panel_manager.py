"""
面板管理器 — 管理所有面板实例的创建、隐藏、状态持久化。

`config["panels"]` 记录哪些分类的面板处于「开启」状态（持久化）：
- 在其中 → 该分类面板开启，启动时会被创建。
- 不在其中 → 关闭，启动时不创建（可从仪表盘每行开关重新打开）。

「运行时可见性」与「开启状态」分离：
- 全局开关 / 托盘 显隐，只隐藏/显示窗口，不改变开启状态（退出不丢面板）。
- 面板 ✕ 或 分类每行开关，才改变开启状态并写盘。
"""
from PyQt5.QtCore import QObject, pyqtSignal
from desktop_panel import DesktopPanel


class PanelManager(QObject):
    """管理所有桌面面板。"""

    # 任一面板显隐/开启状态变化（供仪表盘刷新每行开关文案、全局开关、状态栏）
    panel_state_changed = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.desktop_path = config["desktop_path"]
        self.panels = {}          # category_name -> DesktopPanel（已实体化的面板）
        self._enabled = set()     # 「开启」的分类名（写入 config["panels"]）

    def restore_panels(self):
        """按配置恢复面板。

        用 `config` 中是否含有 `panels` 键来区分「首次启动」与「已被调整过」：
        - 无 `panels` 键（首次/旧配置）：为每个分类开启并创建面板。
        - 有 `panels` 键：仅开启列表中显式保存的分类（关闭过的分类不重建，
          保持关闭，可从仪表盘重新打开）。
        """
        # 先快照原始面板状态：create_panel 会调用 _save_panel_states() 覆写
        # config["panels"]，若在循环里实时读取该键，后续分类会读到被覆写的
        # 占位坐标（100,100）。快照可与覆写解耦，保证读到原始位置。
        saved = self.config.get("panels", [])

        if "panels" not in self.config:
            for i, cat in enumerate(self.config["categories"]):
                self._enabled.add(cat["name"])
                self.create_panel(cat, x=100 + i * 30, y=100 + i * 30)
        else:
            cat_names = {c["name"] for c in self.config["categories"]}
            self._enabled = {p["category"] for p in saved} & cat_names
            for cat in self.config["categories"]:
                if cat["name"] not in self._enabled:
                    continue
                pinfo = next(
                    (p for p in saved if p.get("category") == cat["name"]),
                    None,
                )
                panel = self.create_panel(
                    cat,
                    x=(pinfo["x"] if pinfo else 100),
                    y=(pinfo["y"] if pinfo else 100),
                )
                if pinfo and pinfo.get("collapsed", False) and panel:
                    panel._collapse()

    def create_panel(self, category, x=None, y=None):
        """创建并显示一个面板（并把该分类标记为开启）。"""
        cat_name = category["name"]
        self._enabled.add(cat_name)

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
        self.panel_state_changed.emit()
        return panel

    def remove_panel(self, panel):
        """移除并销毁面板（删除分类等场景用）。"""
        cat_name = panel.panel_id
        if cat_name in self.panels:
            self.panels.pop(cat_name)
        self._enabled.discard(cat_name)
        panel.deleteLater()
        self._save_panel_states()

    def refresh_all(self):
        """刷新所有可见面板的文件列表。"""
        for panel in list(self.panels.values()):
            if panel.isVisible():
                panel.refresh_file_list()

    def show_all(self):
        """全局显示：展示所有「开启」分类的面板（不改变开启状态）。"""
        for cat in self.config["categories"]:
            if cat["name"] not in self._enabled:
                continue
            panel = self.panels.get(cat["name"])
            if panel is None:
                self.create_panel(cat)
            elif not panel.isVisible():
                panel.show()
                panel.refresh_file_list()
        self.panel_state_changed.emit()

    def hide_all(self):
        """全局隐藏：隐藏所有面板窗口（不写盘、不改变开启状态，退出不丢面板）。"""
        for panel in self.panels.values():
            panel.hide()
        self.panel_state_changed.emit()

    def apply_theme(self):
        """主题/字号变化后刷新所有面板。"""
        for panel in self.panels.values():
            panel.apply_theme()

    def set_opacity(self, opacity):
        """设置所有面板的窗口透明度（0~1）。"""
        for panel in self.panels.values():
            panel.setWindowOpacity(opacity)

    # ── 单分类面板显隐（仪表盘每行开关） ──────────────────

    def is_panel_shown(self, cat_name):
        """该分类当前是否有可见面板窗口。"""
        panel = self.panels.get(cat_name)
        return bool(panel and panel.isVisible())

    def any_panel_shown(self):
        """是否至少有一个面板窗口可见。"""
        return any(p.isVisible() for p in self.panels.values())

    def shown_count(self):
        """当前可见的面板数量。"""
        return sum(1 for p in self.panels.values() if p.isVisible())

    def set_panel_visible(self, cat_name, visible):
        """把某分类面板设为显示/隐藏并持久化其开启状态。"""
        cat = self._find_category(cat_name)
        if not cat:
            return

        if visible:
            if cat_name in self.panels:
                panel = self.panels[cat_name]
                if not panel.isVisible():
                    self._enabled.add(cat_name)
                    panel.show()
                    panel.refresh_file_list()
                    self._save_panel_states()
                    self.panel_state_changed.emit()
            else:
                self._enabled.add(cat_name)
                self.create_panel(cat)
        else:
            if (cat_name in self._enabled
                    or (cat_name in self.panels and self.panels[cat_name].isVisible())):
                self._enabled.discard(cat_name)
                panel = self.panels.get(cat_name)
                if panel is not None:
                    panel.hide()
                self._save_panel_states()
                self.panel_state_changed.emit()

    def toggle_panel(self, cat_name):
        """切换某分类面板的显隐（持久化），返回切换后是否显示。"""
        if self.is_panel_shown(cat_name):
            self.set_panel_visible(cat_name, False)
            return False
        self.set_panel_visible(cat_name, True)
        return True

    def add_category(self, name, extensions, folder):
        """添加新分类并创建面板。"""
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
        if category_name in self.panels:
            panel = self.panels.pop(category_name)
            panel.hide()
            panel.deleteLater()
        self._enabled.discard(category_name)

        self.config["categories"] = [
            c for c in self.config["categories"] if c["name"] != category_name
        ]
        self._save_panel_states()
        self.panel_state_changed.emit()

    def rename_category(self, old_name, new_name):
        """分类改名后同步面板键与开启状态，避免重启后产生重复面板。"""
        if old_name in self.panels:
            panel = self.panels.pop(old_name)
            panel.panel_id = new_name
            self.panels[new_name] = panel
        if old_name in self._enabled:
            self._enabled.discard(old_name)
            self._enabled.add(new_name)
        self._save_panel_states()
        self.panel_state_changed.emit()

    # ── 内部 ─────────────────────────────────────────────

    def _find_category(self, name):
        for cat in self.config["categories"]:
            if cat["name"] == name:
                return cat
        return None

    def _on_panel_closed(self, panel):
        """面板点 ✕ 关闭 → 关闭该分类的开启状态（持久化），可从仪表盘重新打开。"""
        self._enabled.discard(panel.panel_id)
        panel.hide()
        self._save_panel_states()
        self.panel_state_changed.emit()

    def _on_panel_moved(self, panel, x, y):
        self._save_panel_states()

    def _save_panel_states(self):
        """把「开启」状态写入 config（不依赖运行时可见性，退出/隐藏不丢面板）。"""
        panels_state = []
        seen = set()
        for cat in self.config["categories"]:
            name = cat["name"]
            if name not in self._enabled or name in seen:
                continue
            seen.add(name)
            panel = self.panels.get(name)
            if panel is not None:
                panels_state.append({
                    "category": name,
                    "x": panel.x(),
                    "y": panel.y(),
                    "collapsed": panel.is_collapsed,
                })
            else:
                panels_state.append({"category": name, "x": 100, "y": 100, "collapsed": False})
        # 兜底：_enabled 里不在 categories 中的名字（理论上不存在）
        for name in self._enabled:
            if name in seen:
                continue
            panel = self.panels.get(name)
            panels_state.append({
                "category": name,
                "x": panel.x() if panel is not None else 100,
                "y": panel.y() if panel is not None else 100,
                "collapsed": panel.is_collapsed if panel is not None else False,
            })
        self.config["panels"] = panels_state

        from config import save_config
        save_config(self.config)
