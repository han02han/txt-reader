"""系统托盘管理模块。

- 托盘图标 + 右键菜单
- 左键点击 = 切换显示/隐藏
- 菜单项：显示/隐藏、打开文件、退出
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon


def _make_tray_icon(size: int = 64) -> QIcon:
    """生成一个简单的程序化托盘图标（书本/T 字样）。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 半透明深色圆角矩形背景
    painter.setBrush(QColor(40, 40, 40, 200))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, size - 8, size - 8, 14, 14)

    # 白色「T」字母
    painter.setPen(QColor(255, 255, 255, 240))
    font = painter.font()
    font.setPixelSize(int(size * 0.55))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "T")

    painter.end()
    return QIcon(pixmap)


class TrayManager(QSystemTrayIcon):
    """系统托盘管理器。"""

    # 信号
    toggle_window = Signal()          # 请求切换窗口可见性
    open_file_requested = Signal(str)  # 请求打开文件（携带路径）
    quit_app = Signal()               # 请求退出应用

    def __init__(self, parent=None):
        super().__init__(parent)

        self._window_visible: bool = False

        self.setIcon(_make_tray_icon())
        self.setToolTip("浮光")

        # 右键菜单
        self._menu = QMenu()

        self._toggle_action = QAction("显示")
        self._toggle_action.triggered.connect(self._on_toggle)
        self._menu.addAction(self._toggle_action)

        self._menu.addSeparator()

        self._open_action = QAction("打开文件...")
        self._open_action.triggered.connect(self._on_open_file)
        self._menu.addAction(self._open_action)

        self._menu.addSeparator()

        self._quit_action = QAction("退出")
        self._quit_action.triggered.connect(self._on_quit)
        self._menu.addAction(self._quit_action)

        self.setContextMenu(self._menu)

        # 菜单弹出前刷新文字，确保状态同步
        self._menu.aboutToShow.connect(self._refresh_toggle_text)

        # 左键点击 = 切换显示/隐藏
        self.activated.connect(self._on_activated)

    # ------------------------------------------------------------------
    # 信号处理
    # ------------------------------------------------------------------

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """托盘图标点击事件。"""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # 左键单击
            self._on_toggle()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:  # 左键双击
            self._on_toggle()

    def _on_toggle(self) -> None:
        """切换窗口显示状态。"""
        self.toggle_window.emit()

    def _on_open_file(self) -> None:
        """打开文件对话框。"""
        path, _ = QFileDialog.getOpenFileName(
            None,
            "选择 TXT 文件",
            "",
            "文本文件 (*.txt);;所有文件 (*)",
        )
        if path:
            self.open_file_requested.emit(path)

    def _on_quit(self) -> None:
        """退出应用。"""
        self.quit_app.emit()

    # ------------------------------------------------------------------
    # 菜单文字同步
    # ------------------------------------------------------------------

    def set_window_visible(self, visible: bool) -> None:
        """由外部通知窗口可见性变化，用于同步菜单文字。"""
        self._window_visible = visible

    def _refresh_toggle_text(self) -> None:
        """菜单弹出前刷新切换按钮文字，反映当前状态。"""
        if self._window_visible:
            self._toggle_action.setText("隐藏")
        else:
            self._toggle_action.setText("显示")
