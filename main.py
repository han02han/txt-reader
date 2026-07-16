"""隐蔽 TXT 阅读器 — 入口模块。

启动流程：
1. 创建 QApplication（设置不随最后窗口关闭而退出）
2. 创建阅读器窗口 + 系统托盘
3. 连接信号，进入事件循环
"""

import sys

from PySide6.QtWidgets import QApplication

from reader_window import ReaderWindow
from tray_manager import TrayManager


class App:
    """应用主控制器，组装窗口和托盘。"""

    def __init__(self):
        self._window = ReaderWindow()
        self._tray = TrayManager()

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


def main() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口不退出，托盘持续运行

    _ = App()  # 持有引用，防止被 GC
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
