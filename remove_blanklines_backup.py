r"""
Open Code Skill: Markdown 空白行清理工具
功能描述：清理 Markdown 文件中的空白行，保留 Frontmatter、代码块、HTML 标签的原始格式
适用场景：Obsidian 文档格式整理、Markdown 内容规范化
正则规则：\n[\s　]*\n+（兼容全角空格）
"""

import re
import sys
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

# 修复 Windows 控制台 UTF-8 输出乱码（最关键）
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

def remove_blanklines(content: str) -> str:
    """
    清理 Markdown 内容中的空白行，保护 Frontmatter、代码块、HTML 标签
    
    Args:
        content: 待处理的 Markdown 文本内容
    
    Returns:
        清理空白行后的 Markdown 内容
    """
    
    # 第一步：识别并完全保护 Frontmatter（不做任何修改）
    # Frontmatter 规则：文件开头以 --- 开始，到第一个单独的 --- 结束
    # 保留 Frontmatter 内的所有空白行和格式，不做任何处理
    frontmatter = None
    content_part = content
    # 使用更稳健的正则表达式匹配 Frontmatter
    # ^---\r?\n - 开头的 ---
    # [\s\S]*? - Frontmatter 内容（非贪婪匹配，包含所有空白、换行）
    # \r?\n--- - 结尾的 ---（单独一行）
    # \s*(?:\r?\n|$) - --- 后面的空白字符和换行符（可选）
    frontmatter_match = re.match(r"^---\r?\n[\s\S]*?\r?\n---\s*(?:\r?\n|$)", content)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(0)
        content_part = content[len(frontmatter):]
    
    # 第二步：识别并保护代码块（包括代码块前后的空行）
    # 匹配 ```...``` 或 ~~~...~~~ 代码块及其周围的空行
    # 支持带缩进、引用标记（>）和语言标记的代码块（如 ```dataview）
    code_blocks = []
    def save_code_block(match):
        code_blocks.append(match.group(0))
        return f"__CODEBLOCK{len(code_blocks)-1}__"
    
    # 保护 ``` 代码块（支持缩进、引用标记和语言标记，以及多行引用）
    # 匹配：可选换行符 + 可选多个引用标记/空格/制表符 + ``` + 语言标记（可选）+ ... + ``` + 可选换行符
    # 使用负向断言确保不会匹配到代码块内部的```
    content_part = re.sub(r"(?m)^(>[\s ]*|[ \t]*)```[\s\S]*?```", save_code_block, content_part)
    # 保护 ~~~ 代码块（支持缩进、引用标记和语言标记，以及多行引用）
    content_part = re.sub(r"(?m)^(>[\s ]*|[ \t]*)~~~[\s\S]*?~~~", save_code_block, content_part)
    
    # 第三步：识别并保护 Markdown 表格（包括前后的空行）
    # Markdown 表格规则：
    # 1. 表头行以 | 开头，包含多个列
    # 2. 分隔行以 | 开头，包含 ---（可以有 : 对齐标记）
    # 3. 内容行以 | 开头，包含单元格内容
    # 4. 表格前后需要有空行才能正确渲染
    tables = []
    def save_table(match):
        tables.append(match.group(0))
        return f"__TABLE{len(tables)-1}__"
    
    # 保护 Markdown 表格
    # 匹配：表格前后的空行 + 表头行 + 分隔行 + 任意数量的内容行
    # 分隔行格式：| 后面跟着空格，然后是 ---（可以有 : 对齐标记），再是空格和 |
    # 表格前后需要有空行才能正确渲染，所以需要保护这些空行
    content_part = re.sub(r"(?m)(\r?\n)?^(\|[^\n]+\|\r?\n\|[-\s:|]*\|\r?\n(?:\|[^\n]+\|\r?\n?)*)(\r?\n)?", save_table, content_part)
    
    # 第四步：识别并保护 HTML 标签块（包括前后的空行）
    # 匹配 HTML 标签块及其内容（包括多行）
    html_blocks = []
    def save_html_block(match):
        html_blocks.append(match.group(0))
        return f"__HTMLBLOCK{len(html_blocks)-1}__"
    
    # 保护 HTML 块（匹配完整的标签对，包括多行内容）
    # 注意：这是简化版的 HTML 匹配，可能不适用于所有复杂 HTML 结构
    content_part = re.sub(r"<[\w-]+[^>]*>[\s\S]*?<\/[\w-]+>", save_html_block, content_part)
    
    # 第四步：保护文本和三横线分隔符之间的空行
    # 保留格式：文本内容 + 空行 + ---（不要删除这种空行）
    preserved_newlines = []
    def save_preserved_newline(match):
        preserved_newlines.append(match.group(0))
        return f"_PRESERVED_{len(preserved_newlines)-1}_"
    
    # 匹配：非空行 + 空行 + ---（三横线分隔符）
    content_part = re.sub(r"([^\n])\n\s*\n---", save_preserved_newline, content_part)
    
    # 第五步：在非保护区域删除空白行（兼容全角空格）
    # 使用正则表达式 \n[\s　]*\n+ 匹配并移除空白行
    content_part = re.sub(r"\n[\s　]*\n+", "\n", content_part)
    
    # 第六步：恢复文本和三横线之间的空行
    for i, preserved in enumerate(preserved_newlines):
        content_part = content_part.replace(f"_PRESERVED_{i}_", preserved, 1)
    
    # 第七步：移除文档开头和结尾的空白行
    # 清理开头的空白行：^\s*\n
    # 清理结尾的空白行：\n\s*$
    content_part = re.sub(r"^\s*\n", "", content_part)
    content_part = re.sub(r"\n\s*$", "", content_part)
    
    # 第八步：恢复代码块、HTML 块和表格
    # 先恢复表格
    for i, table in enumerate(tables):
        content_part = content_part.replace(f"__TABLE{i}__", table, 1)
    # 再恢复 HTML 块
    for i, html_block in enumerate(html_blocks):
        content_part = content_part.replace(f"__HTMLBLOCK{i}__", html_block, 1)
    # 最后恢复代码块
    for i, code_block in enumerate(code_blocks):
        content_part = content_part.replace(f"__CODEBLOCK{i}__", code_block, 1)
    
    # 第九步：合并 Frontmatter 和内容部分
    if frontmatter:
        # 合并 Frontmatter 和内容部分，保持原有换行符
        # 如果 Frontmatter 已包含结尾的换行符，则不再添加额外的换行符
        if frontmatter.endswith('\n'):
            result = frontmatter + content_part
        else:
            result = frontmatter + "\n" + content_part
    else:
        result = content_part
    
    return result

