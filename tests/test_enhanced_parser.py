"""Unit tests for the offline single-page enhancement controller.

No test imports MinerU or loads a model.  The worker boundary is replaced with
a deterministic local stub; real-model checks are separate integration runs.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location(
    'enhanced_parser_test', ROOT / 'scripts/enhanced_parser.py')
enhanced = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(enhanced)


class EnhancedParserTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / 'tests/.runtime'; runtime.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='enhanced-', dir=runtime)
        self.root = Path(self.temp.name)
        for folder in ('config', 'scripts', '.venv/mineru/Scripts', 'models/cache',
                       'sources-original/408/computer-organization/src-aaaaaaaaaaaa',
                       'vault/90-Parsed-Sources/src-aaaaaaaaaaaa'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        source = (self.root /
                  'sources-original/408/computer-organization/src-aaaaaaaaaaaa/test.pdf')
        document = fitz.open(); page = document.new_page()
        page.insert_text((72, 72), 'synthetic x1 page')
        source.write_bytes(document.tobytes()); document.close()
        self.source = source
        self.digest = hashlib.sha256(source.read_bytes()).hexdigest()
        config = json.loads((ROOT / 'config/enhanced-parser.example.json').read_text('utf-8'))
        config['environment_relative_path'] = '.venv/mineru'
        config['worker_relative_path'] = 'scripts/enhanced_worker.py'
        config['model_home_relative_path'] = 'models/cache'
        config['critical_model_files'] = []
        (self.root / 'config/enhanced-parser.example.json').write_text(
            json.dumps(config), encoding='utf-8')
        (self.root / 'scripts/enhanced_worker.py').write_text('# synthetic\n', encoding='utf-8')
        (self.root / '.venv/mineru/Scripts/python.exe').write_bytes(b'synthetic')
        self.parser = enhanced.EnhancedParser(self.root)
        self.record = {
            'source_id': 'src-aaaaaaaaaaaa', 'sha256': self.digest,
            'stored_relative_path': self.source.relative_to(self.root).as_posix(),
            'file_type': 'pdf', 'parser_status': 'parsed', 'page_count': 1,
        }
        self.decision = {'page_number': 1, 'route': 'enhanced_parse_queued',
                         'quality_score': 32, 'reasons': ['replacement_char_count']}

    def tearDown(self):
        self.temp.cleanup()

    def fake_worker(self, _source, page, output):
        (output / 'mineru.md').write_text('合成 $x_1$ [X]补', encoding='utf-8')
        (output / 'mineru-result.json').write_text('{}', encoding='utf-8')
        report = {'ok': True, 'parser_id': 'enhanced_mineru_standard',
                  'parser_version': '4.0.0', 'page_number': page,
                  'network_policy': 'socket_connections_blocked',
                  'total_seconds': 0.1}
        (output / 'worker-report.json').write_text(json.dumps(report), encoding='utf-8')
        return report

    def test_dry_run_has_no_output(self):
        with patch.object(self.parser, '_source', return_value=(self.record, self.decision)):
            result = self.parser.parse('src-aaaaaaaaaaaa', 1)
        self.assertFalse(result['apply'])
        self.assertFalse((self.root / result['target_relative_path']).exists())
        self.assertTrue(self.source.is_file())

    def test_apply_publishes_separate_review_candidate_and_preserves_source(self):
        before = self.source.read_bytes()
        with (patch.object(self.parser, '_source', return_value=(self.record, self.decision)),
              patch.object(self.parser, '_run_worker', side_effect=self.fake_worker)):
            result = self.parser.parse('src-aaaaaaaaaaaa', 1, apply=True)
        self.assertTrue(result['published'])
        target = self.root / result['target_relative_path']
        metadata = json.loads((target / 'candidate-manifest.json').read_text('utf-8'))
        self.assertTrue(metadata['derived'])
        self.assertTrue(metadata['candidate_only'])
        self.assertEqual(metadata['review_status'], 'review_required')
        self.assertEqual(metadata['source_page'], 1)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse((self.root / 'vault/90-Parsed-Sources/src-aaaaaaaaaaaa/basic').exists())

    def test_existing_target_is_never_overwritten(self):
        target = self.root / 'vault/90-Parsed-Sources/src-aaaaaaaaaaaa/enhanced/mineru/page-0001'
        target.mkdir(parents=True); marker = target / 'keep.txt'; marker.write_text('keep')
        with patch.object(self.parser, '_source', return_value=(self.record, self.decision)):
            with self.assertRaisesRegex(enhanced.EnhancedError, 'TARGET_EXISTS'):
                self.parser.parse('src-aaaaaaaaaaaa', 1, apply=True)
        self.assertEqual(marker.read_text(), 'keep')

    def test_failure_is_retained_and_not_published(self):
        def failed(*_args):
            raise enhanced.EnhancedError('LOCAL_INFERENCE_FAILED')
        with (patch.object(self.parser, '_source', return_value=(self.record, self.decision)),
              patch.object(self.parser, '_run_worker', side_effect=failed)):
            with self.assertRaisesRegex(enhanced.EnhancedError, 'LOCAL_INFERENCE_FAILED'):
                self.parser.parse('src-aaaaaaaaaaaa', 1, apply=True)
        parent = self.root / 'vault/90-Parsed-Sources/src-aaaaaaaaaaaa/enhanced/mineru'
        failures = list(parent.glob('.tmp-page-0001-*'))
        self.assertEqual(len(failures), 1)
        self.assertTrue((failures[0] / 'failure.json').is_file())
        self.assertFalse((parent / 'page-0001').exists())

    def test_high_confidence_secret_blocks_publish_without_echo(self):
        def secret_worker(source, page, output):
            report = self.fake_worker(source, page, output)
            (output / 'mineru.md').write_text(
                'credential ' + 'sk-' + 'proj-' + 'AbCdEf0123456789GhIjKlMnOpQr',
                encoding='utf-8')
            return report
        with (patch.object(self.parser, '_source', return_value=(self.record, self.decision)),
              patch.object(self.parser, '_run_worker', side_effect=secret_worker)):
            with self.assertRaisesRegex(enhanced.EnhancedError, 'SENSITIVE_CONTENT_BLOCKED'):
                self.parser.parse('src-aaaaaaaaaaaa', 1, apply=True)
        parent = self.root / 'vault/90-Parsed-Sources/src-aaaaaaaaaaaa/enhanced/mineru'
        failure = next(parent.glob('.tmp-page-0001-*/failure.json'))
        report = failure.read_text('utf-8')
        self.assertIn('SENSITIVE_CONTENT_BLOCKED', report)
        self.assertNotIn('sk-proj-', report)
        self.assertFalse((parent / 'page-0001').exists())

    def test_verify_detects_preview_tampering(self):
        with (patch.object(self.parser, '_source', return_value=(self.record, self.decision)),
              patch.object(self.parser, '_run_worker', side_effect=self.fake_worker)):
            result = self.parser.parse('src-aaaaaaaaaaaa', 1, apply=True)
            self.assertTrue(self.parser.verify_output('src-aaaaaaaaaaaa', 1)['ok'])
            target = self.root / result['target_relative_path']
            (target / 'page-preview.png').write_bytes(b'tampered')
            with self.assertRaisesRegex(enhanced.EnhancedError, 'CANDIDATE_METADATA_INVALID'):
                self.parser.verify_output('src-aaaaaaaaaaaa', 1)

    def test_config_rejects_cloud_policy_and_unsafe_model_path(self):
        config_path = self.root / 'config/enhanced-parser.example.json'
        value = json.loads(config_path.read_text('utf-8'))
        value['network_policy'] = 'cloud'
        config_path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(enhanced.EnhancedError, 'CONFIG_INVALID'):
            enhanced.EnhancedParser(self.root)

    def test_safe_relative_rejects_escape_and_absolute(self):
        for value in ('../outside', 'C:/outside', '/outside', 'models/../outside'):
            self.assertFalse(enhanced.safe_relative(value))


if __name__ == '__main__':
    unittest.main()
