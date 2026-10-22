"""别名和标签迁移回归测试；仅操作临时笔记，不启动界面。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

import update_frontmatter_and_remove_blanklines as combined


class CombinedMetadataMigrationTests(unittest.TestCase):
    def test_keyword_headings_accept_all_levels_and_decorations(self):
        for level in range(1, 7):
            with self.subTest(level=level):
                original = ('---\naliases: [旧名]\ntags: [旧标签]\n---\n'
                            + '#' * level + ' 📚 **文章别名（推荐）**\n'
                            '- 新名一\n\n+ 新名二\n\n'
                            + '#' * level + ' 🏷️ **文章标签（推荐）**\n'
                            '1) 标签一\n\n2. 标签二\n'
                            '## 后续\n- 保留正文\n')
                output, aliases, tags = combined.migrate_frontmatter(original)
                data, _, body = combined.split_frontmatter(output)
                self.assertEqual((aliases, tags), (2, 2))
                self.assertEqual(data['aliases'], ['旧名', '新名一', '新名二'])
                self.assertEqual(data['tags'], ['旧标签', '标签一', '标签二'])
                self.assertNotIn('文章别名', body)
                self.assertNotIn('文章标签', body)
                self.assertIn('## 后续\n- 保留正文\n', body)

    def test_heading_sections_accept_plain_text_and_separated_lists(self):
        original = ('正文\n### 文章别名\nCatLeaf猫页项目分享\n\n'
                    '- RSS阅读器开发笔记\n\n开源订阅工具指南\n'
                    '###### 文章标签\nRSS\n\n开源\n- 工具\n'
                    '## 后续\n保留正文\n')
        output, aliases, tags = combined.migrate_frontmatter(original)
        data, _, body = combined.split_frontmatter(output)
        self.assertEqual((aliases, tags), (3, 3))
        self.assertEqual(data['aliases'],
                         ['CatLeaf猫页项目分享', 'RSS阅读器开发笔记', '开源订阅工具指南'])
        self.assertEqual(data['tags'], ['RSS', '开源', '工具'])
        self.assertEqual(body, '正文\n## 后续\n保留正文\n')

    def test_plain_metadata_stops_before_separator_or_protected_content(self):
        for tail in ['---\n- 保留正文\n',
                     '```text\n文章标签\n- 保留代码\n```\n',
                     '<div>\n文章标签\n- 保留HTML\n</div>\n']:
            with self.subTest(tail=tail):
                original = '## 文章别名\n别名一\n\n' + tail
                output, aliases, tags = combined.migrate_frontmatter(original)
                data, _, body = combined.split_frontmatter(output)
                self.assertEqual((aliases, tags), (1, 0))
                self.assertEqual(data['aliases'], ['别名一'])
                self.assertIn(tail, body)

    def test_special_characters_survive_migration(self):
        original = ('---\ntitle: 原标题\nextra: {enabled: true}\n---\n'
                    '# 正文\n保留正文\n\n## 文章别名：\n'
                    '- 主题: 说明\n- [别名]\n\n## 文章标签：\n'
                    '- #读书\n- #AI/工具\n\n## 后续\n保留后续正文\n')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '笔记.md'
            path.write_text(original, encoding='utf-8')
            result = combined.process_file(path)
            self.assertEqual(result.status, 'modified', result.error)
            output = path.read_text(encoding='utf-8')
            metadata = yaml.safe_load(output.split('---', 2)[1])
            self.assertEqual(metadata['aliases'], ['主题: 说明', '[别名]'])
            self.assertEqual(metadata['tags'], ['#读书', '#AI/工具'])
            self.assertEqual(metadata['extra'], {'enabled': True})
            self.assertIn('保留正文', output)
            self.assertIn('保留后续正文', output)
            self.assertNotIn('## 文章别名', output)
            self.assertNotIn('## 文章标签', output)


    def test_metadata_overwritten_during_save_is_not_reported_as_success(self):
        original = '正文\n## 文章别名：\n- WorkBuddy集成方案\n\n## 文章标签：\n- MCP\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '笔记.md'
            path.write_text(original, encoding='utf-8')
            replace = combined.os.replace

            def replace_then_clear_metadata(source, target):
                replace(source, target)
                _, _, body = combined.split_frontmatter(path.read_text(encoding='utf-8'))
                path.write_text('---\naliases:\ntags:\n---\n' + body, encoding='utf-8')

            with patch.object(combined.os, 'replace', side_effect=replace_then_clear_metadata):
                result = combined.process_file(path)
            self.assertEqual(result.status, 'failed')
            self.assertIn('写回', result.error)

    def test_invalid_serialized_metadata_does_not_delete_body(self):
        original = '正文\n## 文章别名：\n- 别名一\n\n## 文章标签：\n- 标签一\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '笔记.md'
            path.write_text(original, encoding='utf-8')
            before = path.read_bytes()
            with patch.object(combined.yaml, 'safe_dump', return_value='{}\n'):
                result = combined.process_file(path)
            self.assertEqual(result.status, 'failed')
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
