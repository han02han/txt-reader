"""隐蔽 TXT 阅读器 — 入口模块。

启动流程：
1. 创建 QApplication（设置不随最后窗口关闭而退出）
2. 单实例检查：如已有实例运行则通知其显示窗口并退出；否则成为主实例
3. 创建阅读器窗口 + 系统托盘
4. 连接信号，进入事件循环
"""

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QThread
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from reader_window import ReaderWindow
from tray_manager import TrayManager

# 单实例锁的服务名（同一台机器上唯一标识本应用）
_SERVER_NAME = "fuguo_txt_reader"
# Windows 命名互斥锁名字（内核原语，跨进程原子互斥）
_MUTEX_NAME = "fuguo_txt_reader_mutex"
# 全局持有互斥锁句柄，防止被 GC 释放导致锁失效
_MUTEX_HANDLE: int | None = None


class App:
    """应用主控制器，组装窗口和托盘。"""

    def __init__(self, instance_server: QLocalServer):
        self._window = ReaderWindow()
        self._tray = TrayManager()

        # 监听来自后续实例的"显示窗口"请求（单实例互斥由 main 里的内核互斥量保证）
        self._instance_server = instance_server
        self._instance_server.newConnection.connect(self._on_show_request)

        self._connect_signals()
        self._tray.show()

        # 如果恢复了上次的文件，显示窗口
        if self._window._file_path is not None:
            self._window.show()

    def _connect_signals(self) -> None:
        """连接窗口与托盘的信号。"""
        # 窗口关闭 → 隐藏到托盘
        self._window.hide_requested.connect(self._on_window_hidden)

        # 窗口可见性变化 → 托盘菜单同步
        self._window.visibility_changed.connect(self._tray.set_window_visible)

        # 托盘操作
        self._tray.toggle_window.connect(self._on_toggle_visibility)
        self._tray.open_file_requested.connect(self._window.open_file)
        self._tray.settings_requested.connect(self._window.show_settings)
        self._tray.quit_app.connect(self._on_quit)

    # ------------------------------------------------------------------
    # 槽函数
    # ------------------------------------------------------------------

    def _on_toggle_visibility(self) -> None:
        """切换窗口可见性。"""
        if self._window.isVisible():
            self._window.hide()
        else:
            self._window.show()

    def _on_window_hidden(self) -> None:
        """窗口被隐藏后的回调（由窗口 closeEvent 触发）。"""

    def _on_quit(self) -> None:
        """彻底退出应用。"""
        self._window.really_close()
        self._tray.hide()
        QApplication.quit()

    def _on_show_request(self) -> None:
        """后续实例请求显示窗口（通过 QLocalSocket 发送 'show' 消息）。"""
        conn = self._instance_server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(500)
            conn.readAll()
            conn.disconnectFromServer()
        # 显示窗口（如果当前隐藏中）
        if not self._window.isVisible():
            self._window.show()
        else:
            # 已在显示中，提到最前
            self._window.raise_()
            self._window.activateWindow()


def _acquire_single_instance() -> bool:
    """通过 Windows 命名互斥锁确认本进程是唯一实例。

    为什么不用 QLocalServer.listen 作锁：实测同一名字的 listen 在两个
    进程里会同时返回 True（Qt Windows 实现不保证互斥），导致双实例同时
    存活、各自读写同一份状态文件互相覆盖阅读进度。CreateMutexW 是内核
    原子原语，保证同一名字同一时刻只有一个进程能成功持有。
    """
    global _MUTEX_HANDLE
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        return False
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _MUTEX_HANDLE = handle  # 进程存活期间一直持有，进程退出时由内核释放
    return True


def _request_show_existing_instance() -> None:
    """连接已有实例并请求其显示窗口（带重试，覆盖服务端刚启动尚未就绪的情况）。

    若所有重试都失败，仍返回退出：宁可不起，也不成为第二个实例，
    避免两个实例同时读写同一份状态文件互相覆盖阅读进度。
    """
    for _ in range(5):
        socket = QLocalSocket()
        socket.connectToServer(_SERVER_NAME)
        if socket.waitForConnected(300):
            socket.write(b"show")
            socket.waitForBytesWritten(300)
            socket.disconnectFromServer()
            return
        QThread.msleep(200)


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出，托盘持续运行

    # ---- 单实例锁（内核互斥量，原子且跨进程可靠）----
    if not _acquire_single_instance():
        # 已有实例在运行，请求其显示窗口后退出
        _request_show_existing_instance()
        sys.exit(0)

    # 主实例：创建 IPC 服务器，用于接收后续实例的"显示窗口"请求。
    # 锁已由互斥量保证，这里 listen 失败（极罕见）只影响"双击唤起"，
    # 不影响应用本身运行。
    server = QLocalServer()
    server.listen(_SERVER_NAME)

    _ = App(server)  # 持有引用，防止被 GC
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
