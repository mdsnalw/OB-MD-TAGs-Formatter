"""作者迁移测试：只修改临时目录里的 Markdown。"""
import tempfile
import unittest
from pathlib import Path

import update_frontmatter_and_remove_blanklines as tool


class AuthorMigrationTests(unittest.TestCase):
    def test_author_only_creates_frontmatter_and_keeps_body(self):
        body = '# 正文\n内容\n\n---\nAuthor: 青临同学\n'
        output, aliases, tags = tool.migrate_frontmatter(body)
        data, _, remaining = tool.split_frontmatter(output)
        self.assertEqual(data, {'author': '青临同学'})
        self.assertEqual(remaining, body)
        self.assertEqual((aliases, tags), (0, 0))

    def test_missing_null_and_blank_authors_are_filled(self):
        for field in ['', 'author:\n', 'author: null\n', 'author: ""\n',
                      'author: "  "\n']:
            with self.subTest(field=field):
                content = '---\ntitle: 标题\n' + field + '---\nAuthor: 青临同学\n'
                output, _, _ = tool.migrate_frontmatter(content)
                data, _, _ = tool.split_frontmatter(output)
                self.assertEqual(data, {'title': '标题', 'author': '青临同学'})

    def test_existing_author_values_and_header_are_preserved(self):
        for value in ['原作者', '[甲, 乙]', '{name: 甲}', 'false', '0', '[]', '{}']:
            with self.subTest(value=value):
                original = '---\n# 注释\nauthor: ' + value + '\n---\nAuthor: 新作者\n'
                self.assertEqual(tool.migrate_frontmatter(original), (original, 0, 0))

    def test_last_nonempty_author_wins_with_case_and_colon_variants(self):
        body = 'Author: 旧作者\n  aUtHoR ：  青临同学  \nAUTHOR:   \n'
        output, _, _ = tool.migrate_frontmatter(body)
        self.assertEqual(tool.split_frontmatter(output)[0]['author'], '青临同学')

    def test_no_author_does_not_create_frontmatter(self):
        for body in ['正文\n', 'Author:  \n', '提到 Author: 甲\n',
                     '> Author: 甲\n', '- Author: 甲\n',
                     '    Author: 缩进代码\n', '\tAuthor: 缩进代码\n']:
            with self.subTest(body=body):
                self.assertEqual(tool.migrate_frontmatter(body), (body, 0, 0))

    def test_protected_authors_are_ignored(self):
        for region in ['```text\nAuthor: 代码\n```\n',
                       '~~~\nAuthor: 代码\n~~~\n',
                       '<div>\nAuthor: HTML\n</div>\n',
                       '<!--\nAuthor: 注释\n-->\n',
                       '| author |\n| --- |\n| Author: 表格 |\n',
                       '```\nAuthor: 未关闭代码\n', '<div>\nAuthor: 未关闭HTML\n']:
            with self.subTest(region=region):
                self.assertEqual(tool.migrate_frontmatter(region), (region, 0, 0))
                output, _, _ = tool.migrate_frontmatter('Author: 正确作者\n' + region)
                self.assertEqual(tool.split_frontmatter(output)[0]['author'], '正确作者')

    def test_author_after_angle_bracket_links(self):
        for link in ['[链接](<https://example.com>)', '<https://example.com>',
                     '<mailto:user@example.com>', '<user@example.com>']:
            with self.subTest(link=link):
                output, _, _ = tool.migrate_frontmatter(link + '\nAuthor: 青临同学\n')
                self.assertEqual(tool.split_frontmatter(output)[0].get('author'), '青临同学')

    def test_yaml_special_characters_remain_strings(self):
        for author in ['甲: 乙 #作者', '[甲, 乙]', 'true', '123', 'null', 'O\'Reilly']:
            with self.subTest(author=author):
                output, _, _ = tool.migrate_frontmatter('Author: ' + author + '\n')
                self.assertEqual(tool.split_frontmatter(output)[0]['author'], author)

    def test_author_tags_aliases_and_other_fields(self):
        original = ('---\nfeishuRecordID: reczz28QHtkQWY1q\n'
                    'feishuURL: https://feishu.cn/base/example\nextra: {enabled: true}\n'
                    'tags:\naliases:\n---\n正文\n文章别名\n- 别名\n'
                    '文章标签\n- 标签\nAuthor: 青临同学\n')
        output, aliases, tags = tool.migrate_frontmatter(original)
        data, _, body = tool.split_frontmatter(output)
        self.assertEqual((aliases, tags), (1, 1))
        self.assertEqual(data['author'], '青临同学')
        self.assertEqual(data['aliases'], ['别名'])
        self.assertEqual(data['tags'], ['标签'])
        self.assertEqual(data['extra'], {'enabled': True})
        self.assertEqual(data['feishuRecordID'], 'reczz28QHtkQWY1q')
        self.assertEqual(data['feishuURL'], 'https://feishu.cn/base/example')
        self.assertIn('Author: 青临同学\n', body)

    def test_file_pipeline_bom_crlf_summary_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '笔记.md'
            path.write_bytes('\ufeff正文\r\n\r\nAuthor: 青临同学\r\n'.encode('utf-8'))
            result = tool.process_file(path)
            self.assertEqual(result.status, 'modified', result.error)
            output = path.read_bytes()
            self.assertTrue(output.startswith(b'\xef\xbb\xbf'))
            self.assertNotIn(b'\n', output.replace(b'\r\n', b''))
            data, _, body = tool.split_frontmatter(output.decode('utf-8-sig'))
            self.assertEqual(data['author'], '青临同学')
            self.assertEqual(body, '正文\r\nAuthor: 青临同学\r\n')
            self.assertEqual(result.added_authors, 1)
            self.assertIn('实际补充作者：1 篇', tool.format_summary([result]))
            again = tool.process_file(path)
            self.assertEqual(again.status, 'unchanged', again.error)
            self.assertEqual(again.added_authors, 0)
            self.assertEqual(path.read_bytes(), output)
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
