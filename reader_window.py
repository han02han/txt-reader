"""透明阅读器主窗口。

- 无边框、背景透明、无任务栏图标
- 鼠标进入窗口时文字淡入，离开时淡出
- 支持拖放 TXT 文件、窗口拖动、滚轮滚动
- 支持 Ctrl+拖动文本区域来移动窗口
"""

from text_loader import get_file_info, load_file_chunked
from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QSettings,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# 淡入淡出动画时长（毫秒）
FADE_DURATION = 250
# 默认窗口大小
DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 600
# 大文件分块大小（字符）
CHUNK_SIZE = 50000
# 背景亮度阈值（0-255），高于此值视为亮背景
BRIGHTNESS_THRESHOLD = 128
# 主题颜色预设
_DARK_THEME = {
    "container_bg": "rgba(0, 0, 0, 60)",
    "text_color": "rgba(255, 255, 255, 230)",
    "selection_bg": "rgba(255, 255, 255, 60)",
    "placeholder_color": "rgba(255, 255, 255, 100)",
}
_LIGHT_THEME = {
    "container_bg": "rgba(255, 255, 255, 60)",
    "text_color": "rgba(0, 0, 0, 220)",
    "selection_bg": "rgba(0, 0, 0, 30)",
    "placeholder_color": "rgba(0, 0, 0, 100)",
}