def select_file_dialog() -> str | None:
    """
    弹出文本输入对话框，让用户粘贴要处理的 Markdown 文件的绝对路径
    
    Returns:
        有效的文件路径，用户取消或验证失败时返回 None
    """
    try:
        root = tk.Tk()
        root.withdraw()
        
        file_path = simpledialog.askstring(
            title="输入 Markdown 文件路径",
            prompt="请粘贴要处理的 Markdown 文件的绝对路径："
        )
        
        root.destroy()
        
        if not file_path:
            return None
        
        if not os.path.exists(file_path):
            messagebox.showerror("错误", f"文件不存在：\n{file_path}")
            return None
        
        if not file_path.lower().endswith('.md'):
            messagebox.showerror("错误", f"不是有效的 .md 文件：\n{file_path}")
            return None
        
        return file_path
    except Exception as e:
        messagebox.showerror("错误", f"无法打开对话框：\n{str(e)}")
        return None

def process_file(file_path: str) -> dict | None:
    """
    处理 Markdown 文件
    
    Args:
        file_path: Markdown 文件路径
    
    Returns:
        处理成功时返回统计信息字典，包含：
        - file_path: 文件路径
        - original_lines: 原始行数
        - new_lines: 新行数
        - removed_lines: 删除空白行数
        - has_frontmatter: Frontmatter 状态（✓ 或 ✗）
        处理失败时返回 None
    """
    try:
        # 读取文件
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查是否是 .md 文件
        if not file_path.lower().endswith('.md'):
            print(f"❌ 错误: 不是有效的 .md 文件")
            return None
        
        # 统计原始行数
        original_lines = len(content.splitlines())
        
        # 处理空白行
        cleaned_content = remove_blanklines(content)
        
        # 统计新行数
        new_lines = len(cleaned_content.splitlines())
        removed_lines = original_lines - new_lines
        
        # 写回文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(cleaned_content)
        
        # 检查是否有 Frontmatter
        has_frontmatter = "✓" if bool(re.match(r"^---\n.*?\n---\s*\n", cleaned_content, re.DOTALL)) else "✗"
        
        # 输出报告
        print(f"✓ 处理完成: {file_path}")
        print(f"  原始行数: {original_lines}")
        print(f"  新行数: {new_lines}")
        print(f"  删除空白行: {removed_lines}")
        print(f"  检测到 Frontmatter: {has_frontmatter} 已保留原始数据")
        
        return {
            "file_path": file_path,
            "original_lines": original_lines,
            "new_lines": new_lines,
            "removed_lines": removed_lines,
            "has_frontmatter": has_frontmatter
        }
        
    except UnicodeDecodeError:
        print(f"❌ 错误: 文件不是 UTF-8 编码")
        return None
    except PermissionError:
        print(f"❌ 错误: 无法访问文件（权限不足）")
        return None
    except FileNotFoundError:
        print(f"❌ 错误: 文件不存在")
        return None
    except Exception as e:
        print(f"❌ 错误: {str(e)}")
        return None

# 快速使用示例
if __name__ == "__main__":
    success = False
    try:
        if len(sys.argv) > 1:
            # 命令行模式：处理指定文件
            file_path = sys.argv[1]
            result = process_file(file_path)
            if result:
                success = True
        else:
            # 图形界面模式：弹出文件选择对话框
            file_path = select_file_dialog()
            
            if file_path:
                # 用户选择了文件，进行处理
                result = process_file(file_path)
                
                # 显示处理完成提示
                if result:
                    success = True
                    message = f"""处理完成: {result['file_path']}
   原始行数: {result['original_lines']}
   新行数: {result['new_lines']}
   删除空白行: {result['removed_lines']}
   检测到 Frontmatter: {result['has_frontmatter']} 已保留原始数据"""
                    messagebox.showinfo("处理完成", message)
            else:
                # 用户取消了操作
                print("已取消操作")
                success = True
    finally:
        # 关键：给批处理返回正确退出码（0=成功，非0=失败）
        if success:
            sys.exit(0)
        else:
            sys.exit(1)