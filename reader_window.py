"""透明阅读器主窗口。

- 无边框、背景透明、无任务栏图标
- 鼠标进入窗口时文字淡入，离开时淡出
- 支持拖放 TXT 文件、窗口拖动、滚轮滚动
- 支持 Ctrl+拖动文本区域来移动窗口
"""

import json
import os as _os
import sys as _sys

from text_loader import get_file_info, load_file_chunked
from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSettings,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QTextCursor,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# 淡入淡出动画时长（毫秒）
FADE_DURATION = 250
# 默认窗口大小（约显示 4 行文字）
DEFAULT_WIDTH = 380
DEFAULT_HEIGHT = 110
# 大文件分块大小（字符）
CHUNK_SIZE = 50000
# 窗口边缘缩放检测范围（像素）
EDGE_MARGIN = 8
# 背景亮度阈值（0-255），高于此值视为亮背景
BRIGHTNESS_THRESHOLD = 128
# 主题颜色预设
_DARK_THEME = {
    "container_bg": "rgba(0, 0, 0, 60)",
    "text_color": "rgba(255, 255, 255, 180)",
    "selection_bg": "rgba(255, 255, 255, 40)",
    "placeholder_color": "rgba(255, 255, 255, 100)",
}
_LIGHT_THEME = {
    "container_bg": "rgba(255, 255, 255, 60)",
    "text_color": "rgba(0, 0, 0, 220)",
    "selection_bg": "rgba(0, 0, 0, 30)",
    "placeholder_color": "rgba(0, 0, 0, 100)",
}
# 状态文件路径（exe 同目录）


def _state_path() -> str:
    """获取状态 JSON 文件路径。"""
    exe_dir = _os.path.dirname(_sys.executable) if getattr(_sys, 'frozen', False) else _os.path.dirname(_os.path.abspath(__file__))
    return _os.path.join(exe_dir, "fuguo_state.json")


def _load_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(data: dict) -> None:
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# 可选字体列表
_FONT_OPTIONS = [
    "Microsoft YaHei",
    "PingFang SC",
    "SimSun",
    "KaiTi",
    "FangSong",
    "DengXian",
]


