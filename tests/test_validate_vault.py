"""Synthetic notes stay in memory; no temporary fixtures or cleanup deletes."""
from datetime import date
import importlib.util
import io
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location('validate_vault', ROOT / 'scripts/validate_vault.py')
vault = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vault)


def metadata(**changes):
    # Synthetic parser fixture, never written as a learning note.
    result = dict(id='test-fixture-0001', type='knowledge', course='math1',
                  subject='Calculus', chapter=None, knowledge_points=[],
                  source_type=None, source_name=None, source_page=None,
                  difficulty=None, mastery=0, status='draft', created='2026-09-16',
                  updated='2026-09-16', review_dates=[], tags=[])
    result.update(changes)
    return result


def note(data=None, body=''):
    return '---\n' + yaml.safe_dump(metadata() if data is None else data) + '---\n' + body


def codes(documents):
    return {code for _, code, _ in vault.validate_documents(documents)}


class MetadataTests(unittest.TestCase):
    def test_minimal_valid_note_and_all_mastery_levels(self):
        for mastery in range(6):
            self.assertEqual(codes({'note.md': note(metadata(mastery=mastery))}), set())

    def test_all_types_and_both_courses(self):
        for kind in vault.TYPES:
            for course, subject in [('math1', 'Calculus'), ('408', 'Operating-System')]:
                data = metadata(type=kind, course=course, subject=subject)
                if kind == 'mistake':
                    data['error_type'] = 'unknown'
                if kind == 'source-note':
                    data.update(source_file=f'sources-original/{course}/fixture.pdf', source_name='parser fixture', source_page='1')
                self.assertEqual(codes({'note.md': note(data)}), set())

    def test_yaml_syntax_duplicate_keys_and_unsafe_tags(self):
        for text in ('---\na: [\n---', '---\na: 1\na: 2\n---',
                     '---\n- item\n---', '---\na: !!python/object:bad {}\n---',
                     '---\nid: a', '---\na: &a [*a]\n---'):
            with self.subTest(text=text):
                self.assertIn('YAML_INVALID', codes({'note.md': text}))

    def test_yaml_supported_quotes_comments_and_block_scalars(self):
        text = note().replace('chapter: null', 'chapter: |\n  text\n  more text')
        self.assertEqual(codes({'note.md': text}), set())
        self.assertEqual(vault.frontmatter('---\na: "value: with colon" # comment\n---')[0]['a'], 'value: with colon')

    def test_all_required_fields_checked(self):
        for field in vault.REQUIRED:
            data = metadata()
            del data[field]
            self.assertIn('FIELD_REQUIRED', codes({'note.md': note(data)}))

    def test_enums_ranges_and_malformed_types(self):
        for field, values, expected in [
            ('type', ['other', [], None], 'TYPE_INVALID'),
            ('course', ['Math1', 408, [], None], 'COURSE_INVALID'),
            ('subject', ['Operating-System', [], None], 'SUBJECT_INVALID'),
            ('mastery', [-1, 6, True, '3', None], 'MASTERY_INVALID'),
            ('difficulty', [0, 6, True, '2'], 'DIFFICULTY_INVALID'),
            ('status', ['finished', [], None], 'STATUS_INVALID'),
            ('tags', ['tag', [1], ['']], 'TAGS_INVALID'),
        ]:
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertIn(expected, codes({'note.md': note(metadata(**{field: value}))}))

    def test_missing_and_duplicate_id(self):
        self.assertIn('ID_INVALID', codes({'note.md': note(metadata(id=None))}))
        self.assertIn('ID_DUPLICATE', codes({'a.md': note(), 'b.md': note()}))

    def test_date_formats_calendar_and_order(self):
        for value in ('2026-2-01', '2026-02-30', '2026/09/16', '2026-09-16T12:00:00', 123, None):
            self.assertIn('DATE_INVALID', codes({'note.md': note(metadata(created=value))}))
        self.assertEqual(codes({'note.md': note(metadata(created=date(2026, 9, 16)))}), set())
        self.assertIn('DATE_ORDER_INVALID', codes({'note.md': note(metadata(updated='2026-09-15'))}))
        self.assertIn('DATE_LIST_INVALID', codes({'note.md': note(metadata(review_dates=['2026-02-30']))}))

    def test_page_formats(self):
        for value in (None, '', 1, '1', '1-3, 6', 'iv', 'iv-v', 'A-1', 'A.2'):
            self.assertTrue(vault.valid_page(value), repr(value))
        for value in (0, -1, True, 1.5, '0', '-1', '3-1', '1.5', '2026-09-16', 'unknown', '1,', [], {}):
            self.assertFalse(vault.valid_page(value), repr(value))

    def test_knowledge_points_require_quoted_link_list(self):
        for value in ('[[a]]', ['plain title'], [123], None):
            self.assertIn('KNOWLEDGE_LINKS_INVALID', codes({'note.md': note(metadata(knowledge_points=value))}))

    def test_template_placeholders_allowed_but_yaml_checked(self):
        for name in vault.TEMPLATES:
            path = '99-Templates/' + name
            content = (ROOT / 'vault' / path).read_text(encoding='utf-8')
            self.assertEqual(codes({path: content}), set())
        self.assertIn('YAML_INVALID', codes({'99-Templates/Knowledge-Note.md': '---\na: [\n---'}))

    def test_template_concrete_invalid_values_not_exempt(self):
        path = '99-Templates/Knowledge-Note.md'
        content = (ROOT / 'vault' / path).read_text(encoding='utf-8').replace('mastery: "{{mastery}}"', 'mastery: 9')
        self.assertIn('MASTERY_INVALID', codes({path: content}))
        self.assertIn('TEMPLATE_ID_PLACEHOLDER_REQUIRED', codes({path: note()}))

    def test_formal_note_placeholders_rejected(self):
        self.assertIn('UNRESOLVED_PLACEHOLDER', codes({'note.md': note(body='{{unfilled}}')}))

    def test_exemptions_are_explicit_not_directory_wide(self):
        self.assertEqual(codes({'00-System/Home.md': '# Home'}), set())
        for path in ('00-System/new.md', '99-Templates/new.md', 'notes/new.md'):
            self.assertIn('FRONTMATTER_REQUIRED', codes({path: '# Empty'}))

    def test_registered_parsed_markdown_uses_dedicated_validator(self):
        path = '90-Parsed-Sources/src-abcdef123456/pages/page-0001.md'
        self.assertEqual(codes({path: '# Generated derived fixture'}), set())
        self.assertFalse(vault.parsed_output_document('90-Parsed-Sources/not-a-source/page.md'))

    def test_error_type_fixed_options(self):
        for value in vault.ERROR_TYPES:
            self.assertEqual(codes({'note.md': note(metadata(type='mistake', error_type=value))}), set())
        self.assertIn('ERROR_TYPE_INVALID', codes({'note.md': note(metadata(type='mistake', error_type='other'))}))

    def test_source_citation_and_path_constraints(self):
        self.assertIn('SOURCE_CITATION_REQUIRED', codes({'note.md': note(metadata(type='source-note'))}))
        for value in ('../outside.pdf', 'C:/secret.pdf', 'sources-original/math1/../bad.pdf', 'vault/other.pdf', None):
            self.assertIn('SOURCE_FILE_INVALID', codes({'note.md': note(metadata(type='source-note', source_file=value))}))


