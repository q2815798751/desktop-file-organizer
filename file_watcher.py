"""
文件监控模块 — 使用 watchdog 监控桌面文件变化，防抖处理后触发分类。
"""
import os
import time

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class DesktopWatcher(QObject):
    """监控桌面文件变化，发射信号通知面板刷新。

    线程说明：watchdog 在独立工作线程里分发事件，而本对象（QObject）
    属于 GUI 线程。工作线程里不能直接操作 QTimer，因此工作线程只把
    路径记入 _pending 并通过 file_event 信号（队列投递）回到 GUI 线程，
    由 GUI 线程启动防抖定时器。
    """

    file_categorized = pyqtSignal(str, str)  # (category_name, file_path)
    refresh_requested = pyqtSignal()  # 通知面板刷新列表
    file_event = pyqtSignal(str)  # 内部：工作线程 → GUI 线程

    def __init__(self, desktop_path, config, parent=None):
        super().__init__(parent)
        self.desktop_path = desktop_path
        self.config = config
        self._observer = None
        self._pending = {}  # path -> first_seen_time
        self._debounce_ms = 500

        # 防抖定时器（属于 GUI 线程）
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._process_pending)
        self.file_event.connect(self._schedule_debounce)

    def start(self):
        """启动文件监控。"""
        if self._observer is not None:
            return

        handler = _DesktopEventHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, self.desktop_path, recursive=False)
        self._observer.start()

    def stop(self):
        """停止文件监控。"""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None

    def _on_file_event(self, file_path):
        """（工作线程调用）记录文件变化，排队到 GUI 线程处理。"""
        self._pending[file_path] = time.time()
        self.file_event.emit(file_path)

    def _schedule_debounce(self, _file_path):
        """（GUI 线程调用）重置防抖定时器。"""
        self._debounce_timer.start(self._debounce_ms)

    def _process_pending(self):
        """（GUI 线程调用）分类所有待处理文件。"""
        from file_manager import categorize_file

        pending = list(self._pending)
        self._pending.clear()

        for file_path in pending:
            # 文件可能已被移走或删除
            if not os.path.exists(file_path):
                continue

            cat_name, new_path = categorize_file(file_path, self.config)
            if cat_name:
                self.file_categorized.emit(cat_name, new_path)
                self.refresh_requested.emit()

        # 处理期间又有新事件到达则继续等待一轮
        if self._pending:
            self._debounce_timer.start(self._debounce_ms)


class _DesktopEventHandler(FileSystemEventHandler):
    """watchdog 事件处理器。"""

    def __init__(self, watcher):
        super().__init__()
        self._watcher = watcher

    def on_created(self, event):
        if not event.is_directory:
            self._watcher._on_file_event(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._watcher._on_file_event(event.src_path)

    def on_moved(self, event):
        # 文件从外部移入桌面
        if not event.is_directory:
            self._watcher._on_file_event(event.dest_path)
