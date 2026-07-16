# 浮光 — 隐蔽 TXT 阅读器

一个基于 PySide6 的桌面 TXT 阅读器，设计为半透明、无边框的悬浮窗口。适合在工作间隙低调阅读小说或文档。

## 特性

- **透明无边框窗口** — 无标题栏、无任务栏图标，默认 380×110 迷你尺寸，可手动拖边缘缩放
- **鼠标感知淡入淡出** — 鼠标进入窗口时文字渐显，离开时渐隐为几乎不可见
- **桌面背景感知** — 自动检测窗口下方背景亮度，深色背景用白色文字，浅色背景用暗色文字
- **系统托盘驻留** — 关闭窗口后最小化到托盘，右键菜单动态显示"显示"/"隐藏"状态
- **外观设置** — 托盘右键 → 设置，可调整字体（6 种）、字号（10-24px）、文字透明度
- **阅读进度记忆** — 记住上次打开的文件和滚动位置，下次启动自动恢复。每 5 秒自动保存进度
- **拖放打开文件** — 直接拖入 `.txt` 文件即可阅读
- **分块加载大文件** — 滚动接近底部时自动加载更多内容，流畅打开超大文本文件
- **自动编码检测** — 依次尝试 UTF-8、GBK、GB2312、GB18030、Big5，兼容各种中文编码
- **Ctrl + 拖动** — 按住 Ctrl 键拖动文本区域来移动窗口
- **窗口位置/大小记忆** — 关闭时自动保存窗口位置和大小，下次启动恢复

## 环境要求

- Python 3.9+
- PySide6 ≥ 6.5

## 安装

```bash
# 克隆仓库
git clone https://github.com/han02han/txt-reader.git
cd txt-reader

# 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # macOS/Linux

# 安装依赖
pip install -r requirements.txt
```

## 使用

```bash
# 直接运行
python main.py

# 或双击 run.bat（Windows，无命令行窗口）
```

启动后应用会出现在系统托盘中，显示一个「T」字图标。右键菜单操作：

| 菜单项 | 功能 |
|--------|------|
| 显示 / 隐藏 | 切换阅读窗口可见性（文字根据状态动态变化） |
| 打开文件… | 选择 TXT 文件打开 |
| 设置… | 调整字体、字号、文字透明度 |
| 退出 | 彻底退出应用 |

## 项目结构

```
txt-reader/
├── main.py              # 入口，组装窗口与托盘
├── reader_window.py     # 透明阅读器主窗口 + 主题检测 + 设置对话框
├── tray_manager.py      # 系统托盘管理
├── text_loader.py       # TXT 文件加载与编码检测
├── requirements.txt     # Python 依赖
├── run.bat              # Windows 快捷启动脚本
└── README.md
```

## 构建为独立 exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name fuguo main.py
# 产物在 dist/fuguo.exe
```

## 快捷键

| 操作 | 方式 |
|------|------|
| 移动窗口 | 按住 Ctrl 拖动文本区域，或拖动容器边距 |
| 调整大小 | 拖拽右边缘 / 下边缘 / 右下角 |
| 滚动阅读 | 鼠标滚轮（接近底部自动加载更多） |