class LinkTests(unittest.TestCase):
    def test_links_in_body_and_metadata(self):
        docs = {'a.md': note(metadata(knowledge_points=['[[folder/b|target]]']), '[[folder/b#Heading|alias]]'),
                'folder/b.md': note(metadata(id='test-fixture-0002'))}
        self.assertEqual(codes(docs), set())

    def test_missing_and_ambiguous_links(self):
        self.assertIn('LINK_MISSING_OR_AMBIGUOUS', codes({'a.md': note(body='[[absent]]')}))
        self.assertIsNone(vault.resolve_link('same', 'a.md', {'b/same.md', 'c/same.md'}))

    def test_full_local_and_short_links_and_embeds(self):
        assets = {'a.md', 'folder/b.md', 'folder/image.png'}
        for target in ('folder/b', 'b', 'b.md'):
            self.assertEqual(vault.resolve_link(target, 'a.md', assets), 'folder/b.md')
        self.assertEqual(vault.resolve_link('image.png', 'folder/b.md', assets), 'folder/image.png')
        self.assertEqual(vault.validate_documents({'a.md': note(body='![[folder/image.png]]')}, assets), [])

    def test_unsafe_links(self):
        for target in ('../outside', '/absolute', 'C:/outside', 'folder\\outside'):
            self.assertIsNone(vault.resolve_link(target, 'a.md', {'a.md'}))

    def test_code_examples_and_comments_not_links(self):
        body = '`[[missing]]`\n```yaml\n[[missing]]\n```\n~~~\n[[missing]]\n~~~\n<!-- [[missing]] -->'
        self.assertEqual(codes({'a.md': note(body=body)}), set())
        self.assertIn('LINK_MISSING_OR_AMBIGUOUS', codes({'a.md': note(body=body + '\n[[missing]]')}))


