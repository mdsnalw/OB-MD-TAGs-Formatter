# OB-MD-TAGs-Formatter

为 Obsidian Markdown 笔记整理 FrontMatter，并清理正文空行。

## 功能

- 将正文中的“文章别名”“文章标签”等列表迁移到 FrontMatter 的 `aliases`、`tags`，自动去重。
- 从正文末尾向前查找独立的 `Author: 作者名` 行，补充 FrontMatter 的 `author`，保留正文作者行；运行汇总显示实际补充作者的篇数。
- 清理正文空行，保护 FrontMatter、代码块、HTML、表格及必要的相邻空行。
- Windows 下无参数运行时，自动识别 Obsidian 当前文章，无需选择路径。
- 支持命令行指定单个文件或文件夹；文件夹只处理当前层级 `.md` 文件。
- 直接更新原 Markdown 文件，不生成 `.bak` 副本；未变化的文件不写回。
- 无效 YAML、同名笔记识别歧义或写入期间的并发修改会阻止覆盖。

## 安装

使用 Python 3.9 或更高版本，自动识别和结果弹窗需要 Windows 与 Tkinter。
本项目已在 Windows / Python 3.12 下验证。

```powershell
git clone https://github.com/mdsnalw/OB-MD-TAGs-Formatter.git
cd OB-MD-TAGs-Formatter
python -m pip install -r requirements.txt
```

Tkinter 通常随 Windows 官方 Python 安装程序提供，不通过 pip 安装。

## 使用

在 Obsidian 中点击目标文章，等待自动保存后运行：

```powershell
python update_frontmatter_and_remove_blanklines.py
```

程序识别 Windows 窗口层级最靠前的 Obsidian 窗口，通过真实窗口标题和仓库注册信息定位当前 Markdown 文件，执行整理并显示结果。
支持目录连接点映射的外部笔记目录，跳过失效连接点并防止循环遍历。
如果存在同名笔记、同名仓库或无法识别的窗口标题，程序会停止并提示错误。
处理期间避免编辑或切换目标文章。

也可显式指定路径，此模式将结果输出到终端：

```powershell
python update_frontmatter_and_remove_blanklines.py "D:\笔记\文章.md"
python update_frontmatter_and_remove_blanklines.py "D:\笔记\待整理文件夹"
```

正常完成退出码为 `0`，识别或处理失败为 `1`。
合并 YAML 时可能规范化排版并移除 YAML 注释；仅清理空行时保留原有 FrontMatter 排版。
写回采用原子替换，临时文件在操作结束后清理；以前生成的 `.bak` 文件保持原样。

作者提取兼容 `Author` 大小写、英文或中文冒号，并去除作者名首尾空白；有多条时取最后一条非空值。跳过代码块、HTML、表格、引用和列表中的作者示例。
仅在 `author` 缺失、为 null 或为空白字符串时补充，已有非空作者保持原样；未找到作者时不新增字段。
例如正文末尾的 `Author: 青临同学` 会补充为：

```yaml
author: 青临同学
```

## 文件

| 文件 | 用途 |
| --- | --- |
| `update_frontmatter_and_remove_blanklines.py` | 推荐入口，完成自动识别和合并整理 |
| `test_update_frontmatter_and_remove_blanklines.py` | 使用临时样本的回归测试 |
| `update_frontmatter_with_input_dialog.py` | 保留的旧版 FrontMatter 脚本 |
| `remove_blanklines_backup.py` | 保留的旧版空行清理脚本 |
| `使用说明.md` | 详细说明和原开发机器运行记录 |

旧版脚本保持原有行为；建议使用推荐入口获得自动识别、直接更新和错误保护。

## 验证

```powershell
python -m unittest discover -v
```

测试覆盖迁移、作者提取及已有值保护、空行保护、无备份直接更新、并发修改、自动识别、多窗口、同名拒绝及 Windows 目录连接点。
测试不改写真实 Obsidian 笔记。

## 许可证

[MIT](LICENSE)
