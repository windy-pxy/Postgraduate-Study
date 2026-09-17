"""Phase 2B tests use generated PDFs only under tests/.runtime."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location('pdf_parser_test', ROOT / 'scripts/pdf_parser.py')
pdf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pdf)


class PDFParserTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / 'tests/.runtime'
        runtime.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='pdf-test-', dir=runtime)
        self.root = Path(self.temp.name)
        self.assertTrue(self.root.resolve().is_relative_to(runtime.resolve()))
        for directory in ('sources-original/math1/calculus', 'config/source-manifests',
                          'vault/90-Parsed-Sources', 'import-inbox', 'review-queue/import-plans',
                          'review-queue/pdf-parse-blocks'):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.source_id = self._register_pdf('synthetic.pdf', self._make_pdf())
        self.parser = pdf.PDFParser(self.root)

    def tearDown(self):
        self.assertTrue(self.root.resolve().is_relative_to((ROOT / 'tests/.runtime').resolve()))
        self.temp.cleanup()

    def _make_pdf(self, pages=('First synthetic page', '', 'Image page')):
        document = fitz.open()
        for index, text in enumerate(pages):
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text, fontsize=12)
            if index == 2:
                pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
                pixmap.clear_with(0x55AAEE)
                page.insert_image(fitz.Rect(72, 100, 120, 148), stream=pixmap.tobytes('png'))
        data = document.tobytes(garbage=4, deflate=True)
        document.close()
        return data

    def _register_pdf(self, filename, data):
        digest = hashlib.sha256(data).hexdigest()
        source_id = 'src-' + digest[:12]
        relative = f'sources-original/math1/calculus/{source_id}/{filename}'
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest = {
            'schema_version': 1, 'source_id': source_id, 'sha256': digest,
            'original_filename': filename, 'stored_relative_path': relative,
            'file_type': 'pdf', 'size_bytes': len(data), 'course': 'math1',
            'subject': 'calculus', 'source_type': 'textbook',
            'classification_status': 'confirmed', 'import_status': 'imported',
            'imported_at': '2026-09-16T12:00:00+08:00', 'parser_status': 'not_started',
            'parser_name': None, 'parser_version': None, 'page_count': None,
            'parsed_at': None, 'parsed_output_relative_path': None,
            'parse_review_status': None, 'notes': ''}
        (self.root / 'config/source-manifests' / f'{source_id}.json').write_bytes(pdf.json_bytes(manifest))
        baseline = {'schema_version': 2, 'algorithm': 'sha256',
                    'sources': {source_id: {'sha256': digest, 'stored_relative_path': relative,
                                            'size_bytes': len(data)}}}
        (self.root / 'config/sources-original.baseline.json').write_bytes(pdf.json_bytes(baseline))
        return source_id

    def output(self):
        return self.root / 'vault/90-Parsed-Sources' / self.source_id

    def apply(self):
        return self.parser.parse(self.source_id, execute=True)

    def test_inspect_multi_page_pdf(self):
        result = self.parser.inspect(self.source_id)
        self.assertEqual(result['page_count'], 3)
        self.assertTrue(result['read_only'])
        self.assertEqual(result['parser_version'], fitz.__version__)

    def test_parse_dry_run_writes_nothing(self):
        before = set(self.root.rglob('*'))
        result = self.parser.parse(self.source_id)
        self.assertTrue(result['dry_run'])
        self.assertEqual(set(self.root.rglob('*')), before)

    def test_apply_structure_text_blank_image_and_report(self):
        before_manifest = self.parser.manager.manifests()[0][self.source_id]
        result = self.apply()
        self.assertEqual(result['page_count'], 3)
        out = self.output()
        self.assertEqual({p.name for p in out.iterdir()}, {'index.md', 'review.md', 'parse-report.json', 'pages', 'assets'})
        report = json.loads((out / 'parse-report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['declared_page_count'], 3)
        self.assertEqual(report['output_page_count'], 3)
        self.assertEqual(report['empty_pages'], [2])
        self.assertEqual(report['image_pages'], [3])
        self.assertGreaterEqual(report['image_count'], 1)
        self.assertIn(3, report['formula_review_pages'])
        self.assertTrue((out / 'assets/page-0002.png').exists())
        self.assertTrue((out / 'assets/page-0003.png').exists())
        page = (out / 'pages/page-0001.md').read_text(encoding='utf-8')
        self.assertIn('source_page: 1', page)
        self.assertIn('First synthetic page', page)
        self.assertTrue(self.parser.verify_output(self.source_id)['ok'])
        manifest = json.loads((self.root / f'config/source-manifests/{self.source_id}.json').read_text(encoding='utf-8'))
        for field in ('source_id', 'sha256', 'original_filename', 'stored_relative_path', 'course',
                      'subject', 'source_type', 'imported_at'):
            self.assertEqual(manifest[field], before_manifest[field])
        self.assertEqual(manifest['parser_status'], 'parsed')
        self.assertEqual(manifest['parser_name'], pdf.PARSER_NAME)
        self.assertEqual(manifest['parser_version'], fitz.__version__)
        self.assertEqual(manifest['page_count'], 3)
        self.assertEqual(manifest['parsed_at'], report['parsed_at'])
        self.assertEqual(manifest['parsed_output_relative_path'], f'vault/90-Parsed-Sources/{self.source_id}')
        self.assertEqual(manifest['parse_review_status'], 'review_required')

    def test_chinese_text_and_chinese_filename(self):
        # Synthetic extraction result avoids reliance on a system font outside the project.
        source_id = self._register_pdf('中文资料.pdf', self._make_pdf(('placeholder',)))
        tool = pdf.PDFParser(self.root)
        with patch.object(tool, '_extract_page', return_value='中文文本段落'):
            tool.parse(source_id, execute=True)
        page = self.root / f'vault/90-Parsed-Sources/{source_id}/pages/page-0001.md'
        self.assertIn('中文文本段落', page.read_text(encoding='utf-8'))
        self.assertTrue(tool.verify_output(source_id)['ok'])

    def test_formula_syntax_is_not_fabricated(self):
        with patch.object(self.parser, '_extract_page', return_value='x = y + 1 and $not-latex$'):
            self.apply()
        page = (self.output() / 'pages/page-0001.md').read_text(encoding='utf-8')
        self.assertIn('needs_formula_review', page)
        self.assertIn('$not-latex$', page)
        self.assertNotIn('$$', page)
        self.assertTrue(self.parser.verify_output(self.source_id)['ok'])

    def test_base_verifier_allows_separate_candidate_layers_only(self):
        self.apply()
        for name in ('enhanced', 'quality', 'annotations', 'accepted'):
            (self.output() / name).mkdir()
        self.assertTrue(self.parser.verify_output(self.source_id)['ok'])
        (self.output() / 'unexpected-layer').mkdir()
        with self.assertRaisesRegex(pdf.ParserError, 'OUTPUT_STRUCTURE_INVALID'):
            self.parser.verify_output(self.source_id)

    def test_single_page_exception_is_reported_not_skipped(self):
        original = self.parser._extract_page
        def extract(page):
            if page.number == 1:
                raise RuntimeError('synthetic extraction failure')
            return original(page)
        with patch.object(self.parser, '_extract_page', side_effect=extract):
            self.apply()
        report = json.loads((self.output() / 'parse-report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['error_pages'], [2])
        self.assertEqual(report['output_page_count'], 3)
        self.assertTrue((self.output() / 'pages/page-0002.md').exists())

    def test_parser_open_exception_leaves_no_output(self):
        with patch.object(self.parser, '_open', side_effect=pdf.ParserError('PDF_OPEN_FAILED')):
            with self.assertRaisesRegex(pdf.ParserError, 'PDF_OPEN_FAILED'):
                self.apply()
        self.assertFalse(self.output().exists())
        self.assertFalse(list((self.root / 'vault/90-Parsed-Sources').glob('.tmp-*')))

    def test_page_preview_failure_is_reported(self):
        with patch.object(self.parser, '_render', side_effect=RuntimeError('synthetic render failure')):
            self.apply()
        report = self.parser.report(self.source_id)
        self.assertIn('page_preview_render_failed', report['quality_warnings'])
        self.assertEqual(list((self.output() / 'assets').iterdir()), [])

    def test_source_hash_anomaly_blocks_parse(self):
        path = next((self.root / 'sources-original').rglob('*.pdf'))
        data = path.read_bytes()
        path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        with self.assertRaisesRegex(pdf.ParserError, 'SOURCE_INTEGRITY_FAILED'):
            self.parser.parse(self.source_id)

    def test_invalid_and_unregistered_source_id(self):
        for source_id in ('../outside', 'src-short', 'C:/outside'):
            with self.subTest(source_id=source_id), self.assertRaisesRegex(pdf.ParserError, 'SOURCE_ID_INVALID'):
                self.parser.inspect(source_id)
        missing = 'src-' + 'a' * 12
        with self.assertRaisesRegex(pdf.ParserError, 'SOURCE_NOT_REGISTERED'):
            self.parser.inspect(missing)

    def test_non_pdf_registered_source_rejected(self):
        manifest_path = next((self.root / 'config/source-manifests').glob('*.json'))
        record = json.loads(manifest_path.read_text(encoding='utf-8'))
        record['file_type'] = 'docx'
        record['original_filename'] = 'synthetic.docx'
        record['stored_relative_path'] = record['stored_relative_path'][:-3] + 'docx'
        old = next((self.root / 'sources-original').rglob('*.pdf'))
        old.rename(self.root / record['stored_relative_path'])
        manifest_path.write_bytes(pdf.json_bytes(record))
        baseline_path = self.root / 'config/sources-original.baseline.json'
        baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
        baseline['sources'][self.source_id]['stored_relative_path'] = record['stored_relative_path']
        baseline_path.write_bytes(pdf.json_bytes(baseline))
        with self.assertRaises((pdf.ParserError, pdf.SourceError)):
            self.parser.inspect(self.source_id)

    def test_existing_output_refused_and_preserved(self):
        self.output().mkdir()
        sentinel = self.output() / 'sentinel.txt'
        sentinel.write_text('preserve synthetic fixture', encoding='utf-8')
        with self.assertRaisesRegex(pdf.ParserError, 'OUTPUT_EXISTS'):
            self.apply()
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'preserve synthetic fixture')

    def test_atomic_publish_failure_cleans_temp(self):
        with patch.object(self.parser, '_publish', side_effect=OSError('synthetic publish failure')):
            with self.assertRaises(OSError):
                self.apply()
        self.assertFalse(self.output().exists())
        self.assertFalse(list((self.root / 'vault/90-Parsed-Sources').glob('.tmp-*')))
        record = self.parser.manager.manifests()[0][self.source_id]
        self.assertEqual(record['parser_status'], 'not_started')

    def test_output_validation_failure_keeps_manifest_not_started(self):
        with patch.object(self.parser, 'verify_directory', side_effect=pdf.ParserError('OUTPUT_STRUCTURE_INVALID')):
            with self.assertRaisesRegex(pdf.ParserError, 'OUTPUT_STRUCTURE_INVALID'):
                self.apply()
        self.assertFalse(self.output().exists())
        record = self.parser.manager.manifests()[0][self.source_id]
        self.assertEqual(record['parser_status'], 'not_started')

    def test_parse_does_not_write_source(self):
        source = next((self.root / 'sources-original').rglob('*.pdf'))
        before = (source.read_bytes(), source.stat().st_mtime_ns)
        self.apply()
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), before)

    def test_output_page_count_mismatch(self):
        self.apply()
        report_path = self.output() / 'parse-report.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        report['output_page_count'] = 2
        report_path.write_bytes(pdf.json_bytes(report))
        with self.assertRaisesRegex(pdf.ParserError, 'PAGE_COUNT_MISMATCH'):
            self.parser.verify_output(self.source_id)

    def test_report_metrics_mismatch(self):
        self.apply()
        report_path = self.output() / 'parse-report.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        report['image_count'] += 1
        report_path.write_bytes(pdf.json_bytes(report))
        with self.assertRaisesRegex(pdf.ParserError, 'REPORT_METRICS_MISMATCH'):
            self.parser.verify_output(self.source_id)

    def test_asset_signature_checked(self):
        self.apply()
        asset = next((self.output() / 'assets').glob('*.png'))
        asset.write_bytes(b'not a PNG generated fixture')
        with self.assertRaisesRegex(pdf.ParserError, 'ASSET_FORMAT_INVALID'):
            self.parser.verify_output(self.source_id)

    def test_internal_link_target_must_exist(self):
        self.apply()
        index = self.output() / 'index.md'
        index.write_text(index.read_text(encoding='utf-8') + '\n[[pages/missing-page]]\n', encoding='utf-8')
        with self.assertRaisesRegex(pdf.ParserError, 'INTERNAL_LINK_MISSING'):
            self.parser.verify_output(self.source_id)

    def test_missing_and_unregistered_page_files(self):
        self.apply()
        page = self.output() / 'pages/page-0002.md'
        page.unlink()  # Generated derived fixture only.
        with self.assertRaisesRegex(pdf.ParserError, 'PAGE_FILES_MISMATCH'):
            self.parser.verify_output(self.source_id)
        page.write_text('generated unexpected fixture', encoding='utf-8')
        (self.output() / 'pages/page-9999.md').write_text('generated unexpected fixture', encoding='utf-8')
        with self.assertRaisesRegex(pdf.ParserError, 'PAGE_FILES_MISMATCH'):
            self.parser.verify_output(self.source_id)

    def test_missing_page_metadata(self):
        self.apply()
        page = self.output() / 'pages/page-0001.md'
        page.write_text('# generated fixture without metadata', encoding='utf-8')
        with self.assertRaisesRegex(pdf.ParserError, 'PAGE_FRONTMATTER_MISSING'):
            self.parser.verify_output(self.source_id)

    def test_wrong_source_id_in_page(self):
        self.apply()
        page = self.output() / 'pages/page-0001.md'
        page.write_text(page.read_text(encoding='utf-8').replace(self.source_id, 'src-' + 'a' * 12, 1), encoding='utf-8')
        with self.assertRaisesRegex(pdf.ParserError, 'PAGE_METADATA_MISMATCH'):
            self.parser.verify_output(self.source_id)

    def test_wrong_source_id_in_index(self):
        self.apply()
        index = self.output() / 'index.md'
        index.write_text(index.read_text(encoding='utf-8').replace(self.source_id, 'src-' + 'a' * 12, 1), encoding='utf-8')
        with self.assertRaisesRegex(pdf.ParserError, 'INDEX_METADATA_MISMATCH'):
            self.parser.verify_output(self.source_id)

    def test_review_state_required(self):
        self.apply()
        review = self.output() / 'review.md'
        review.write_text(review.read_text(encoding='utf-8').replace('- review_status: review_required', '- review_status: reviewed'), encoding='utf-8')
        with self.assertRaisesRegex(pdf.ParserError, 'REVIEW_METADATA_MISMATCH'):
            self.parser.verify_output(self.source_id)

    def test_external_and_traversal_links_rejected(self):
        self.apply()
        page = self.output() / 'review.md'
        for link in ('https://example.invalid', '../../../outside.md', 'C:/outside.md'):
            original = page.read_text(encoding='utf-8')
            page.write_text(original + f'\n[unsafe]({link})\n', encoding='utf-8')
            with self.assertRaisesRegex(pdf.ParserError, 'EXTERNAL_OR_UNSAFE_LINK'):
                self.parser.verify_output(self.source_id)
            page.write_text(original, encoding='utf-8')

    def test_normal_code_examples_are_preserved_exactly(self):
        example = 'YOUR_API_KEY = "example"\napi_key = "${API_KEY}"\nprint("hello")'
        with patch.object(self.parser, '_extract_page', return_value=example):
            self.apply()
        content = (self.output() / 'pages/page-0001.md').read_text(encoding='utf-8')
        self.assertIn(example, content)
        self.assertNotIn('REDACTED', content)

    def test_high_confidence_secret_blocks_without_disclosure_or_source_change(self):
        synthetic_key = 'sk-' + 'A1b2C3d4E5f6G7h8J9k0LmNopQrStUvWxYz'
        source = next((self.root / 'sources-original').rglob('*.pdf'))
        before = (source.read_bytes(), source.stat().st_mtime_ns)
        output = io.StringIO()
        with patch.object(self.parser, '_extract_page', return_value='page text ' + synthetic_key), \
                patch.object(pdf, 'PDFParser', return_value=self.parser), redirect_stdout(output):
            self.assertEqual(pdf.cli(['parse', self.source_id, '--apply']), 1)
        self.assertNotIn(synthetic_key, output.getvalue())
        self.assertNotIn(str(self.root), output.getvalue())
        self.assertIn('SENSITIVE_CONTENT_BLOCKED', output.getvalue())
        self.assertFalse(self.output().exists())
        blocked = self.root / f'review-queue/pdf-parse-blocks/{self.source_id}.json'
        self.assertTrue(blocked.is_file())
        report_text = blocked.read_text(encoding='utf-8')
        self.assertNotIn(synthetic_key, report_text)
        report = json.loads(report_text)
        self.assertEqual(report['status'], 'blocked_sensitive_content')
        self.assertEqual(report['error_code'], 'SENSITIVE_CONTENT_BLOCKED')
        self.assertEqual(report['affected_pages'], [1])
        self.assertIn('openai_style_api_key', report['risk_types'])
        self.assertFalse(report['contains_source_text'])
        record = self.parser.manager.manifests()[0][self.source_id]
        self.assertEqual(record['parser_status'], 'not_started')
        self.assertIsNone(record['parsed_at'])
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), before)

    def test_manifest_update_failure_is_reported_as_state_conflict(self):
        with patch.object(self.parser.manager, 'mark_parsed', side_effect=pdf.SourceError('MANIFEST_UPDATE_FAILED')):
            with self.assertRaisesRegex(pdf.SourceError, 'MANIFEST_UPDATE_FAILED'):
                self.apply()
        self.assertTrue(self.output().is_dir())
        record = self.parser.manager.manifests()[0][self.source_id]
        self.assertEqual(record['parser_status'], 'not_started')
        issues = self.parser.manager.verify()['issues']
        self.assertIn('PARSE_STATE_CONFLICT', {item['error'] for item in issues})

    def test_parsed_manifest_requires_output_and_matching_report(self):
        self.apply()
        moved = self.root / 'vault/90-Parsed-Sources/generated-away'
        self.output().rename(moved)
        self.assertIn('PARSED_OUTPUT_MISSING', {item['error'] for item in self.parser.manager.verify()['issues']})
        moved.rename(self.output())
        report_path = self.output() / 'parse-report.json'
        report = json.loads(report_path.read_text(encoding='utf-8'))
        report['declared_page_count'] = 2
        report_path.write_bytes(pdf.json_bytes(report))
        self.assertIn('PARSE_MANIFEST_REPORT_CONFLICT',
                      {item['error'] for item in self.parser.manager.verify()['issues']})

    def test_repeat_parse_refuses_overwrite(self):
        self.apply()
        with self.assertRaisesRegex(pdf.ParserError, 'OUTPUT_EXISTS'):
            self.apply()

    def test_report_requires_verified_output(self):
        with self.assertRaisesRegex(pdf.ParserError, 'OUTPUT_MISSING'):
            self.parser.report(self.source_id)
        self.apply()
        result = self.parser.report(self.source_id)
        self.assertEqual(result['review_status'], 'review_required')
        self.assertEqual(result['output_page_count'], 3)

    def test_output_directory_name_and_no_outside_write(self):
        self.apply()
        self.assertEqual(self.output().name, self.source_id)
        for path in self.root.rglob('*'):
            self.assertTrue(path.resolve().is_relative_to(self.root.resolve()))

    def test_all_command_help(self):
        for command in ('inspect', 'parse', 'verify-output', 'report'):
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                pdf.cli([command, '--help'])
            self.assertEqual(result.exception.code, 0)

    def test_dependency_version_is_pinned(self):
        requirements = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
        self.assertIn('PyMuPDF==' + fitz.__version__, requirements)


if __name__ == '__main__':
    unittest.main()
