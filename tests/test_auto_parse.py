"""Tests for automatic local parsing; no real model is loaded."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location('auto_parse_test', ROOT / 'scripts/auto_parse.py')
auto = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(auto)
WORKER_SPEC = importlib.util.spec_from_file_location(
    'paddle_worker_test', ROOT / 'scripts/paddleocr_worker.py')
worker_module = importlib.util.module_from_spec(WORKER_SPEC)
WORKER_SPEC.loader.exec_module(worker_module)


class AutoParseTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / 'tests/.runtime'; runtime.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='auto-parse-', dir=runtime)
        self.root = Path(self.temp.name)
        sid = 'src-aaaaaaaaaaaa'; self.sid = sid
        for folder in ('config', 'scripts', '.venv/paddleocr-vl/Scripts', 'models/cache',
                       f'sources-original/math1/calculus/{sid}',
                       f'vault/90-Parsed-Sources/{sid}/pages'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        source = self.root / f'sources-original/math1/calculus/{sid}/test.pdf'
        document = fitz.open(); page = document.new_page()
        page.insert_text((72, 72), '1. synthetic formula x1')
        source.write_bytes(document.tobytes()); document.close()
        self.source = source; self.digest = hashlib.sha256(source.read_bytes()).hexdigest()
        config = json.loads((ROOT / 'config/auto-parsing.example.json').read_text('utf-8'))
        config['environment_relative_path'] = '.venv/paddleocr-vl'
        config['worker_relative_path'] = 'scripts/paddleocr_worker.py'
        config['model_cache_relative_path'] = 'models/cache'
        config['layout_model_relative_path'] = 'models/cache/layout'
        config['vl_model_relative_path'] = 'models/cache/vl'
        config['critical_model_files'] = []
        config['sample_review_percent'] = 0
        (self.root / 'config/auto-parsing.example.json').write_text(json.dumps(config))
        (self.root / 'scripts/paddleocr_worker.py').write_text('# synthetic\n')
        (self.root / '.venv/paddleocr-vl/Scripts/python.exe').write_bytes(b'x')
        (self.root / 'models/cache/layout').mkdir(); (self.root / 'models/cache/vl').mkdir()
        (self.root / f'vault/90-Parsed-Sources/{sid}/pages/page-0001.md').write_text(
            '## 提取文本\n\n```text\n1、合成公式 x1，用于测试中文正文、数字和公式关系是否完整保留，并验证自动质量检查可以稳定通过。\n```\n', encoding='utf-8')
        self.record = {'source_id': sid, 'sha256': self.digest,
                       'stored_relative_path': source.relative_to(self.root).as_posix(),
                       'file_type': 'pdf', 'parser_status': 'parsed', 'page_count': 1}
        self.decision = {'page_number': 1, 'route': 'enhanced_parse_queued',
                         'quality_score': 20, 'reasons': ['formula_candidate']}
        self.parser = auto.AutoParser(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def worker(self, _preview, output, markdown='1、合成公式 $x_{1}$，用于测试中文正文、数字和公式关系是否完整保留，并验证自动质量检查可以稳定通过。'):
        (output / 'paddleocr.md').write_text(markdown, encoding='utf-8')
        (output / 'paddleocr-result.json').write_text('{}')
        report = {'ok': True, 'parser_id': 'paddleocr_vl_local',
                  'parser_version': '3.7.0', 'network_policy': 'socket_connections_blocked'}
        (output / 'worker-report.json').write_text(json.dumps(report))
        return report

    def test_dry_run_writes_nothing(self):
        with patch.object(self.parser, '_source', return_value=(self.record, self.decision)):
            result = self.parser.parse(self.sid, 1)
        self.assertFalse(result['apply'])
        self.assertFalse((self.root / result['target_relative_path']).exists())

    def test_apply_publishes_machine_checked_candidate_without_source_change(self):
        before = self.source.read_bytes()
        with (patch.object(self.parser, '_source', return_value=(self.record, self.decision)),
              patch.object(self.parser, '_run_worker', side_effect=self.worker)):
            result = self.parser.parse(self.sid, 1, apply=True)
        self.assertEqual(result['quality_status'], 'machine_checked_candidate')
        target = self.root / result['target_relative_path']
        manifest = json.loads((target / 'candidate-manifest.json').read_text('utf-8'))
        self.assertTrue(manifest['derived']); self.assertTrue(manifest['candidate_only'])
        self.assertEqual(manifest['review_status'], 'machine_checked_candidate')
        self.assertEqual(manifest['device'], 'gpu:0')
        self.assertIn('timing_seconds', manifest)
        self.assertEqual(self.source.read_bytes(), before)

    def test_missing_question_is_exception(self):
        def worker(preview, output):
            return self.worker(preview, output, '合成公式 $x_{1}$')
        with (patch.object(self.parser, '_source', return_value=(self.record, self.decision)),
              patch.object(self.parser, '_run_worker', side_effect=worker)):
            result = self.parser.parse(self.sid, 1, apply=True)
        self.assertEqual(result['quality_status'], 'exception_review')
        self.assertIn('QUESTION_NUMBER_COVERAGE_LOW', result['quality_issues'])

    def test_existing_target_refused(self):
        target = self.root / f'vault/90-Parsed-Sources/{self.sid}/enhanced/paddleocr-vl/page-0001'
        target.mkdir(parents=True)
        with patch.object(self.parser, '_source', return_value=(self.record, self.decision)):
            with self.assertRaisesRegex(auto.AutoParseError, 'TARGET_EXISTS'):
                self.parser.parse(self.sid, 1, apply=True)

    def test_batch_limit_and_page_range(self):
        record = dict(self.record); record['page_count'] = 30
        with patch.object(self.parser.manager, 'manifests', return_value=({self.sid: record}, [])):
            with self.assertRaisesRegex(auto.AutoParseError, 'BATCH_LIMIT_EXCEEDED'):
                self.parser.batch(self.sid, '1-26')
        for value in ('0', '3-2', '../1', '31'):
            with self.assertRaises(auto.AutoParseError):
                auto.parse_pages(value, 30)

    def test_escaped_latex_brace_is_not_false_failure(self):
        self.assertTrue(auto.balanced_math('$f(x)=\\left\\{x\\right.$'))
        self.assertFalse(auto.balanced_math('$x_{1$'))

    def test_paths_reject_escape(self):
        for value in ('../outside', 'C:/outside', '/outside', 'models/../outside'):
            self.assertFalse(auto.safe_relative(value))

    def test_worker_rejects_paths_outside_project(self):
        self.assertFalse(worker_module.safe_local_path(
            self.root / 'outside.png', ROOT, 'vault'))
        self.assertTrue(worker_module.safe_local_path(
            ROOT / 'vault/90-Parsed-Sources/.tmp-page-test', ROOT, 'vault'))


if __name__ == '__main__':
    unittest.main()
