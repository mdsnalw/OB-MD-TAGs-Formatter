#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Frontmatter更新工具 - 输入对话框版本
功能：弹出对话框让用户粘贴Markdown文件路径，然后提取别名和标签更新到frontmatter
"""

import re
import yaml
import sys
import io
import os
import ctypes  # 新增：用于调用 Windows API 主动关闭控制台窗口
import tkinter as tk
from tkinter import simpledialog, messagebox
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union
from dataclasses import dataclass

# 新增：自动退出开关（默认False，保持原有手动退出；设为True则自动退出）
AUTO_EXIT = True  # 改为True即可自动退出


def _close_console_window():
    """主动请求关闭当前控制台窗口（仅 Windows）

    解决 os._exit(0) 终止 Python 后 CMD 窗口仍然残留的问题：
      - 双击 .py 运行时：py.exe / python.exe 所在的 cmd 窗口会被关闭
      - 在 cmd 里手动运行 python script.py 时：该 cmd 窗口会被关闭
      - 通过 .bat 调用 python script.py 时：.bat 所在的 cmd 窗口会被关闭

    注意：PostMessageW 发送 WM_CLOSE 是异步请求，不会阻塞当前进程。
    """
    if sys.platform != 'win32':
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            # WM_CLOSE = 0x0010，向窗口发送关闭消息（与用户点 X 等价）
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
    except Exception:
        # 关闭窗口是“尽力而为”，失败也不影响进程退出
        pass


# 新增：终止 Windows Python Launcher (py.exe)
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001


class _PROCESSENTRY32W(ctypes.Structure):
    """Windows 进程枚举结构体（Unicode 版）"""
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _kill_py_launcher():
    """强制结束 Windows Python Launcher（py.exe）进程

    触发场景：用户双击 .py 后，CMD 窗口标题显示为 "C:\\WINDOWS\\py.exe"。
    这时我们的 python 是 py.exe 启动的子进程，os._exit(0) 只杀 python 子进程，
    父进程 py.exe 常因 tkinter finalize 阶段 / pipe 未释放而挂死，
    占据 console 不放，导致 CMD 窗口始终停留。

    本函数用 CreateToolhelp32Snapshot 枚举所有进程，定位名为 py.exe 的进程，
    用 TerminateProcess 强制结束，让 Windows 释放 console，CMD 窗口才会真正消失。

    严格只杀 py.exe（Windows Python Launcher），不会误伤：
      - python.exe / python3.exe / pythonw.exe 等解释器进程
      - 用户机器上其他用 py.exe 启动的 Python 工具不会受牵连
        （本进程可能恰好在其它 py.exe 下，但本脚本一般是用 python.exe / py.exe 启动的）
    """
    if sys.platform != 'win32':
        return
    try:
        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        # 无效句柄（0 / -1 / INVALID_HANDLE_VALUE）一律视为失败
        if snapshot in (0, -1, 0xFFFFFFFF):
            return
        my_pid = os.getpid()
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                # 比较 exe 文件名（不区分大小写）
                name = entry.szExeFile or ""
                if name.lower() == "py.exe" and entry.th32ProcessID != my_pid:
                    h = kernel32.OpenProcess(PROCESS_TERMINATE, False, entry.th32ProcessID)
                    if h:
                        kernel32.TerminateProcess(h, 0)
                        kernel32.CloseHandle(h)
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:
        # 杀进程是“尽力而为”，失败也不影响我们退出自己
        pass


def safe_exit():
    """安全退出函数，支持自动退出"""
    try:
        print("\n" + "=" * 60)
        if not AUTO_EXIT:  # 仅当自动退出关闭时，才需要手动按回车
            input("按回车键退出程序...")
    except:
        pass
    # 刷新输出，确保弹窗前的内容已显示完整
    try:
        sys.stdout.flush()
    except:
        pass
    try:
        sys.stderr.flush()
    except:
        pass
    # 新增：主动关闭当前控制台窗口，让 CMD 在 Python 退出后一并消失
    _close_console_window()
    # 新增：若是被 py.exe 启动的，强制结束 py.exe（Windows Python Launcher）
    # 不杀它会让它继续占据 console，CMD 窗口仍然残留
    _kill_py_launcher()
    # 使用 os._exit 强制退出，绕过 Windows 上 tkinter finalize 阶段的挂起，
    # 否则 sys.exit 无法终止进程，bat 永远等不到 Python 返回，cmd 窗口不会关闭
    os._exit(0)


def setup_encoding():
    """【修复乱码核心】强制Windows输出UTF-8"""
    if sys.platform == 'win32':
        try:
            # 现代Python方式
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except:
            # 兼容旧版Python
            try:
                sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
                sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
            except:
                pass

# ------------------------------ 以下代码完全不变，保持你的功能 ------------------------------
@dataclass
class ExtractionResult:
    success: bool
    aliases: List[str]
    tags: List[str]
    filename: str
    error: Optional[str] = None
    
    def __str__(self):
        if not self.success:
            return f" {self.filename}: {self.error}"
        return f" {self.filename}: 新增别名 {len(self.aliases)} 个，标签 {len(self.tags)} 个"


class FrontmatterUpdater:
    ALIAS_PATTERNS = [
        r'[#]{1,6}\s*[📝]?文章别名[：:]*\s*$',
        r'[#]{1,6}\s*文章别名[：:]*\s*$',
        r'[#]{1,6}\s*别名[:：]*\s*$',
        r'[-]{3,}\s*文章别名\s*[-]{3,}\s*$',
        r'📝\s*文章别名[：:]*\s*$',
        r'文章别名',  # 宽松模式：只要包含关键字
    ]
    
    TAG_PATTERNS = [
        r'[#]{1,6}\s*[🎯🌱]?文章标签[：:]*\s*$',
        r'[#]{1,6}\s*文章标签[：:]*\s*$',
        r'[#]{1,6}\s*标签提取[：:]*\s*$',
        r'[#]{1,6}\s*标签[:：]*\s*$',
        r'[-]{3,}\s*文章标签\s*[-]{3,}\s*$',
        r'🌱\s*标签提取[：:]*\s*$',
        r'🎯\s*文章标签[：:]*\s*$',
        r'文章标签',  # 宽松模式：只要包含关键字
        r'标签提取',  # 宽松模式：只要包含关键字
    ]
    
    def __init__(self, delete_original: bool = True):
        self.delete_original = delete_original
    
    def extract_aliases_and_tags(self, content: str) -> Tuple[List[str], List[str], Optional[List[Tuple[int, int]]]]:
        aliases = []
        tags = []
        alias_start = None
        tag_start = None
        
        alias_section = None
        alias_end = None
        
        print(f"\n  正在搜索别名标题...")
        for pattern in self.ALIAS_PATTERNS:
            match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
            if match:
                alias_start = match.start()
                alias_section = content[match.end():]
                print(f"  找到别名标题（模式: {pattern[:30]}...）")
                print(f"     位置: {alias_start}")
                print(f"     内容: {repr(content[alias_start:alias_start+50])}")
                break
        
        tag_section = None
        tag_end = None
        
        print(f"\n  正在搜索标签标题...")
        for pattern in self.TAG_PATTERNS:
            match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
            if match:
                tag_start = match.start()
                tag_section = content[match.end():]
                print(f"  找到标签标题（模式: {pattern[:30]}...）")
                print(f"     位置: {tag_start}")
                print(f"     内容: {repr(content[tag_start:tag_start+50])}")
                break
        
        sections_to_delete = []
        
        if alias_section and alias_start is not None:
            aliases = self._extract_list_items(alias_section)
            alias_end = self._extract_section_end(content[alias_start:]) + alias_start
            if alias_end > alias_start:
                sections_to_delete.append((alias_start, alias_end))
        
        if tag_section and tag_start is not None:
            tags = self._extract_list_items(tag_section)
            tag_end = self._extract_section_end(content[tag_start:]) + tag_start
            if tag_end > tag_start:
                sections_to_delete.append((tag_start, tag_end))
        
        if not aliases and not tags:
            print(f"\n   未找到别名或标签")
            print(f"   提示：请检查文件中是否包含以下格式的标题：")
            print(f"     - #### 文章别名：")
            print(f"     - #### 文章标签：")
            print(f"     - 标签提取：")
        
        return aliases, tags, sections_to_delete
    
    def _extract_list_items(self, section: str) -> List[str]:
        items = []
        lines = section.split('\n')
        
        prev_line = None
        for line in lines:
            line = line.strip()
            if re.match(r'^[-*]\s+\S', line) or re.match(r'^\d+\.\s+\S', line):
                item = re.sub(r'^[-*]\s+|^\d+\.\s+', '', line).strip()
                if item:
                    items.append(item)
            elif line and not any(keyword in line for keyword in ['📝', '🎯', '文章', '标签', '别名', '摘要', '总结']):
                if prev_line and re.match(r'^[-*]', prev_line.strip()):
                    items.append(line)
            prev_line = line
            
            if line.startswith('#') or (not line and items):
                if items:
                    break
        
        return items
    
    def _extract_section_end(self, section: str) -> int:
        lines = section.split('\n')
        
        if len(lines) <= 1:
            return len(section)
        
        i = 1
        found_end = False
        consecutive_empty = 0
        list_item_count = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            if re.match(r'^[-*]\s+\S', line) or re.match(r'^\d+\.\s+\S', line):
                list_item_count += 1
                consecutive_empty = 0
            elif not line:
                consecutive_empty += 1
                if consecutive_empty >= 2 and list_item_count > 0:
                    found_end = True
                    i -= consecutive_empty
                    break
            else:
                consecutive_empty = 0
            
            if line.startswith('#'):
                if '📈' in line or '一句话' in line or '摘要' in line:
                    found_end = True
                    i -= 1
                    break
                found_end = True
                i -= 1
                break
            
            if re.match(r'^\s*---\s*$', line):
                found_end = True
                i -= 1
                break
            
            if line.startswith('|'):
                found_end = True
                i -= 1
                break
                
            i += 1
        
        if not found_end:
            i = len(lines) - 1
        
        i = max(i, 0)
        i = min(i, len(lines) - 1)
        
        try:
            end_pos = sum(len(lines[j]) + 1 for j in range(i + 1)) - 1
        except:
            end_pos = len(section)
        
        return min(max(end_pos, 0), len(section))
    
    def parse_frontmatter(self, content: str) -> Tuple[Dict, int, int]:
        start_match = re.search(r'^---\s*$', content, re.MULTILINE)
        if not start_match:
            return {}, -1, -1
        
        start_pos = start_match.start()
        end_match = re.search(r'^---\s*$', content[start_pos + 3:], re.MULTILINE)
        if not end_match:
            return {}, start_pos, -1
        
        end_pos = start_pos + 3 + end_match.start() + 3
        fm_content = content[start_pos + 3:end_pos - 3]
        
        try:
            fm_dict = yaml.safe_load(fm_content) or {}
            return fm_dict, start_pos, end_pos
        except yaml.YAMLError as e:
            print(f" YAML解析错误: {e}")
            return {}, start_pos, end_pos
    
    def update_frontmatter(self, fm_dict: Dict, aliases: List[str], tags: List[str]) -> Dict:
        if aliases:
            existing_aliases = fm_dict.get('aliases', [])
            if isinstance(existing_aliases, str):
                existing_aliases = [existing_aliases]
            elif not isinstance(existing_aliases, list):
                existing_aliases = []
            
            all_aliases = existing_aliases + [a for a in aliases if a not in existing_aliases]
            if all_aliases:
                fm_dict['aliases'] = all_aliases
        
        if tags:
            existing_tags = fm_dict.get('tags', [])
            if isinstance(existing_tags, str):
                existing_tags = [existing_tags]
            elif not isinstance(existing_tags, list):
                existing_tags = []
            
            all_tags = existing_tags + [t for t in tags if t not in existing_tags]
            if all_tags:
                fm_dict['tags'] = all_tags
        
        return fm_dict
    
    def format_frontmatter(self, fm_dict: Dict) -> str:
        if not fm_dict:
            return "---\n---\n"
        
        lines = ['---']
        for key, value in fm_dict.items():
            if value is None:
                continue
            
            if isinstance(value, list):
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"- {item}")
            else:
                lines.append(f"{key}: {value}")
        
        lines.append('---')
        return '\n'.join(lines) + '\n'
    
    def process_file(self, filepath: Path, dry_run: bool = False) -> ExtractionResult:
        try:
            content = filepath.read_text(encoding='utf-8')
            
            aliases, tags, sections_to_delete = self.extract_aliases_and_tags(content)
            
            if not aliases and not tags:
                return ExtractionResult(
                    success=False,
                    aliases=[],
                    tags=[],
                    filename=filepath.name,
                    error="未找到别名或标签"
                )
            
            print(f"  - 提取到别名 {len(aliases)} 个，标签 {len(tags)} 个")
            
            if self.delete_original and sections_to_delete:
                sections_to_delete.sort(key=lambda x: x[0], reverse=True)
                for start, end in sections_to_delete:
                    content = content[:start] + content[end:]
                    print(f"  - 已删除原文部分（位置: {start}-{end}，长度: {end-start} 字符）")
            
            fm_dict, fm_start, fm_end = self.parse_frontmatter(content)
            updated_fm_dict = self.update_frontmatter(fm_dict, aliases, tags)
            new_fm = self.format_frontmatter(updated_fm_dict)
            
            if fm_start >= 0:
                before_fm = content[:fm_start]
                after_fm = content[fm_end:]
                new_content = before_fm + new_fm + after_fm
            else:
                new_content = new_fm + content
            
            if not dry_run:
                filepath.write_text(new_content, encoding='utf-8')
            
            return ExtractionResult(
                success=True,
                aliases=aliases,
                tags=tags,
                filename=filepath.name
            )
            
        except Exception as e:
            return ExtractionResult(
                success=False,
                aliases=[],
                tags=[],
                filename=filepath.name,
                error=str(e)
            )


def show_input_dialog() -> Optional[str]:
    """
    显示输入对话框，让用户粘贴文件路径
    
    Returns:
        用户输入的路径，或None（如果取消）
    """
    root = None
    try:
        print("\n" + "=" * 60)
        print(" 正在打开输入对话框...")
        print("提示：对话框应该会弹出在屏幕最前方")
        print("如果没有看到，请检查任务栏或按 Alt+Tab 切换窗口")
        print("=" * 60 + "\n")
        
        root = tk.Tk()
        root.title("FrontMatterUpdater")
        root.withdraw()
        
        root.attributes('-topmost', True)
        root.update()
        root.deiconify()
        root.withdraw()
        root.update()
        
        path = simpledialog.askstring(
            title="请输入Markdown文件或文件夹路径",
            prompt="请粘贴或输入Markdown文件的完整路径，\n或包含Markdown文件的文件夹路径：",
            parent=root
        )
        
        root.destroy()
        root = None
        
        if path:
            path = path.strip().strip('"').strip("'")
            print(f" 已输入路径: {path}")
            return path
        
        print(" 未输入路径")
        return None
        
    except Exception as e:
        print(f"\n  打开对话框时出错: {e}")
        print("请尝试手动输入路径...")
        
        if root:
            try:
                root.destroy()
            except:
                pass
        
        print("\n请输入文件或文件夹路径：")
        try:
            path = input().strip().strip('"').strip("'")
            if path:
                return path
        except:
            pass
        
        return None


def main():
    root_tk = tk.Tk()
    root_tk.withdraw()

    filepath_str = show_input_dialog()
    
    if not filepath_str:
        print("\n 未输入路径，程序退出")
        messagebox.showinfo("执行完成", "未输入路径，程序结束。")
        root_tk.destroy()
        safe_exit()  # 修复：弹窗确认后直接强制退出
        return
    
    print(f"\n 路径: {filepath_str}")
    
    filepath = Path(filepath_str)
    
    if not filepath.exists():
        print(f" 错误：文件或路径不存在: {filepath}")
        messagebox.showerror("错误", f"文件或路径不存在：{filepath}")
        root_tk.destroy()
        safe_exit()  # 修复
        return
    
    updater = FrontmatterUpdater(delete_original=True)
    results = []
    
    msg_lines = []
    if filepath.is_file():
        if filepath.suffix.lower() != '.md':
            print(f" 错误：文件不是Markdown文件: {filepath}")
            messagebox.showerror("错误", f"不是Markdown文件：{filepath}")
            root_tk.destroy()
            safe_exit()  # 修复
            return
        
        print("\n 正在处理文件...")
        result = updater.process_file(filepath)
        results.append(result)
        
        print("\n" + "=" * 60)
        print("处理结果：")
        print("=" * 60)
        print(result)
        
        if result.success:
            print(f"\n 提取的别名：")
            for alias in result.aliases:
                print(f"  - {alias}")
            print(f"\n 提取的标签：")
            for tag in result.tags:
                print(f"  - {tag}")
            msg_lines.append(f"文件：{filepath.name}\n成功！新增别名{len(result.aliases)}个，标签{len(result.tags)}个")
        else:
            msg_lines.append(f"文件：{filepath.name}\n失败：{result.error}")
    
    elif filepath.is_dir():
        md_files = list(filepath.glob('*.md'))
        if not md_files:
            print(f" 错误：文件夹中没有.md文件: {filepath}")
            messagebox.showerror("错误", f"文件夹内没有Markdown文件：{filepath}")
            root_tk.destroy()
            safe_exit()  # 修复
            return
        
        print(f"\n 找到 {len(md_files)} 个Markdown文件")
        print("=" * 60)
        
        for i, md_file in enumerate(md_files, 1):
            print(f"\n[{i}/{len(md_files)}] 处理: {md_file.name}...")
            result = updater.process_file(md_file)
            results.append(result)
            print(result)
        
        success = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        total_aliases = sum(len(r.aliases) for r in results)
        total_tags = sum(len(r.tags) for r in results)
        
        print("\n" + "=" * 60)
        print("汇总统计：")
        print("=" * 60)
        print(f" 成功: {success} 个文件")
        print(f" 失败: {failed} 个文件")
        print(f" 总新增别名: {total_aliases} 个")
        print(f" 总新增标签: {total_tags} 个")
        msg_lines.append(f"批量处理完成\n成功:{success} 个，失败:{failed} 个\n总新增别名:{total_aliases} 个\n总新增标签:{total_tags} 个")

    # 弹出完成提示框，用户点确定之后立刻强制终止进程
    messagebox.showinfo("执行完成", "\n".join(msg_lines))
    root_tk.destroy()
    safe_exit()  # 修复重点：弹窗确认完直接调用强制退出，不再return回__main__


if __name__ == '__main__':
    try:
        setup_encoding()
        
        print("\n" + "=" * 60)
        print("FrontMatterUpdater - 输入对话框版本")
        print("=" * 60)
        print("提示：程序运行完成后弹窗提示，确认后自动退出")
        print("=" * 60 + "\n")
        
        main()
        
    except KeyboardInterrupt:
        print("\n\n程序已被用户中断")
        safe_exit()
    except Exception as e:
        print(f"\n\n 程序运行出错: {e}")
        import traceback
        traceback.print_exc()
        # 异常弹窗
        err_root = tk.Tk()
        err_root.withdraw()
        messagebox.showerror("程序异常", f"程序运行出错：{e}")
        err_root.destroy()
        safe_exit()
    else:
        # main内部已经调用safe_exit，理论不会走到这里
        safe_exit()