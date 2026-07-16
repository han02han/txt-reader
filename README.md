# 浮光 — 隐蔽 TXT 阅读器

一个基于 PySide6 的桌面 TXT 阅读器，设计为半透明、无边框的悬浮窗口，适合在工作间隙低调阅读文本。

## 特性

- **透明无边框窗口** — 无标题栏、无任务栏图标，半透明深色底衬保证文字可读
- **鼠标感知淡入淡出** — 鼠标进入窗口时文字渐显，离开时渐隐，不遮挡背后内容
- **系统托盘驻留** — 关闭窗口后最小化到托盘，右键菜单提供快捷操作，左键单击切换显示/隐藏
- **拖放打开文件** — 直接拖入 `.txt` 文件即可阅读
- **分块加载大文件** — 滚动接近底部时自动加载更多内容，流畅打开超大文本文件
- **自动编码检测** — 依次尝试 UTF-8、GBK、GB2312、GB18030、Big5，兼容各种中文编码
- **Ctrl + 拖动** — 按住 Ctrl 键拖动文本区域来移动窗口
- **窗口位置记忆** — 关闭时自动保存窗口位置和大小，下次启动恢复
- **单文件、零依赖之外** — 仅依赖 PySide6，无其他第三方库

## 环境要求

- Python 3.9+
- PySide6 ≥ 6.5

## 安装

```bash
# 克隆仓库
git clone <repo-url> txt-reader
cd txt-reader

# 创建虚拟环境（推荐）
python -m venv venv
venv\Scripts\activate  # Windows
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
| 显示/隐藏 | 切换阅读窗口可见性 |
| 打开文件… | 选择 TXT 文件打开 |
| 退出 | 彻底退出应用 |

## 项目结构

```
txt-reader/
├── main.py              # 入口，组装窗口与托盘
├── reader_window.py     # 透明阅读器主窗口
├── tray_manager.py      # 系统托盘管理
├── text_loader.py       # TXT 文件加载与编码检测
├── requirements.txt     # Python 依赖
├── run.bat              # Windows 快捷启动脚本
└── README.md
```

## 构建为独立 exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name 浮光 main.py
```
