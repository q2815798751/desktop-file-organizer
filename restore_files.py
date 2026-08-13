"""
恢复脚本 — 将存储目录中分类文件夹的文件移回桌面。
在需要还原文件时运行此脚本。
"""
import json
import os
import shutil

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")

DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")
CATEGORY_FOLDERS = [
    "办公文件", "压缩包", "文本文件", "图片", "其他"
]


def _storage_root():
    """读取 config.json 里的存储根目录，缺省 Documents\\桌面文件收纳。"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        root = cfg.get("storage_path", "")
        if root:
            return root
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents", "桌面文件收纳")


def restore():
    count = 0
    root = _storage_root()
    print(f"从存储目录恢复: {root}\n")
    for folder_name in CATEGORY_FOLDERS:
        folder_path = os.path.join(root, folder_name)
        if not os.path.isdir(folder_path):
            print(f"  跳过（不存在）: {folder_name}")
            continue

        for entry in os.listdir(folder_path):
            src = os.path.join(folder_path, entry)
            if not os.path.isfile(src):
                continue
            dest = os.path.join(DESKTOP, entry)
            # 处理冲突
            if os.path.exists(dest):
                name, ext = os.path.splitext(entry)
                counter = 1
                while True:
                    new_name = f"{name}_restored({counter}){ext}"
                    dest = os.path.join(DESKTOP, new_name)
                    if not os.path.exists(dest):
                        break
                    counter += 1
            try:
                shutil.move(src, dest)
                print(f"  已恢复: {entry}")
                count += 1
            except OSError as e:
                print(f"  失败: {entry} - {e}")

    print(f"\n共恢复 {count} 个文件到桌面。")


if __name__ == "__main__":
    print("正在将文件从存储目录移回桌面...\n")
    restore()