class _ReaderTextEdit(QTextEdit):
    """自定义文本编辑器：支持滚轮接近底部时通知父窗口加载更多，
    以及 Ctrl+拖动来移动窗口。"""

    near_bottom = Signal()
    drag_requested = Signal(QMouseEvent)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """滚轮事件 — 检测接近底部时发出信号。"""
        vbar = self.verticalScrollBar()
        if vbar.isVisible() and vbar.value() >= vbar.maximum() - 50:
            self.near_bottom.emit()
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """按住 Ctrl + 左键 → 请求拖动窗口；否则正常选择文本。"""
        if event.button() == Qt.MouseButton.LeftButton and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.drag_requested.emit(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.drag_requested.emit(event)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.drag_requested.emit(event)
            return
        super().mouseReleaseEvent(event)


class ReaderWindow(QWidget):
    """透明阅读器主窗口。"""

    # 信号
    hide_requested = Signal()          # 窗口被"关闭"（实际是隐藏）时发出
    visibility_changed = Signal(bool)  # 窗口显示/隐藏状态变化

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._drag_pos: QPoint | None = None
        self._file_path: str | None = None
        self._current_offset: int = 0
        self._has_more: bool = False
        self._quitting: bool = False
        self._is_light_bg: bool = False
        self._text_widget: _ReaderTextEdit | None = None
        self._container: QFrame | None = None
        self._opacity_effect: QGraphicsOpacityEffect | None = None
        self._fade_anim: QPropertyAnimation | None = None

        self._setup_window()
        self._setup_ui()
        self._restore_geometry()

    # ------------------------------------------------------------------
    # 窗口设置
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        """配置窗口标志与属性。"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint  # 无边框
            | Qt.WindowType.Tool               # 隐藏任务栏图标
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self.resize(DEFAULT_WIDTH, DEFAULT_HEIGHT)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """构建界面：中央半透明容器 + 只读文本区 + 淡入淡出效果。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # 中央容器 — 半透明底衬，保证文字在任何背景下可读
        self._container = QFrame(self)
        self._container.setObjectName("textContainer")
        self._container.setStyleSheet("""
            #textContainer {
                border-radius: 12px;
            }
        """)

        inner = QHBoxLayout(self._container)
        inner.setContentsMargins(24, 18, 24, 18)

        # 自定义文本编辑区
        self._text_widget = _ReaderTextEdit(self._container)
        self._text_widget.setReadOnly(True)
        self._text_widget.setFrameShape(QFrame.Shape.NoFrame)
        self._text_widget.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._text_widget.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # 连接自定义信号
        self._text_widget.near_bottom.connect(self._load_more)
        self._text_widget.drag_requested.connect(self._on_edit_drag)

        inner.addWidget(self._text_widget)
        root.addWidget(self._container)

        # 容器边距区域也可用于拖动窗口
        self._container.installEventFilter(self)

        # 透明度效果 — 仅作用于文字容器
        self._opacity_effect = QGraphicsOpacityEffect(self._container)
        self._opacity_effect.setOpacity(0.0)  # 初始隐藏
        self._container.setGraphicsEffect(self._opacity_effect)

        # 淡入淡出动画
        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_anim.setDuration(FADE_DURATION)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # 初始提示文字
        self._text_widget.setPlaceholderText(
            "拖放 TXT 文件到此处\n或通过系统托盘菜单打开文件\n\n"
            "按住 Ctrl 拖动鼠标可移动窗口"
        )

        # 应用默认主题（后续由 _update_theme 动态调整）
        self._apply_theme()

    # ------------------------------------------------------------------
    # 鼠标感知 — 淡入淡出
    # ------------------------------------------------------------------

    def enterEvent(self, event) -> None:
        """鼠标进入窗口 → 文字淡入。"""
        super().enterEvent(event)
        self._fade_to(1.0)

    def leaveEvent(self, event) -> None:
        """鼠标离开窗口 → 文字淡出。"""
        super().leaveEvent(event)
        self._fade_to(0.0)

    def _fade_to(self, target: float) -> None:
        """平滑过渡到目标透明度。"""
        if self._fade_anim is None:
            return
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(target)
        self._fade_anim.start()

    # ------------------------------------------------------------------
    # 窗口拖动（无边框替代方案）
    # ------------------------------------------------------------------

    def _begin_drag(self, event: QMouseEvent) -> None:
        """记录拖动起点。"""
        self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _do_drag(self, event: QMouseEvent) -> None:
        """执行拖动。"""
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def _end_drag(self) -> None:
        """结束拖动。"""
        self._drag_pos = None

    def _on_edit_drag(self, event: QMouseEvent) -> None:
        """来自 _ReaderTextEdit 的拖动请求（Ctrl+鼠标）。"""
        if event.type() == event.Type.MouseButtonPress:
            self._begin_drag(event)
        elif event.type() == event.Type.MouseMove:
            self._do_drag(event)
        elif event.type() == event.Type.MouseButtonRelease:
            self._end_drag()
            self._update_theme()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """在窗口空白区域按下鼠标 → 开始拖动。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin_drag(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """拖动窗口。"""
        self._do_drag(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._end_drag()
        self._update_theme()  # 窗口可能移到了不同背景上
        super().mouseReleaseEvent(event)

    def eventFilter(self, obj, event) -> bool:
        """事件过滤器 — 在容器边距区域按下左键时，转发到窗口拖动。"""
        from PySide6.QtCore import QEvent
        if obj is self.findChild(QFrame, "textContainer"):
            if event.type() == QEvent.Type.MouseButtonPress:
                # 如果点击在容器的边距区域（不在 QTextEdit 上），启动拖动
                child = obj.childAt(event.position().toPoint())
                if child is not self._text_widget:
                    self._begin_drag(event)
                    return True
            elif event.type() == QEvent.Type.MouseMove:
                if self._drag_pos is not None:
                    self._do_drag(event)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if self._drag_pos is not None:
                    self._end_drag()
                    return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # 背景感知主题切换
    # ------------------------------------------------------------------

    def _update_theme(self) -> None:
        """采样窗口下方桌面背景亮度，自动切换明暗主题。

        故意在窗口外侧采样，避免捕获到窗口自身内容。
        """
        screen = self.screen()
        if screen is None:
            return

        try:
            geo = self.geometry()
            sample_size = 60

            # 在窗口左外侧采样，避免拍到窗口自己；
            # 如果窗口靠左边界，则改为右外侧
            if geo.x() > sample_size + 10:
                sx = geo.x() - sample_size - 10
            else:
                sx = min(geo.right() + 10, screen.size().width() - sample_size)
            sy = max(0, geo.y() + (geo.height() - sample_size) // 2)

            pixmap = screen.grabWindow(0, sx, sy, sample_size, sample_size)
            if pixmap.isNull():
                return
            img = pixmap.toImage()
            if img.isNull():
                return

            # 每隔 2 像素采样一次，减少计算量
            total, count = 0, 0
            for py in range(0, img.height(), 2):
                for px in range(0, img.width(), 2):
                    color = img.pixelColor(px, py)
                    # 感知亮度公式
                    total += 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
                    count += 1

            avg = total / max(count, 1)
            light = avg > BRIGHTNESS_THRESHOLD

            if light != self._is_light_bg:
                self._is_light_bg = light
                self._apply_theme()
        except Exception:
            pass  # 检测失败时保持当前主题，不影响正常使用

    def _apply_theme(self) -> None:
        """根据当前背景亮度应用对应的文字与容器颜色。"""
        t = _LIGHT_THEME if self._is_light_bg else _DARK_THEME

        if self._container is not None:
            self._container.setStyleSheet(f"""
                #textContainer {{
                    background-color: {t['container_bg']};
                    border-radius: 12px;
                }}
            """)

        if self._text_widget is not None:
            self._text_widget.setStyleSheet(f"""
                QTextEdit {{
                    background: transparent;
                    color: {t['text_color']};
                    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
                    font-size: 16px;
                    line-height: 1.6;
                    selection-background-color: {t['selection_bg']};
                }}
                QScrollBar {{ width: 0; height: 0; }}
            """)

    # ------------------------------------------------------------------
    # 拖放 TXT 文件
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".txt"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".txt"):
                self.open_file(path)
                break

    # ------------------------------------------------------------------
    # 文件加载
    # ------------------------------------------------------------------

    def open_file(self, file_path: str) -> None:
        """加载并显示 TXT 文件。"""
        try:
            self._file_path = file_path
            self._current_offset = 0

            # 加载第一块
            text, self._current_offset, self._has_more = load_file_chunked(
                file_path, 0, CHUNK_SIZE
            )

            if self._text_widget is not None:
                self._text_widget.setPlainText(text)
                self._text_widget.moveCursor(
                    self._text_widget.textCursor().Start
                )

            info = get_file_info(file_path)
            self.setWindowTitle(f"浮光 — {info['name']}")

            if not self.isVisible():
                self.show()

        except Exception as e:
            if self._text_widget is not None:
                self._text_widget.setPlainText(f"❌ 无法打开文件:\n{e}")

    # ------------------------------------------------------------------
    # 分页加载
    # ------------------------------------------------------------------

    def _load_more(self) -> None:
        """加载下一块内容并追加到末尾。"""
        if not self._file_path or not self._has_more:
            return
        try:
            text, self._current_offset, self._has_more = load_file_chunked(
                self._file_path, self._current_offset, CHUNK_SIZE
            )
            if self._text_widget and text:
                cursor = self._text_widget.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.insertText(text)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 窗口关闭 → 隐藏到托盘
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        """窗口已显示，通知托盘，延迟更新主题。"""
        super().showEvent(event)
        self.visibility_changed.emit(True)
        # 显示时确保内容可见（初始透明度为 0）
        if self._opacity_effect is not None:
            self._opacity_effect.setOpacity(1.0)
        # 窗口出现后再采样桌面背景，避免阻塞显示
        QTimer.singleShot(300, self._update_theme)

    def hideEvent(self, event) -> None:
        """窗口已隐藏，通知托盘；同时异步更新主题。"""
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def closeEvent(self, event) -> None:
        """关闭窗口时隐藏而非退出，由托盘控制真正退出。"""
        if self._quitting:
            self._save_geometry()
            event.accept()
            return
        self._save_geometry()
        self.hide()
        self.hide_requested.emit()
        event.ignore()

    def really_close(self) -> None:
        """真正关闭窗口（程序退出时由 main 调用）。"""
        self._quitting = True
        self.close()

    # ------------------------------------------------------------------
    # 窗口位置/大小持久化
    # ------------------------------------------------------------------

    def _save_geometry(self) -> None:
        settings = QSettings("浮光", "浮光")
        settings.setValue("window/geometry", self.saveGeometry())

    def _restore_geometry(self) -> None:
        settings = QSettings("浮光", "浮光")
        geo = settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            # 首次启动，居中显示
            screen = self.screen().availableGeometry()
            self.move(
                (screen.width() - self.width()) // 2,
                (screen.height() - self.height()) // 2,
            )
