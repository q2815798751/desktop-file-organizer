"""
首次安装设置模块 — 首次运行时让用户选择分类存储目录。

首次运行（config.json 未配置 storage_path、尚未初始化）时弹出对话框，
用户可选择任意目录作为分类存储根目录；不做选择时默认「系统文档」下的
"桌面文件收纳"（即 C:\\Users\\<用户名>\\Documents\\桌面文件收纳）。
所选目录写入 config.json 的 storage_path，下次启动不再重复提示。
"""
import os

from PyQt5.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QVBoxLayout,
    QHBoxLayout,
    QDialogButtonBox,
    QMessageBox,
    QStyle,
)

import config
from file_manager import DEFAULT_STORAGE_NAME, get_storage_root


def default_storage_path():
    """系统文档（Documents）下的默认存储目录。"""
    return os.path.join(os.path.expanduser("~"), "Documents", DEFAULT_STORAGE_NAME)


def ensure_storage_path(config_cfg):
    """
    保证 config 已配置 storage_path。

    说明：
    - 已配置 storage_path → 直接返回（正常启动，不弹窗）。
    - 未配置 → 弹「首次安装设置」对话框，让用户选择存储目录；
      * 用户选择目录 → 使用所选目录；
      * 用户取消 / 使用默认 → 使用系统文档默认目录。
      随后把结果写入 config.json，仅此一次。
    """
    if config_cfg.get("storage_path"):
        return

    chosen = None
    dialog = FirstRunSetupDialog()
    if dialog.exec_():
        chosen = dialog.chosen_path()
    if not chosen:
        chosen = default_storage_path()

    config_cfg["storage_path"] = chosen
    config.save_config(config_cfg)


class FirstRunSetupDialog(QDialog):
    """首次安装设置对话框：选择分类存储目录。默认系统文档\桌面文件收纳。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("桌面文件收纳 — 首次安装设置")
        self.setModal(True)
        self._default = default_storage_path()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 16)
        layout.setSpacing(12)

        title = QLabel("选择文件收纳的存储位置")
        font = title.font()
        font.setPointSize(13)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel(
            "文件将按分类存入所选目录（分类文件夹在桌面之外，桌面保持整洁）。\n"
            "不做选择将使用系统文档：%s" % self._default
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #7a7f85;")
        layout.addWidget(desc)

        # 目录选择行：输入框 + 浏览
        row = QHBoxLayout()
        row.setSpacing(8)
        self.path_edit = QLineEdit(self._default)
        self.path_edit.setReadOnly(False)
        browse_btn = QPushButton("浏览…")
        browse_btn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse_btn.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        # 底部按钮：使用默认(系统文档) / 确定 / 取消
        box = QDialogButtonBox()
        default_btn = QPushButton("使用系统文档")
        default_btn.clicked.connect(self._use_default)
        ok_btn = box.button(QDialogButtonBox.Ok)
        if ok_btn is None:
            ok_btn = box.addButton("确定", QDialogButtonBox.AcceptRole)
        cancel_btn = box.button(QDialogButtonBox.Cancel)
        if cancel_btn is None:
            cancel_btn = box.addButton("取消", QDialogButtonBox.RejectRole)
        ok_btn.setText("确定")
        cancel_btn.setText("取消")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(default_btn)
        layout.addWidget(box)

    def _browse(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "选择文件收纳的存储目录", self.path_edit.text().strip()
        )
        if chosen:
            self.path_edit.setText(chosen)

    def _use_default(self):
        self.path_edit.setText(self._default)

    def chosen_path(self):
        """返回用户最终选择的目录；无效则返回空串（调用方回退默认）。"""
        path = self.path_edit.text().strip()
        if not path:
            return ""
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "无法使用该目录", f"目录不可用：\n{path}\n\n{exc}")
            return ""
        return path