class _ReaderTextEdit(QTextEdit):
    """自定义文本编辑器：支持滚轮平滑滚动、键盘快捷键、接近底部时加载更多，
    以及 Ctrl+拖动来移动窗口。"""

    near_bottom = Signal()
    drag_requested = Signal(QMouseEvent)

    # 滚轮每格滚动行数（用于平滑滚动）
    WHEEL_LINES = 3
    # 平滑滚动动画时长（毫秒）
    SCROLL_ANIM_DURATION = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scroll_anim: QVariantAnimation | None = None
        self._scroll_target: int = 0

    # ------------------------------------------------------------------
    # 滚轮 — 平滑滚动
    # ------------------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:
        """滚轮事件 — 3 行/格平滑滚动 + 接近底部加载更多。"""
        vbar = self.verticalScrollBar()
        if vbar is None:
            super().wheelEvent(event)
            return

        # 检测接近底部
        if vbar.value() >= vbar.maximum() - 50:
            self.near_bottom.emit()

        angle = event.angleDelta().y()
        if angle == 0:
            event.accept()
            return

        line_height = self.fontMetrics().lineSpacing()
        # 每格（120 单位）= WHEEL_LINES 行；负号使「向下滚=文字前进」
        lines = (-angle / 120.0) * self.WHEEL_LINES
        delta_px = int(lines * line_height)

        if delta_px != 0:
            self._animate_scroll_by(delta_px)

        event.accept()

    # ------------------------------------------------------------------
    # 键盘快捷键
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        """Ctrl+箭头 = 大幅跳转；其它交给父类。"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            line_h = self.fontMetrics().lineSpacing()
            delta = 0
            if event.key() == Qt.Key.Key_Right:
                delta = 100 * line_h
            elif event.key() == Qt.Key.Key_Left:
                delta = -100 * line_h
            elif event.key() == Qt.Key.Key_Down:
                delta = 1000 * line_h
            elif event.key() == Qt.Key.Key_Up:
                delta = -1000 * line_h

            if delta != 0:
                self._animate_scroll_by(delta, duration_ms=250)
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # 平滑滚动动画
    # ------------------------------------------------------------------

    def _animate_scroll_by(self, delta_px: int, duration_ms: int | None = None) -> None:
        """平滑滚动 delta_px 像素，新事件到达时自动更新目标值。"""
        vbar = self.verticalScrollBar()
        if vbar is None:
            return

        if duration_ms is None:
            duration_ms = self.SCROLL_ANIM_DURATION

        current = vbar.value()
        # 如果动画运行中，在上次目标基础上累加；否则从当前位置开始
        if (self._scroll_anim is not None
                and self._scroll_anim.state() == QVariantAnimation.State.Running):
            self._scroll_target = max(0, min(vbar.maximum(),
                                             self._scroll_target + delta_px))
        else:
            self._scroll_target = max(0, min(vbar.maximum(),
                                             current + delta_px))

        if self._scroll_target == current:
            return

        if self._scroll_anim is not None:
            self._scroll_anim.stop()

        self._scroll_anim = QVariantAnimation(self)
        self._scroll_anim.setDuration(duration_ms)
        self._scroll_anim.setStartValue(current)
        self._scroll_anim.setEndValue(self._scroll_target)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_anim.valueChanged.connect(self._on_scroll_anim_tick)
        self._scroll_anim.start()

    def _on_scroll_anim_tick(self, value) -> None:
        """动画每帧更新滚动条位置。"""
        vbar = self.verticalScrollBar()
        if vbar is not None:
            vbar.setValue(round(value))

    # ------------------------------------------------------------------
    # 窗口拖动（Ctrl+鼠标）
    # ------------------------------------------------------------------

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
        self._resizing: str | None = None        # 当前缩放边：'right','bottom','bottomright'
        self._resize_start_geo: QRect | None = None
        self._resize_start_pos: QPoint | None = None
        self._file_path: str | None = None
        self._current_offset: int = 0
        self._has_more: bool = False
        self._quitting: bool = False
        self._is_light_bg: bool = False
        # 从设置中读取或使用默认值
        s = QSettings("浮光", "浮光")
        self._font_family: str = s.value("appearance/font", "Microsoft YaHei")
        self._font_size: int = s.value("appearance/font_size", 14, type=int)
        self._text_alpha: int = s.value("appearance/alpha", 180, type=int)
        self._text_widget: _ReaderTextEdit | None = None
        self._container: QFrame | None = None
        self._opacity_effect: QGraphicsOpacityEffect | None = None
        self._fade_anim: QPropertyAnimation | None = None

        # 自动保存阅读进度的定时器
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(5000)  # 每 5 秒保存一次进度
        self._save_timer.timeout.connect(self._save_reading_state)

        self._setup_window()
        self._setup_ui()
        self._restore_geometry()
        self._restore_reading_state()

    # ------------------------------------------------------------------
    # 窗口设置
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        """配置窗口标志与属性。"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint   # 无边框
            | Qt.WindowType.Tool                # 隐藏任务栏图标
            | Qt.WindowType.WindowStaysOnTopHint  # 保持在其他窗口之上
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
        inner.setContentsMargins(14, 10, 14, 10)

        # 自定义文本编辑区
        self._text_widget = _ReaderTextEdit(self._container)
        self._text_widget.setReadOnly(True)
        self._text_widget.setFrameShape(QFrame.Shape.NoFrame)
        # 滚动条用 CSS 隐藏（width:0），但策略保持启用，确保 value() 正确跟踪位置
        self._text_widget.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self._text_widget.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
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
        """鼠标进入窗口 → 文字淡入 + 更新主题。"""
        super().enterEvent(event)
        self._fade_to(1.0)
        self._update_theme()

    def changeEvent(self, event) -> None:
        """窗口激活状态变化 → 更新主题（适用于 Alt+Tab 切换回来）。"""
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._update_theme()
        super().changeEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标离开窗口 → 文字淡出到几乎不可见（但保留鼠标事件响应）。"""
        super().leaveEvent(event)
        self._fade_to(0.01)  # 不能到 0.0，否则 WA_TranslucentBackground 会让鼠标穿透

    def _fade_to(self, target: float) -> None:
        """平滑过渡到目标透明度。"""
        if self._fade_anim is None:
            return
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(target)
        self._fade_anim.start()

    # ------------------------------------------------------------------
    # 窗口拖动 + 边缘缩放（无边框替代方案）
    # ------------------------------------------------------------------

    def _get_resize_edge(self, pos: QPoint) -> str | None:
        """判断鼠标是否靠近窗口边缘，返回缩放方向。"""
        w, h = self.width(), self.height()
        right = pos.x() >= w - EDGE_MARGIN
        bottom = pos.y() >= h - EDGE_MARGIN

        if right and bottom:
            return "bottomright"
        elif right:
            return "right"
        elif bottom:
            return "bottom"
        return None

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
        """按下鼠标 — 靠近边缘则缩放，否则拖动窗口。"""
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._get_resize_edge(event.position().toPoint())
            if edge:
                self._resizing = edge
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = event.globalPosition().toPoint()
                return
            self._begin_drag(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """移动鼠标 — 缩放中 / 拖动中。"""
        if self._resizing:
            delta = event.globalPosition().toPoint() - self._resize_start_pos
            geo = QRect(self._resize_start_geo)
            if self._resizing in ("right", "bottomright"):
                geo.setRight(max(geo.left() + 200, geo.right() + delta.x()))
            if self._resizing in ("bottom", "bottomright"):
                geo.setBottom(max(geo.top() + 100, geo.bottom() + delta.y()))
            self.setGeometry(geo)
            return

        self._do_drag(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """释放鼠标 — 结束缩放或拖动。"""
        if self._resizing:
            self._resizing = None
            self._update_theme()
            return
        self._end_drag()
        self._update_theme()
        super().mouseReleaseEvent(event)

    def eventFilter(self, obj, event) -> bool:
        """事件过滤器 — 容器上的拖放与边缘缩放。"""
        from PySide6.QtCore import QEvent
        if obj is self.findChild(QFrame, "textContainer"):
            if event.type() == QEvent.Type.MouseButtonPress:
                child = obj.childAt(event.position().toPoint())
                if child is self._text_widget:
                    return False  # 文本区让 QTextEdit 自己处理

                # 检查是否在窗口边缘 → 缩放
                local = obj.mapTo(self, event.position().toPoint())
                edge = self._get_resize_edge(local)
                if edge:
                    self._resizing = edge
                    self._resize_start_geo = self.geometry()
                    self._resize_start_pos = event.globalPosition().toPoint()
                    return True

                # 否则拖动窗口
                self._begin_drag(event)
                return True

            elif event.type() == QEvent.Type.MouseMove:
                if self._resizing:
                    delta = event.globalPosition().toPoint() - self._resize_start_pos
                    geo = QRect(self._resize_start_geo)
                    if self._resizing in ("right", "bottomright"):
                        geo.setRight(max(geo.left() + 200, geo.right() + delta.x()))
                    if self._resizing in ("bottom", "bottomright"):
                        geo.setBottom(max(geo.top() + 100, geo.bottom() + delta.y()))
                    self.setGeometry(geo)
                    return True
                if self._drag_pos is not None:
                    self._do_drag(event)
                    return True
                # 靠近边缘时显示缩放光标（设在容器上，不影响窗口事件）
                local = obj.mapTo(self, event.position().toPoint())
                edge = self._get_resize_edge(local)
                if edge:
                    obj.setCursor(Qt.CursorShape.SizeFDiagCursor if edge == "bottomright"
                                  else Qt.CursorShape.SizeHorCursor if edge == "right"
                                  else Qt.CursorShape.SizeVerCursor)
                else:
                    obj.unsetCursor()  # 恢复默认，让文本区显示 I 型光标

            elif event.type() == QEvent.Type.MouseButtonRelease:
                if self._resizing:
                    self._resizing = None
                    self._update_theme()
                    return True
                if self._drag_pos is not None:
                    self._end_drag()
                    self._update_theme()
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
        """根据当前背景亮度应用对应的文字与容器颜色。

        注意：setStyleSheet 会触发 QTextEdit 内部布局重建，可能导致
        滚动位置被重置。因此先保存视口第一个可见字符位置再恢复。
        """
        t = _LIGHT_THEME if self._is_light_bg else _DARK_THEME

        # 保存当前视口第一个可见字符位置（setStyleSheet 可能重置滚动）
        saved_char: int = 0
        if self._text_widget is not None:
            cursor = self._text_widget.cursorForPosition(QPoint(0, 0))
            saved_char = cursor.position()

        if self._container is not None:
            self._container.setStyleSheet(f"""
                #textContainer {{
                    background-color: {t['container_bg']};
                    border-radius: 12px;
                }}
            """)

        if self._text_widget is not None:
            base_color = "255, 255, 255" if not self._is_light_bg else "0, 0, 0"
            self._text_widget.setStyleSheet(f"""
                QTextEdit {{
                    background: transparent;
                    color: rgba({base_color}, {self._text_alpha});
                    font-family: "{self._font_family}", "Microsoft YaHei", sans-serif;
                    font-size: {self._font_size}px;
                    line-height: 1.5;
                    selection-background-color: {t['selection_bg']};
                }}
                QScrollBar {{ width: 0; height: 0; }}
            """)

        # 恢复滚动位置（用字符位置，不依赖排版进度）
        if saved_char > 0 and self._text_widget is not None:
            QTimer.singleShot(50, lambda: self._restore_char_position(saved_char))

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
                self._text_widget.moveCursor(QTextCursor.MoveOperation.Start)

            info = get_file_info(file_path)
            self.setWindowTitle(f"浮光 — {info['name']}")

            self._save_timer.start()  # 开始定期保存阅读进度

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
                cursor.movePosition(QTextCursor.MoveOperation.End)
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
        # 提到最前，确保鼠标事件能到达窗口
        self.raise_()
        self.activateWindow()
        # 窗口出现后再采样桌面背景，避免阻塞显示
        QTimer.singleShot(300, self._update_theme)

    def hideEvent(self, event) -> None:
        """窗口已隐藏，通知托盘；同时异步更新主题。"""
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def closeEvent(self, event) -> None:
        """关闭窗口时隐藏而非退出，由托盘控制真正退出。"""
        if self._quitting:
            event.accept()
            return
        self._save_reading_state()
        self._save_timer.stop()
        self._save_geometry()
        self.hide()
        self.hide_requested.emit()
        event.ignore()

    def really_close(self) -> None:
        """真正关闭窗口（程序退出时由 main 调用）。"""
        self._save_reading_state()
        self._save_geometry()
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

    # ------------------------------------------------------------------
    # 阅读进度持久化
    # ------------------------------------------------------------------

    def _save_reading_state(self) -> None:
        """保存当前文件路径和滚动位置到 JSON 文件。"""
        if not self._file_path or self._text_widget is None:
            return
        vbar = self._text_widget.verticalScrollBar()
        if vbar is None:
            return

        scroll_val = vbar.value()
        scroll_max = vbar.maximum()

        # 保存视口第一个可见字符在文档中的位置（用于可靠恢复，
        # 不依赖窗口大小 / 字体 / 排版进度）
        cursor = self._text_widget.cursorForPosition(QPoint(0, 0))
        first_visible_char = cursor.position()

        data = {
            "last_file": self._file_path,
            "scroll_pos": scroll_val,
            "scroll_max": scroll_max,
            "loaded_offset": self._current_offset,
            "first_visible_char": first_visible_char,
        }
        _save_state(data)

        # 调试日志
        try:
            with open(_state_path() + ".log", "a", encoding="utf-8") as f:
                import datetime
                f.write(f"{datetime.datetime.now()}: saved scroll={scroll_val} max={scroll_max} char={first_visible_char}\n")
        except Exception:
            pass

    def _restore_reading_state(self) -> None:
        """从 JSON 文件恢复上次阅读的文件和滚动位置。"""
        data = _load_state()
        last_file = data.get("last_file")
        if not last_file:
            return
        if not _os.path.exists(last_file):
            _save_state({})  # 文件已删除，清除记录
            return

        # 优先使用字符位置恢复（不受窗口尺寸/字体/排版进度影响）；
        # 旧格式没有 first_visible_char，回退到 scroll_pos
        target_char = data.get("first_visible_char")
        if target_char is not None and target_char > 0:
            target_scroll = 0  # 用字符位置，不需要 scroll 回退
        else:
            target_char = None
            target_scroll = data.get("scroll_pos", 0)

        self._file_path = last_file
        self._current_offset = 0

        text, self._current_offset, self._has_more = load_file_chunked(
            last_file, 0, CHUNK_SIZE
        )
        if self._text_widget is not None:
            self._text_widget.setPlainText(text)

        # 持续加载直到文本量覆盖目标恢复位置（字符位置或滚动位置）
        vbar = self._text_widget.verticalScrollBar() if self._text_widget else None
        while self._has_more and self._text_widget is not None:
            # 新格式：字符数够覆盖 target_char 就停
            if target_char is not None and self._text_widget.document().characterCount() > target_char:
                break
            # 旧格式：滚动条最大值够覆盖 target_scroll 就停
            if target_char is None and vbar and vbar.maximum() >= target_scroll:
                break
            text, self._current_offset, self._has_more = load_file_chunked(
                last_file, self._current_offset, CHUNK_SIZE
            )
            if text:
                cursor = self._text_widget.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(text)

        # 恢复滚动位置（延迟等文字排版完成）
        if target_char is not None and target_char > 0:
            QTimer.singleShot(100, lambda: self._restore_char_position(target_char))
        elif target_scroll > 0:
            QTimer.singleShot(100, lambda: self._restore_scroll(target_scroll))

        info = get_file_info(last_file)
        self.setWindowTitle(f"浮光 — {info['name']}")
        self._save_timer.start()

    def _restore_scroll(self, target: int, retries: int = 5) -> None:
        """延迟恢复滚动位置（带重试，等 QTextEdit 完成排版后调用）。

        旧格式回退使用。新格式优先使用 _restore_char_position。
        """
        if self._text_widget is None:
            return
        vbar = self._text_widget.verticalScrollBar()
        if vbar is not None:
            if vbar.maximum() >= target:
                vbar.setValue(target)
                # 调试日志
                try:
                    with open(_state_path() + ".log", "a", encoding="utf-8") as f:
                        import datetime
                        f.write(f"{datetime.datetime.now()}: restored scroll={target} max={vbar.maximum()}\n")
                except Exception:
                    pass
            elif retries > 0:
                QTimer.singleShot(100, lambda: self._restore_scroll(target, retries - 1))

    def _restore_char_position(self, pos: int, retries: int = 5) -> None:
        """用文档字符位置恢复滚动（带重试，不依赖排版进度）。

        相比 scrollbar 值，字符位置不受窗口大小、字体、排版完成度的影响，
        恢复更可靠。
        """
        if self._text_widget is None:
            return
        doc = self._text_widget.document()
        # characterCount() 包含末尾段落分隔符，所以用 > 判断
        if doc.characterCount() > pos:
            cursor = self._text_widget.textCursor()
            cursor.setPosition(pos)
            self._text_widget.setTextCursor(cursor)
            self._text_widget.ensureCursorVisible()
            # 调试日志
            try:
                with open(_state_path() + ".log", "a", encoding="utf-8") as f:
                    import datetime
                    vbar = self._text_widget.verticalScrollBar()
                    cur_scroll = vbar.value() if vbar else 0
                    f.write(f"{datetime.datetime.now()}: restored char_pos={pos} scroll_now={cur_scroll}\n")
            except Exception:
                pass
        elif retries > 0:
            QTimer.singleShot(100, lambda: self._restore_char_position(pos, retries - 1))

    # ------------------------------------------------------------------
    # 外观设置
    # ------------------------------------------------------------------

    def show_settings(self) -> None:
        """弹出外观设置对话框。"""
        dlg = _SettingsDialog(self._font_family, self._font_size, self._text_alpha, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._font_family, self._font_size, self._text_alpha = dlg.values()
            s = QSettings("浮光", "浮光")
            s.setValue("appearance/font", self._font_family)
            s.setValue("appearance/font_size", self._font_size)
            s.setValue("appearance/alpha", self._text_alpha)
            self._apply_theme()


class _SettingsDialog(QDialog):
    """字体与文字透明度设置对话框。"""

    def __init__(self, current_font: str, current_size: int, current_alpha: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("外观设置")
        self.resize(340, 200)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowTitleHint
        )

        layout = QFormLayout(self)

        # 字体选择
        self._font_combo = QComboBox()
        for name in _FONT_OPTIONS:
            self._font_combo.addItem(name)
        idx = self._font_combo.findText(current_font)
        if idx >= 0:
            self._font_combo.setCurrentIndex(idx)
        layout.addRow("字体:", self._font_combo)

        # 字号滑块 (10-24)
        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setRange(10, 24)
        self._size_slider.setValue(current_size)
        self._size_label = QLabel(str(current_size))
        self._size_slider.valueChanged.connect(
            lambda v: self._size_label.setText(str(v))
        )
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("小"))
        size_row.addWidget(self._size_slider)
        size_row.addWidget(QLabel("大"))
        size_row.addWidget(self._size_label)
        layout.addRow("字号:", size_row)

        # 透明度滑块 (alpha 120-240)
        self._alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self._alpha_slider.setRange(120, 240)
        self._alpha_slider.setValue(current_alpha)
        self._alpha_value_label = QLabel(str(current_alpha))
        self._alpha_slider.valueChanged.connect(
            lambda v: self._alpha_value_label.setText(str(v))
        )

        alpha_row = QHBoxLayout()
        alpha_row.addWidget(QLabel("淡"))
        alpha_row.addWidget(self._alpha_slider)
        alpha_row.addWidget(QLabel("亮"))
        alpha_row.addWidget(self._alpha_value_label)
        layout.addRow("文字:", alpha_row)

        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def values(self) -> tuple[str, int, int]:
        """返回 (font_family, font_size, alpha)。"""
        return self._font_combo.currentText(), self._size_slider.value(), self._alpha_slider.value()
