"""Synthetic tests for the Claudian read-only pilot contract."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location(
    'claudian_pilot_test', ROOT / 'scripts/validate_claudian_pilot.py')
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


class ClaudianPilotTests(unittest.TestCase):
    def test_project_policy_contains_every_guard(self):
        result = pilot.check_policy(ROOT)
        self.assertTrue(result['ok'])
        self.assertEqual(result['missing_requirement_count'], 0)

    def test_incomplete_policy_fails_without_echoing_content(self):
        runtime = ROOT / 'tests/.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as folder:
            root = Path(folder)
            (root / 'vault').mkdir()
            (root / pilot.POLICY_RELATIVE).write_text('study_readonly_pilot', encoding='utf-8')
            result = pilot.check_policy(root)
            self.assertFalse(result['ok'])
            self.assertEqual(result['error'], 'POLICY_INCOMPLETE')
            self.assertNotIn('study_readonly_pilot', json.dumps(result))

    def test_pilot_requires_no_approved_answer_and_separate_candidates(self):
        formal = {'status': 'no_approved_content', 'message': '暂无已审核资料', 'results': []}
        base = {
            'source_id': pilot.PILOT_SOURCE, 'page_number': 2,
            'parser_id': 'pymupdf-basic-text', 'parser_version': '1.0',
            'review_status': 'review_required', 'risk': 'UNREVIEWED_CANDIDATE',
            'obsidian_wikilink': '[[90-Parsed-Sources/base]]',
            'relative_path': 'vault/AGENTS.md', 'version_kind': 'basic',
        }
        enhanced = dict(base, parser_id='enhanced_mineru_standard',
                        parser_version='4.0.0', version_kind='enhanced')
        engine = unittest.mock.Mock()
        engine.search.side_effect = [formal, {'results': [base, enhanced]}]
        fake_module = unittest.mock.Mock()
        fake_module.LocalSearch.return_value = engine
        with patch.object(pilot, 'load_local_search', return_value=fake_module):
            result = pilot.run_pilot(ROOT)
        self.assertTrue(result['ok'])
        self.assertEqual(result['preview_versions'], ['basic', 'enhanced'])
        self.assertNotIn('snippet', json.dumps(result))

    def test_candidate_cannot_replace_formal_answer(self):
        engine = unittest.mock.Mock()
        engine.search.side_effect = [
            {'status': 'matches', 'results': [{'candidate': True}]},
            {'results': []},
        ]
        fake_module = unittest.mock.Mock()
        fake_module.LocalSearch.return_value = engine
        with patch.object(pilot, 'load_local_search', return_value=fake_module):
            result = pilot.run_pilot(ROOT)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'PILOT_CONTRACT_FAILED')


if __name__ == '__main__':
    unittest.main()
