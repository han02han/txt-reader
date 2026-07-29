"""隐蔽 TXT 阅读器 — 入口模块。

启动流程：
1. 创建 QApplication（设置不随最后窗口关闭而退出）
2. 单实例检查：如已有实例运行则通知其显示窗口并退出；否则成为主实例
3. 创建阅读器窗口 + 系统托盘
4. 连接信号，进入事件循环
"""

import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from reader_window import ReaderWindow
from tray_manager import TrayManager

# 单实例锁的服务名（同一台机器上唯一标识本应用）
_SERVER_NAME = "fuguo_txt_reader"


class App:
    """应用主控制器，组装窗口和托盘。"""

    def __init__(self, instance_server: QLocalServer):
        self._window = ReaderWindow()
        self._tray = TrayManager()

        # 单实例锁：监听来自后续实例的"显示窗口"请求
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


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出，托盘持续运行

    # ---- 单实例检查 ----
    # 先尝试连接已有实例（快速路径）
    socket = QLocalSocket()
    socket.connectToServer(_SERVER_NAME)
    if socket.waitForConnected(500):
        # 已有实例在运行，请求其显示窗口后退出
        socket.write(b"show")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        sys.exit(0)

    # 没有已有实例，尝试成为主实例
    QLocalServer.removeServer(_SERVER_NAME)  # 清理上次崩溃残留
    server = QLocalServer()
    if not server.listen(_SERVER_NAME):
        # 极罕见的竞态：另一个实例在我们检查和 listen 之间抢占了服务名
        sys.exit(0)

    _ = App(server)  # 持有引用，防止被 GC
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