class IgnoreRuleTests(unittest.TestCase):
    """Query Git rules for hypothetical paths without creating any files."""

    def assert_ignored(self, paths, expected):
        for path in paths:
            with self.subTest(path=path):
                result = subprocess.run(
                    ['git', '--no-optional-locks', '-C', str(ROOT),
                     'check-ignore', '--no-index', '-q', '--', path],
                    capture_output=True, timeout=10,
                )
                self.assertIn(result.returncode, (0, 1))
                self.assertEqual(result.returncode == 0, expected)

    def test_all_obsidian_paths_ignored(self):
        self.assert_ignored([
            '.obsidian/app.json', '.obsidian/.gitkeep',
            'vault/.obsidian/app.json', 'vault/.obsidian/appearance.json',
            'vault/.obsidian/core-plugins.json', 'vault/.obsidian/workspace.json',
            'vault/nested/.obsidian/app.json',
            'vault/nested/deeper/.obsidian/plugins/plugin/main.js',
            'sources-original/math1/.obsidian/.gitkeep',
            'sources-original/408/nested/.obsidian/app.json',
        ], True)

    def test_sensitive_and_runtime_files_ignored(self):
        self.assert_ignored([
            '.env', 'config/.env.production', 'logs/run.log',
            'scripts/__pycache__/tool.cpython-312.pyc', '.pytest_cache/state', '.venv/Lib/site-packages/example.py',
            'api-cache/result.json', '.cache/result.json',
            'review-queue/pdf-parse-blocks/src-abcdef123456.json',
            'config/sources-original.baseline.json',
            'config/source-manifests/src-abcdef123456.json',
            'import-inbox/pending.pdf',
            'review-queue/import-plans/plan.json',
            'review-queue/parsing-routing/src-abcdef123456.json',
            'review-queue/parsing-jobs/job.json',
            'review-queue/parsing-checkpoints/checkpoint.json', 'models/cache/model.bin',
            'vault/90-Parsed-Sources/src-abcdef123456/index.md',
            'sources-original/math1/book.PDF', 'sources-original/408/slides.ppt',
            'sources-original/408/slides.pptx', 'sources-original/math1/book.doc',
            'sources-original/math1/book.docx', 'vault/80-Attachments/book.pdf',
        ], True)

    def test_safe_project_files_remain_trackable(self):
        self.assert_ignored([
            '.env.example', 'AGENTS.md', 'README.md',
            'vault/03-Knowledge-Notes/note.md', 'prompts/example.md',
            'scripts/validate_vault.py', 'tests/test_validate_vault.py',
            'scripts/pdf_parser.py', 'tests/test_pdf_parser.py', 'requirements.txt',
            'scripts/parsing_architecture.py', 'tests/test_parsing_architecture.py',
            'config/parsing-profiles.yaml', 'config/resource-limits.yaml',
            'config/providers.example.yaml', 'config/sources-original.baseline.example.json',
            'config/source-manifests/.gitkeep', 'import-inbox/.gitkeep',
            'review-queue/import-plans/.gitkeep', 'review-queue/parsing-routing/.gitkeep',
            'vault/90-Parsed-Sources/.gitkeep',
            'vault/90-Parsed-Sources/Parsed-Sources-MOC.md',
        ], False)


class SafetyTests(unittest.TestCase):
    def test_inventory_detects_add_missing_and_metadata_changes(self):
        baseline = {'math1/.gitkeep': {'kind': 'file', 'size': 0, 'mtime_ns': 1}}
        self.assertEqual(vault.compare_originals(baseline, baseline), [])
        for current in ({}, {**baseline, 'bad.md': {'kind': 'file'}},
                        {'math1/.gitkeep': {'kind': 'file', 'size': 1, 'mtime_ns': 1}}):
            self.assertTrue(vault.compare_originals(current, baseline))

    def test_reparse_points_rejected_before_descent(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, 'lstat', return_value=info), patch.object(Path, 'iterdir') as descend:
            with self.assertRaises(vault.UnsafePath):
                vault.scan_tree(ROOT, ROOT / 'vault')
            descend.assert_not_called()

    def test_external_scan_refused(self):
        with self.assertRaises(ValueError):
            vault.scan_tree(ROOT, Path('Z:/outside'))

    def test_real_project_read_only_and_no_original_text_reads(self):
        original_open = io.open
        def read_only(file, mode='r', *args, **kwargs):
            self.assertFalse(any(c in mode for c in 'wax+'))
            if isinstance(file, (str, Path)):
                path = Path(file).absolute()
                self.assertTrue(path.is_relative_to(ROOT))
                if path.is_relative_to(ROOT / 'sources-original'):
                    self.assertIn('b', mode)  # Phase 2A permits binary SHA-256 checks only.
            return original_open(file, mode, *args, **kwargs)
        with patch('io.open', side_effect=read_only), \
                patch.object(Path, 'write_text', side_effect=AssertionError('write forbidden')), \
                patch.object(Path, 'unlink', side_effect=AssertionError('delete forbidden')):
            issues, count = vault.validate_project(ROOT)
        self.assertEqual(issues, [])
        self.assertGreaterEqual(count, len(vault.SYSTEM_NOTES) + len(vault.TEMPLATES))

    def test_missing_yaml_dependency_no_install(self):
        with patch.object(vault, 'yaml', None), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(vault.main(), 2)
        self.assertIn('no installation attempted', output.getvalue())


if __name__ == '__main__':
    unittest.main()
