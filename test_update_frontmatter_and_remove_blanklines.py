"""回归测试：只在临时目录中操作 Markdown。"""
import importlib.util
import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import yaml

SCRIPT = Path(__file__).with_name('update_frontmatter_and_remove_blanklines.py')


class ScriptPresenceTests(unittest.TestCase):
    def test_standalone_entrypoint_exists(self):
        self.assertTrue(SCRIPT.is_file(), '缺少已规划的独立合并脚本')


class MarkdownToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('markdown_tool', SCRIPT)
        cls.tool = importlib.util.module_from_spec(spec)
        # dataclass 通过模块名查询类型信息。
        import sys
        sys.modules[spec.name] = cls.tool
        spec.loader.exec_module(cls.tool)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, text, name='笔记.md'):
        path = self.root / name
        path.write_bytes(text.encode('utf-8'))
        return path

    def metadata(self, text):
        return yaml.safe_load(text.split('---', 2)[1])

    def test_script_exists(self):
        self.assertTrue(SCRIPT.is_file(), '缺少已规划的独立合并脚本')

    def test_pipeline_backup_counts_and_idempotence(self):
        original = ('---\ntitle: 原标题\naliases: [旧名]\ntags: 旧标签\n'
                    'enabled: true\ncount: 3\nextra: {a: [1, 2]}\n---\n'
                    '# 正文\n\n内容\n\n#### 文章别名：\n- 旧名\n- 新名\n- 新名\n'
                    '\n#### 文章标签：\n- 旧标签\n- 新标签\n\n## 后续\n\n保留正文\n')
        path = self.write(original)
        result = self.tool.process_file(path)
        self.assertEqual(result.status, 'modified', result.error)
        self.assertEqual((result.added_aliases, result.added_tags), (1, 1))
        self.assertGreater(result.removed_blank_lines, 0)
        text = path.read_text(encoding='utf-8')
        data = self.metadata(text)
        self.assertEqual(data['aliases'], ['旧名', '新名'])
        self.assertEqual(data['tags'], ['旧标签', '新标签'])
        self.assertIs(data['enabled'], True)
        self.assertEqual(data['extra'], {'a': [1, 2]})
        self.assertNotIn('文章别名', text)
        self.assertNotIn('文章标签', text)
        self.assertIn('## 后续\n保留正文', text)
        self.assertEqual(result.backup_path.read_bytes(), original.encode('utf-8'))
        again = self.tool.process_file(path)
        self.assertEqual(again.status, 'unchanged', again.error)
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)

    def test_missing_metadata_still_cleans_and_counts_only_blanks(self):
        path = self.write('甲\n\n　\n\n乙\n')
        result = self.tool.process_file(path)
        self.assertEqual(result.status, 'modified')
        self.assertEqual(result.removed_blank_lines, 3)
        self.assertEqual(path.read_text(encoding='utf-8'), '甲\n乙\n')
        self.assertEqual((result.added_aliases, result.added_tags), (0, 0))

    def test_special_yaml_characters_and_single_section(self):
        for title, key in [('📝 文章别名：', 'aliases'), ('🌱 标签提取：', 'tags')]:
            with self.subTest(key=key):
                path = self.write('正文\n' + title + '\n- a: b\n- #中文\n\n继续正文\n', key + '.md')
                result = self.tool.process_file(path)
                self.assertEqual(result.status, 'modified', result.error)
                text = path.read_text(encoding='utf-8')
                self.assertEqual(self.metadata(text)[key], ['a: b', '#中文'])
                self.assertIn('继续正文', text)

    def test_protected_regions_and_empty_section_are_not_extracted(self):
        regions = [
            '```markdown\n文章别名\n- 不提取\n\n代码\n```\n',
            '> > ~~~text\n> 标签提取\n> - 不提取\n>\n> > ~~~\n',
            '<div>\n文章标签\n- 不提取\n\n<div>嵌套</div>\n\n结尾\n</div>\n',
            '| 名称 | 内容 |\n| --- | --- |\n| 一 | 二 |\n',
        ]
        text = '正文\n\n\n' + '\n'.join(regions) + '\n文章别名\n\n## 后续\n文字\n'
        path = self.write(text)
        result = self.tool.process_file(path)
        output = path.read_text(encoding='utf-8')
        self.assertNotEqual(result.status, 'failed', result.error)
        self.assertFalse(output.startswith('---'))
        for region in regions:
            self.assertIn(region, output)
        self.assertIn('文章别名', output)
        self.assertIn('## 后续\n文字', output)

    def test_frontmatter_is_untouched_when_only_cleaning(self):
        header = '---\n# 注释\ntitle: "标题"\n\ntext: |\n  第一行\n\n  第二行\n---\n'
        path = self.write(header + '\n正文\n\n\n结束\n')
        self.assertEqual(self.tool.process_file(path).status, 'modified')
        self.assertTrue(path.read_text(encoding='utf-8').startswith(header))

    def test_invalid_yaml_or_delimiters_do_not_touch_file(self):
        for index, text in enumerate(['---\ntitle: [broken\n---\n正文\n\n结束',
                                      '---\ntitle: 未关闭\n正文',
                                      '---\n- 列表\n---\n正文',
                                      '---\nfalse\n---\n正文']):
            with self.subTest(text=text):
                path = self.write(text, str(index) + '.md')
                result = self.tool.process_file(path)
                self.assertEqual(result.status, 'failed')
                self.assertEqual(path.read_bytes(), text.encode('utf-8'))
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_no_backups_for_unchanged_or_invalid_paths(self):
        self.assertEqual(self.tool.process_file(self.write('正文\n')).status, 'unchanged')
        self.assertEqual(self.tool.process_file(self.root / 'missing.md').status, 'failed')
        self.assertEqual(self.tool.process_file(self.write('a\n\nb', 'x.txt')).status, 'failed')
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_backup_failure_preserves_original(self):
        path = self.write('一\n\n二\n')
        original = path.read_bytes()
        with patch.object(self.tool, 'create_backup', side_effect=PermissionError('模拟备份失败')):
            result = self.tool.process_file(path)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(path.read_bytes(), original)

    def test_replace_failure_keeps_original_and_backup_and_cleans_temp(self):
        path = self.write('一\n\n二\n')
        original = path.read_bytes()
        with patch.object(self.tool.os, 'replace', side_effect=PermissionError('模拟替换失败')):
            result = self.tool.process_file(path)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(result.backup_path.read_bytes(), original)
        self.assertEqual(sorted(p.suffix for p in self.root.iterdir()), ['.bak', '.md'])

    def test_crlf_bom_and_separator_are_preserved(self):
        path = self.write('\ufeff正文\r\n\r\n---\r\n\r\n甲\r\n\r\n乙\r\n')
        result = self.tool.process_file(path)
        self.assertEqual(result.status, 'modified', result.error)
        data = path.read_bytes()
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        self.assertIn('正文\r\n\r\n---'.encode('utf-8'), data)
        self.assertNotIn(b'\r\r\n', data)
        self.assertNotIn('甲\r\n\r\n乙'.encode('utf-8'), data)

    def test_batch_is_shallow_and_continues_after_error(self):
        self.write('甲\n\n乙', 'a.MD')
        self.write('---\nx: [\n---\n', 'b.md')
        self.write('无变化', 'c.md')
        self.write('不处理', 'd.txt')
        (self.root / 'sub').mkdir()
        child = self.root / 'sub' / 'child.md'
        child.write_text('甲\n\n乙', encoding='utf-8')
        results = self.tool.process_path(self.root)
        self.assertEqual([r.status for r in results], ['modified', 'failed', 'unchanged'])
        self.assertEqual(child.read_text(encoding='utf-8'), '甲\n\n乙')
        summary = self.tool.format_summary(results)
        for expected in ['修改：1', '未变化：1', '失败：1', 'b.md']:
            self.assertIn(expected, summary)

    def test_migration_lines_are_not_counted_as_removed_blanks(self):
        path = self.write('正文\n文章别名\n- 别名一\n- 别名二\n文章标签\n- 标签\n')
        result = self.tool.process_file(path)
        self.assertEqual(result.status, 'modified', result.error)
        self.assertEqual(result.removed_blank_lines, 0)
        self.assertEqual((result.added_aliases, result.added_tags), (2, 1))

    def test_unclosed_fence_and_placeholder_like_text_are_safe(self):
        protected = '````markdown\n文章别名\n- 不提取\n\n```\n\n保持\n'
        path = self.write('__CODEBLOCK0__\n\n_PRESERVED_0_\n\n' + protected)
        result = self.tool.process_file(path)
        self.assertEqual(result.status, 'modified', result.error)
        text = path.read_text(encoding='utf-8')
        self.assertIn('__CODEBLOCK0__', text)
        self.assertIn('_PRESERVED_0_', text)
        self.assertIn(protected, text)
        self.assertFalse(text.startswith('---'))

    def test_concurrent_edit_is_not_overwritten(self):
        path = self.write('甲\n\n乙\n')
        original_backup = self.tool.create_backup

        def backup_and_edit(target, original):
            backup = original_backup(target, original)
            target.write_bytes('其他程序刚写入的内容'.encode('utf-8'))
            return backup

        with patch.object(self.tool, 'create_backup', side_effect=backup_and_edit):
            result = self.tool.process_file(path)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(path.read_text(encoding='utf-8'), '其他程序刚写入的内容')
        self.assertEqual(result.backup_path.read_bytes(), '甲\n\n乙\n'.encode('utf-8'))

    def test_standalone_cli_without_original_scripts(self):
        standalone = self.root / SCRIPT.name
        standalone.write_bytes(SCRIPT.read_bytes())
        path = self.write('正文\n\n文章别名\n- 命令行别名\n')
        completed = subprocess.run([sys.executable, str(standalone), str(path)],
                                   capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn('修改：1', completed.stdout)
        self.assertEqual(self.metadata(path.read_text(encoding='utf-8'))['aliases'], ['命令行别名'])
        failed = subprocess.run([sys.executable, str(standalone), str(self.root / 'missing.md')],
                                capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(failed.returncode, 1)
        self.assertIn('路径不存在', failed.stderr)

    def test_gui_automatically_processes_current_note_without_path_dialog(self):
        import tkinter
        from tkinter import messagebox, simpledialog
        path = self.write('正文\n\n末尾\n')
        with patch.object(tkinter, 'Tk') as root_factory, \
                patch.object(self.tool, 'detect_current_markdown', return_value=path), \
                patch.object(simpledialog, 'askstring') as ask, \
                patch.object(messagebox, 'showinfo') as info:
            self.assertEqual(self.tool.main([]), 0)
            ask.assert_not_called()
            info.assert_called_once()
            root_factory.return_value.destroy.assert_called_once()
        self.assertEqual(path.read_text(encoding='utf-8'), '正文\n末尾\n')
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)

    def test_detection_failure_does_not_ask_for_path_or_change_files(self):
        import tkinter
        from tkinter import messagebox, simpledialog
        path = self.write('正文\n\n末尾\n')
        with patch.object(tkinter, 'Tk') as root_factory, \
                patch.object(self.tool, 'detect_current_markdown', side_effect=ValueError('没有打开笔记')), \
                patch.object(simpledialog, 'askstring') as ask, \
                patch.object(messagebox, 'showerror'):
            self.assertEqual(self.tool.main([]), 1)
            ask.assert_not_called()
            root_factory.return_value.destroy.assert_called_once()
        self.assertEqual(path.read_text(encoding='utf-8'), '正文\n\n末尾\n')
        self.assertFalse(list(self.root.glob('*.bak')))

    def obsidian_config(self, vaults):
        path = self.root / 'obsidian.json'
        path.write_text(json.dumps({'vaults': {
            str(i): {'path': str(vault), 'open': True}
            for i, vault in enumerate(vaults)
        }}), encoding='utf-8')
        return path

    def test_detects_unicode_note_and_does_not_use_stale_workspace(self):
        vault = self.root / '我的库'
        folder = vault / '文章'
        folder.mkdir(parents=True)
        note = folder / '中文 - 标题.md'
        note.write_text('正文', encoding='utf-8')
        (vault / '.obsidian').mkdir()
        (vault / '.obsidian' / 'workspace.json').write_text('{broken', encoding='utf-8')
        config = self.obsidian_config([vault])
        actual = self.tool.detect_current_markdown(config, ['中文 - 标题 - 我的库 - Obsidian 1.13.7'])
        self.assertEqual(actual, note.resolve())

    def test_duplicate_note_names_are_rejected(self):
        for folder in ['a', 'b']:
            (self.root / folder).mkdir()
            (self.root / folder / '同名.md').write_text('内容', encoding='utf-8')
        config = self.obsidian_config([self.root])
        with self.assertRaisesRegex(ValueError, '同名'):
            self.tool.detect_current_markdown(config, [f'同名 - {self.root.name} - Obsidian 1.13.7'])

    def test_uses_topmost_obsidian_window_instead_of_other_open_vault(self):
        first = self.root / '一库'
        second = self.root / '二库'
        first.mkdir()
        second.mkdir()
        note = first / '当前.md'
        note.write_text('正文', encoding='utf-8')
        (second / '其他.md').write_text('正文', encoding='utf-8')
        config = self.obsidian_config([second, first])
        self.assertEqual(self.tool.detect_current_markdown(config, [
            '当前 - 一库 - Obsidian 1.13.7', '其他 - 二库 - Obsidian 1.13.7']), note.resolve())

    def test_no_window_missing_file_and_non_markdown_stop(self):
        config = self.obsidian_config([self.root])
        (self.root / '图.canvas').write_text('{}', encoding='utf-8')
        for titles in [[], [f'不存在 - {self.root.name} - Obsidian 1.13.7'],
                       [f'图.canvas - {self.root.name} - Obsidian 1.13.7']]:
            with self.subTest(titles=titles), self.assertRaises(ValueError):
                self.tool.detect_current_markdown(config, titles)

    def test_duplicate_vault_names_are_rejected(self):
        vaults = [self.root / 'a' / '库', self.root / 'b' / '库']
        for vault in vaults:
            vault.mkdir(parents=True)
            (vault / '文章.md').write_text('正文', encoding='utf-8')
        config = self.obsidian_config(vaults)
        with self.assertRaisesRegex(ValueError, '仓库'):
            self.tool.detect_current_markdown(config, ['文章 - 库 - Obsidian 1.13.7'])

    def test_ignores_trash_and_obsidian_internal_files(self):
        note = self.write('正文', '文章.md')
        for folder in ['.trash', '.obsidian']:
            (self.root / folder).mkdir()
            (self.root / folder / '文章.md').write_text('忽略', encoding='utf-8')
        config = self.obsidian_config([self.root])
        self.assertEqual(self.tool.detect_current_markdown(config, [
            f'文章 - {self.root.name} - Obsidian 1.13.7']), note.resolve())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows 目录连接点')
    def test_detects_note_in_junction_folder_and_avoids_directory_cycles(self):
        vault = self.root / '库'
        external = self.root / '外部文章'
        vault.mkdir()
        external.mkdir()
        (external / '文章.md').write_text('正文', encoding='utf-8')
        linked = vault / '导入文章'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(linked), str(external)],
                       capture_output=True, check=True)
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(external / '循环'), str(vault)],
                       capture_output=True, check=True)
        missing = self.root / '已移走的目录'
        missing.mkdir()
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(vault / '失效连接'), str(missing)],
                       capture_output=True, check=True)
        missing.rmdir()
        config = self.obsidian_config([vault])
        self.assertEqual(self.tool.detect_current_markdown(config, [
            '文章 - 库 - Obsidian 1.13.7']), linked / '文章.md')


if __name__ == '__main__':
    unittest.main()
