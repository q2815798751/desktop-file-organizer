"""
文件监控模块 — 使用 watchdog 监控桌面文件变化，防抖处理后触发分类。
"""
import logging
import os
import time

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

logger = logging.getLogger(__name__)


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
        # AW-7：文件仍在写入（大文件还在复制）时的重试上限与计数。每轮重试之间
        # 隔一个防抖周期，超过上限则放弃自动归类、把文件留在桌面（安全优先）。
        self._max_retries = 20
        self._retries = {}  # path -> 已重试次数

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
        from file_manager import (
            ACTION_RETRY,
            categorize_file,
            stability_decision,
            stable_files,
        )

        # 先剔除已消失的文件（否则会被 stable_files 归为「不稳定」而反复重试）
        pending = []
        for file_path in list(self._pending):
            if os.path.exists(file_path):
                pending.append(file_path)
            else:
                self._retries.pop(file_path, None)
        self._pending.clear()

        # AW-7：归类前先确认文件已经写完。旧实现只等 500ms 防抖，大文件正在复制时
        # 会把**半个文件**移走。这里整批间隔采样 os.path.getsize，连续两次相同才归类。
        ready, still_writing = stable_files(pending)

        for file_path in still_writing:
            decision = stability_decision(
                False, self._retries.get(file_path, 0), self._max_retries
            )
            if decision == ACTION_RETRY:
                # 仍在写入 → 记一次重试，稍后（下一个防抖周期）再看
                self._retries[file_path] = self._retries.get(file_path, 0) + 1
                self._pending[file_path] = time.time()
            else:  # ACTION_GIVE_UP：迟迟写不完，放弃自动归类，留在桌面
                self._retries.pop(file_path, None)
                logger.warning(
                    "文件持续变化，放弃自动归类（保留在桌面）：%s", file_path
                )

        for file_path in ready:
            # ready 里的文件都已稳定 → 一定走 ACTION_CATEGORIZE（stability_decision
            # 对 stable=True 恒返回它），这里直接归类并清掉重试计数。
            self._retries.pop(file_path, None)
            cat_name, new_path = categorize_file(file_path, self.config)
            if cat_name:
                self.file_categorized.emit(cat_name, new_path)
                self.refresh_requested.emit()

        # 处理期间又有新事件到达、或有文件仍在写入则继续等待一轮
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
