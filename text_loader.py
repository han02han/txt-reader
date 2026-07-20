"""TXT 文件加载与编码检测模块。"""

from pathlib import Path

# 按优先级排列的编码尝试列表
_ENCODINGS = ["utf-8", "gbk", "gb2312", "gb18030", "big5", "latin-1"]

# 大文件分块读取大小（字符数）
CHUNK_SIZE = 50000

# 文件内容缓存：{path: (mtime, content)}
# 避免 _restore_reading_state 循环中每次调用 load_file_chunked 都读全文件
_cache: dict[str, tuple[float, str]] = {}


def _read_with_cache(file_path: str) -> str:
    """读取文件全内容（优先从缓存获取，mtime 变化时重新读取）。"""
    p = Path(file_path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0
    entry = _cache.get(file_path)
    if entry is not None and entry[0] == mtime:
        return entry[1]
    text = load_file(file_path)
    _cache[file_path] = (mtime, text)
    return text


def detect_encoding(file_path: str) -> str:
    """尝试检测文件编码，返回第一个成功的编码名。

    依次尝试常用中文编码，最终回退到 latin-1（不会抛出解码错误）。
    """
    raw = Path(file_path).read_bytes()
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "latin-1"


def load_file(file_path: str) -> str:
    """加载文件全部内容，自动检测编码。"""
    encoding = detect_encoding(file_path)
    with open(file_path, "r", encoding=encoding, errors="replace") as f:
        return f.read()


def load_file_chunked(file_path: str, offset: int = 0, size: int = CHUNK_SIZE) -> tuple[str, int, bool]:
    """分块加载文件内容（通过缓存避免重复读取全文件）。

    Args:
        file_path: 文件路径
        offset: 起始字符位置
        size: 读取字符数

    Returns:
        (text_chunk, next_offset, has_more)
    """
    text = _read_with_cache(file_path)
    end = min(offset + size, len(text))
    chunk = text[offset:end]
    has_more = end < len(text)
    return chunk, end, has_more


def get_file_info(file_path: str) -> dict:
    """获取文件基本信息（复用缓存，不再重复读取）。"""
    p = Path(file_path)
    text = _read_with_cache(file_path)
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    return {
        "name": p.name,
        "path": str(p.absolute()),
        "size_bytes": p.stat().st_size,
        "encoding": detect_encoding(file_path),
        "lines": lines,
        "chars": len(text),
    }
