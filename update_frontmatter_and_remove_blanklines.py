#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""先迁移文章别名/标签到 FrontMatter，再清理 Markdown 空白行。

双击：自动识别 Windows 上最近使用的 Obsidian 窗口当前笔记，处理后显示汇总。
命令行：python update_frontmatter_and_remove_blanklines.py "文件或文件夹路径"
文件夹只处理当前层级的 .md 文件。直接更新原文件，不生成 .bak 备份。
依赖：PyYAML；图形界面还需要 Python 自带的 Tkinter。
"""

import os
import json
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import yaml


ALIAS_PATTERNS = [
    r'[#]{1,6}\s*[📝]?文章别名[：:]*\s*$',
    r'[#]{1,6}\s*文章别名[：:]*\s*$',
    r'[#]{1,6}\s*别名[:：]*\s*$',
    r'[-]{3,}\s*文章别名\s*[-]{3,}\s*$',
    r'📝\s*文章别名[：:]*\s*$',
    r'文章别名',
]
TAG_PATTERNS = [
    r'[#]{1,6}\s*[🎯🌱]?文章标签[：:]*\s*$',
    r'[#]{1,6}\s*文章标签[：:]*\s*$',
    r'[#]{1,6}\s*标签提取[：:]*\s*$',
    r'[#]{1,6}\s*标签[:：]*\s*$',
    r'[-]{3,}\s*文章标签\s*[-]{3,}\s*$',
    r'🌱\s*标签提取[：:]*\s*$',
    r'🎯\s*文章标签[：:]*\s*$',
    r'文章标签',
    r'标签提取',
]
LIST_ITEM = re.compile(r'^\s*(?:[-*]|\d+\.)\s+(\S.*)$')
FENCE = re.compile(r'^[ \t]*(?:>[ \t]*)*(`{3,}|~{3,})([^\r\n]*)$')
HTML_TAG = re.compile(
    r'<!--[\s\S]*?-->|<(?P<close>/)?(?P<tag>[A-Za-z][\w-]*)\b[^>]*>'
)
VOID_TAGS = set('area base br col embed hr img input link meta param source track wbr'.split())


@dataclass
class ProcessingResult:
    path: Path
    status: str  # modified / unchanged / failed
    added_aliases: int = 0
    added_tags: int = 0
    removed_blank_lines: int = 0
    error: Optional[str] = None


def split_frontmatter(content: str) -> Tuple[dict, str, str]:
    """仅识别文件开头的 FrontMatter；出错时阻止整个文件写入。"""
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        return {}, '', content
    for index in range(1, len(lines)):
        if lines[index].strip() == '---':
            raw = ''.join(lines[:index + 1])
            data = yaml.safe_load(''.join(lines[1:index]))
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise ValueError('FrontMatter 必须是 YAML 字段映射，不能是列表或单个值')
            return data, raw, ''.join(lines[index + 1:])
    raise ValueError('FrontMatter 缺少结束分隔符 ---')


def protected_lines(body: str) -> List[bool]:
    """标记代码块、表格、HTML；同时供提取和空行清理使用。

    使用位置标记，不用文本占位符，正文里的类似占位符不会被替换。
    未关闭的代码/HTML 保守保护到文件结尾。
    """
    lines = body.splitlines(keepends=True)
    protected = [False] * len(lines)
    offsets = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)

    index = 0
    while index < len(lines):
        opening = FENCE.match(lines[index].rstrip('\r\n'))
        if not opening:
            index += 1
            continue
        marker = opening.group(1)
        end = index + 1
        while end < len(lines):
            closing = FENCE.match(lines[end].rstrip('\r\n'))
            if (closing and closing.group(1)[0] == marker[0]
                    and len(closing.group(1)) >= len(marker)
                    and not closing.group(2).strip()):
                end += 1
                break
            end += 1
        protected[index:end] = [True] * (end - index)
        index = end

    # 在代码以外匹配 HTML，栈用于保留同名嵌套标签的整个外层区域。
    html_source = ''.join(
        line if not protected[i] else ' ' * len(line)
        for i, line in enumerate(lines)
    )
    spans = []
    stack = []
    html_start = None
    for match in HTML_TAG.finditer(html_source):
        if match.group().startswith('<!--'):
            spans.append(match.span())
            continue
        name = match.group('tag').lower()
        if name in VOID_TAGS or match.group().endswith('/>'):
            spans.append(match.span())
            continue
        if not match.group('close'):
            if not stack:
                html_start = match.start()
            stack.append(name)
        elif name in stack:
            # 容忍 HTML 中省略的关闭标签，匹配最近同名的打开标签。
            position = len(stack) - 1 - stack[::-1].index(name)
            del stack[position:]
            if not stack:
                spans.append((html_start, match.end()))
                html_start = None
    if stack:
        spans.append((html_start, len(body)))
    span_index = 0
    spans.sort()
    for i, start in enumerate(offsets):
        end = start + len(lines[i])
        while span_index < len(spans) and spans[span_index][1] <= start:
            span_index += 1
        if span_index < len(spans) and spans[span_index][0] < end:
            protected[i] = True

    # 沿用原工具带首尾竖线的表格识别范围。
    for i in range(len(lines) - 1):
        if protected[i] or protected[i + 1]:
            continue
        if (re.fullmatch(r'\|[^\r\n]+\|', lines[i].strip())
                and re.fullmatch(r'\|[- \t:|]+\|', lines[i + 1].strip())):
            end = i + 2
            while end < len(lines) and re.fullmatch(r'\|[^\r\n]+\|', lines[end].strip()):
                end += 1
            protected[i:end] = [True] * (end - i)

    # 保留受保护块相邻的一行空行，避免破坏 Markdown 渲染边界。
    core = protected[:]
    for i, keep in enumerate(core):
        if keep:
            for neighbor in (i - 1, i + 1):
                if 0 <= neighbor < len(lines) and not lines[neighbor].strip():
                    protected[neighbor] = True
    return protected


def section_key(line: str) -> Optional[str]:
    if LIST_ITEM.match(line):
        return None
    for key, patterns in [('aliases', ALIAS_PATTERNS), ('tags', TAG_PATTERNS)]:
        if any(re.search(pattern, line.strip(), re.IGNORECASE) for pattern in patterns):
            return key
    return None


def migrate_frontmatter(content: str) -> Tuple[str, int, int]:
    data, raw_header, body = split_frontmatter(content)
    lines = body.splitlines(keepends=True)
    protected = protected_lines(body)
    extracted = {'aliases': [], 'tags': []}
    deleted = set()
    index = 0
    while index < len(lines):
        key = None if protected[index] else section_key(lines[index])
        if key is None:
            index += 1
            continue
        start = index
        cursor = start + 1
        while cursor < len(lines) and not protected[cursor] and not lines[cursor].strip():
            cursor += 1
        items = []
        while cursor < len(lines) and not protected[cursor]:
            match = LIST_ITEM.match(lines[cursor].rstrip('\r\n'))
            if not match:
                break
            items.append(match.group(1).strip())
            cursor += 1
        if items:
            extracted[key].extend(items)
            deleted.update(range(start, cursor))
            index = cursor
        else:
            # 空标题不能成为删除正文的理由。
            index += 1

    if not deleted:
        return content, 0, 0
    counts = {'aliases': 0, 'tags': 0}
    for key, items in extracted.items():
        if not items:
            continue
        existing = data.get(key, [])
        if existing is None:
            existing = []
        elif isinstance(existing, str):
            existing = [existing]
        if not isinstance(existing, list):
            raise ValueError(f'FrontMatter 的 {key} 必须是字符串或列表，已跳过以保护原值')
        merged = []
        for value in existing:
            if value not in merged:
                merged.append(value)
        for value in items:
            if value not in merged:
                merged.append(value)
                counts[key] += 1
        data[key] = merged

    # 仅当数据变化时重新序列化；仅移动重复项时也能保留原 YAML 注释和排版。
    original_data, _, _ = split_frontmatter(content)
    if raw_header and data == original_data:
        header = raw_header
    else:
        newline = '\r\n' if '\r\n' in content else '\n'
        serialized = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        header = ('---\n' + serialized + '---\n').replace('\n', newline)
    body = ''.join(line for i, line in enumerate(lines) if i not in deleted)
    return header + body, counts['aliases'], counts['tags']


def remove_blanklines(content: str) -> str:
    """删除非保护区域的空行；保留非空行本身及其原有换行符。"""
    _, header, body = split_frontmatter(content)
    lines = body.splitlines(keepends=True)
    protected = protected_lines(body)
    # 延续原脚本规则：正文与 --- 之间的空行需要保留。
    for i, line in enumerate(lines):
        if line.strip() == '---' and not protected[i]:
            cursor = i - 1
            while cursor >= 0 and not lines[cursor].strip():
                protected[cursor] = True
                cursor -= 1
    return header + ''.join(
        line for i, line in enumerate(lines) if line.strip() or protected[i]
    )


def atomic_write(path: Path, data: bytes, original: bytes) -> None:
    """原子替换原文件；临时文件在成功或失败后清理，不保留备份副本。"""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent,
                                         prefix=f'.{path.name}.', suffix='.tmp',
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        if path.read_bytes() != original:
            raise RuntimeError('文件在处理过程中被其他程序修改，已取消写回')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def process_file(file_path: Path) -> ProcessingResult:
    path = Path(file_path)
    result = ProcessingResult(path=path, status='failed')
    try:
        if path.suffix.lower() != '.md' or not path.is_file():
            raise ValueError(f'不是有效的 Markdown 文件：{path}')
        if path.is_symlink():
            raise ValueError('为避免替换符号链接，请直接选择其目标 Markdown 文件')
        original = path.read_bytes()
        # utf-8-sig 同时读取带 BOM/不带 BOM 的文件，写回时保留原有 BOM。
        content = original.decode('utf-8-sig')
        migrated, added_aliases, added_tags = migrate_frontmatter(content)
        cleaned = remove_blanklines(migrated)
        removed = (sum(not line.strip() for line in migrated.splitlines())
                   - sum(not line.strip() for line in cleaned.splitlines()))
        output = cleaned.encode('utf-8')
        if original.startswith(b'\xef\xbb\xbf'):
            output = b'\xef\xbb\xbf' + output
        if output == original:
            result.status = 'unchanged'
            return result
        if path.read_bytes() != original:
            raise RuntimeError('文件在处理过程中被其他程序修改，已取消写回')
        atomic_write(path, output, original)
        result.status = 'modified'
        result.added_aliases = added_aliases
        result.added_tags = added_tags
        result.removed_blank_lines = removed
    except Exception as exc:
        result.error = str(exc)
    return result


def process_path(path: Path) -> List[ProcessingResult]:
    path = Path(path)
    if not path.exists():
        raise ValueError(f'路径不存在：{path}')
    if path.is_file():
        return [process_file(path)]
    if not path.is_dir():
        raise ValueError(f'不是文件或文件夹：{path}')
    files = sorted((p for p in path.iterdir() if p.is_file() and p.suffix.lower() == '.md'),
                   key=lambda p: p.name.casefold())
    if not files:
        raise ValueError(f'文件夹当前层级没有 Markdown 文件：{path}')
    return [process_file(p) for p in files]


def format_summary(results: List[ProcessingResult]) -> str:
    lines = [
        '处理顺序：迁移标签和别名 → 清理空白行',
        f'文件共 {len(results)} 个；修改：{sum(r.status == "modified" for r in results)}；'
        f'未变化：{sum(r.status == "unchanged" for r in results)}；'
        f'失败：{sum(r.status == "failed" for r in results)}',
        f'实际新增别名：{sum(r.added_aliases for r in results)} 个',
        f'实际新增标签：{sum(r.added_tags for r in results)} 个',
        f'删除空白行：{sum(r.removed_blank_lines for r in results)} 行',
        '已直接更新原 Markdown 文件，不生成备份副本。',
    ]
    for result in results:
        if result.error:
            lines.append(f'失败：{result.path.name}：{result.error}')
    return '\n'.join(lines)


def get_obsidian_window_titles() -> List[str]:
    """按 Windows 窗口 Z 序取得 Obsidian 标题，包括最小化的窗口。"""
    if sys.platform != 'win32':
        raise ValueError('自动识别当前笔记仅支持 Windows；其他系统请使用命令行指定路径')
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    titles = []

    @callback_type
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        if not re.search(r' - Obsidian(?:\s|$)', title.value):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = kernel32.OpenProcess(0x1000, False, pid.value)
        if process:
            try:
                size = wintypes.DWORD(32768)
                executable = ctypes.create_unicode_buffer(size.value)
                if (kernel32.QueryFullProcessImageNameW(process, 0, executable, ctypes.byref(size))
                        and Path(executable.value).name.casefold() == 'obsidian.exe'):
                    titles.append(title.value)
            finally:
                kernel32.CloseHandle(process)
        return True

    if not user32.EnumWindows(visit, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return titles


def detect_current_markdown(config_path: Optional[Path] = None,
                            window_titles: Optional[List[str]] = None) -> Path:
    """用实时窗口标题和仓库注册信息定位文件；有歧义时绝不猜测。"""
    titles = get_obsidian_window_titles() if window_titles is None else window_titles
    if not titles:
        raise ValueError('未找到正在运行的 Obsidian 笔记窗口，请先在 Obsidian 中打开 Markdown 文章')
    if config_path is None:
        appdata = os.environ.get('APPDATA')
        if not appdata:
            raise ValueError('找不到 APPDATA，无法读取 Obsidian 仓库注册信息')
        config_path = Path(appdata) / 'obsidian' / 'obsidian.json'
    try:
        config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        vaults = config['vaults']
        if not isinstance(vaults, dict):
            raise ValueError('vaults 不是对象')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f'无法读取 Obsidian 仓库配置：{config_path}（{exc}）') from exc

    # 第一个窗口是 Z 序最高的 Obsidian 窗口；不跳过它去处理其他窗口。
    title = re.sub(r' - Obsidian(?:\s.*)?$', '', titles[0])
    matches = []
    for entry in vaults.values():
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            continue
        vault = Path(entry['path'])
        suffix = ' - ' + vault.name
        if title.endswith(suffix):
            matches.append((vault, title[:-len(suffix)]))
    if len(matches) != 1:
        raise ValueError('无法从窗口标题唯一确定 Obsidian 仓库（可能存在同名仓库）')
    vault, note_name = matches[0]
    vault = vault.resolve(strict=True)
    candidates = []
    visited_directories = set()

    def scan_error(error):
        if isinstance(error, FileNotFoundError):
            # 失效目录连接点不包含可处理的文件。
            return
        # 部分目录不可读时不能认定笔记名唯一。
        raise ValueError(f'无法完整检查仓库，已停止以避免误选文件：{error}')

    for directory, folders, filenames in os.walk(vault, onerror=scan_error, followlinks=False):
        real_directory = Path(directory).resolve(strict=True)
        if real_directory in visited_directories:
            folders[:] = []
            continue
        visited_directories.add(real_directory)
        # 支持 Obsidian 内通过目录连接点导入的文章，同时阻止连接点循环。
        folders[:] = [name for name in folders if not name.startswith('.')
                      and not (Path(directory) / name).is_symlink()]
        for name in filenames:
            path = Path(directory) / name
            if path.suffix.lower() != '.md' or path.stem != note_name or path.is_symlink():
                continue
            candidates.append(path)
    if not candidates:
        raise ValueError('当前窗口没有可唯一定位的 Markdown 文章，请切换到已保存的 .md 文章后重试')
    if len(candidates) != 1:
        raise ValueError('仓库中存在同名 Markdown 文章，已停止以避免误处理；可用命令行指定完整路径')
    return candidates[0]


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) > 1:
        print('用法：python update_frontmatter_and_remove_blanklines.py "文件或文件夹路径"',
              file=sys.stderr)
        return 1
    root = None
    try:
        if arguments:
            path_text = arguments[0]
        else:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path_text = str(detect_current_markdown())
            print(f'自动识别 Obsidian 当前文章：{path_text}')
        path = Path(path_text.strip().strip('"').strip("'")).expanduser()
        results = process_path(path)
        for result in results:
            print(f'{result.status}: {result.path}')
        summary = format_summary(results)
        if not arguments:
            summary = f'当前文章：{path}\n\n' + summary
        print(summary)
        failed = any(r.status == 'failed' for r in results)
        if root is not None:
            from tkinter import messagebox
            show = messagebox.showwarning if failed else messagebox.showinfo
            show('处理结果', summary, parent=root)
        return 1 if failed else 0
    except Exception as exc:
        print(f'错误：{exc}', file=sys.stderr)
        if root is not None:
            from tkinter import messagebox
            messagebox.showerror('处理失败', str(exc), parent=root)
        return 1
    finally:
        if root is not None:
            root.destroy()


if __name__ == '__main__':
    for output_stream in (sys.stdout, sys.stderr):
        if hasattr(output_stream, 'reconfigure'):
            output_stream.reconfigure(encoding='utf-8')
    sys.exit(main())
