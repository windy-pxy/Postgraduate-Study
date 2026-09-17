"""Synthetic-only tests for the local accepted-by-default page index."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location('local_search_test', ROOT / 'scripts/local_search.py')
search = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(search)


class LocalSearchTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / 'tests/.runtime'; runtime.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='search-', dir=runtime)
        self.root = Path(self.temp.name)
        self.sid = 'src-aaaaaaaaaaaa'
        self.source = self.root / f'sources-original/408/computer-organization/{self.sid}/synthetic.pdf'
        self.source.parent.mkdir(parents=True); self.source.write_bytes(b'%PDF synthetic')
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.record = {
            'source_id': self.sid, 'sha256': self.sha,
            'stored_relative_path': self.source.relative_to(self.root).as_posix(),
            'parser_status': 'parsed', 'parser_name': 'pymupdf-basic-text',
            'parser_version': '1.0', 'page_count': 2,
        }
        (self.root / 'config').mkdir(); (self.root / 'indexes').mkdir()
        (self.root / 'review-queue/acceptance-events').mkdir(parents=True)
        (self.root / 'vault/90-Parsed-Sources').mkdir(parents=True)
        self.engine = search.LocalSearch(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def accepted(self, page=1, content='计算机组成原理 已人工审核'):
        path = self.root / f'review-queue/manual-page-{page:04d}.md'
        metadata = {
            'source_id': self.sid, 'source_sha256': self.sha, 'source_page': page,
            'derived': True, 'review_status': 'review_required',
            'parser_id': 'human-reviewed-merge', 'parser_version': '1',
        }
        path.write_text('---\n' + '\n'.join(
            f'{key}: {json.dumps(value, ensure_ascii=False)}' for key, value in metadata.items()
        ) + '\n---\n' + content + '\n', encoding='utf-8')
        with patch.object(self.engine.reviews.manager, 'verify', return_value={'ok': True}), \
             patch.object(self.engine.reviews.manager, 'manifests',
                          return_value=({self.sid: self.record}, [])):
            result = self.engine.reviews.accept(
                self.sid, page, path.relative_to(self.root).as_posix(),
                'synthetic-reviewer', 'synthetic review', apply=True)
        return self.root / result['snapshot_relative_path'], result['event_id']

    def candidates(self):
        basic = self.root / f'vault/90-Parsed-Sources/{self.sid}/pages/page-0002.md'
        basic.parent.mkdir(parents=True, exist_ok=True)
        basic.write_text(
            f'---\nsource_id: "{self.sid}"\nsource_page: 2\nderived: true\n'
            'parse_status: "extracted"\nreview_status: "review_required"\n---\n'
            '```text\n补码基础候选 x1\n```\n', encoding='utf-8')
        enhanced = self.root / f'vault/90-Parsed-Sources/{self.sid}/enhanced/mineru/page-0002'
        enhanced.mkdir(parents=True)
        (enhanced / 'mineru.md').write_text('补码增强候选 $x_1$', encoding='utf-8')
        (enhanced / 'candidate-manifest.json').write_text(json.dumps({
            'parser_id': 'enhanced_mineru_standard', 'parser_version': '4.0.0'}), encoding='utf-8')

    def context(self):
        return patch.multiple(
            self.engine.manager,
            verify=unittest.mock.DEFAULT,
            manifests=unittest.mock.DEFAULT,
        )

    def build_with_records(self, **kwargs):
        with patch.object(self.engine.manager, 'verify', return_value={'ok': True}), \
             patch.object(self.engine.manager, 'manifests', return_value=({self.sid: self.record}, [])), \
             patch.object(self.engine.reviews.manager, 'verify', return_value={'ok': True}), \
             patch.object(self.engine.reviews.manager, 'manifests',
                          return_value=({self.sid: self.record}, [])), \
             patch.object(search, 'EnhancedParser') as verifier:
            verifier.return_value.verify_output.return_value = {'ok': True}
            return self.engine.build(**kwargs)

    def verify_with_records(self):
        with patch.object(self.engine.manager, 'verify', return_value={'ok': True}), \
             patch.object(self.engine.manager, 'manifests', return_value=({self.sid: self.record}, [])), \
             patch.object(self.engine.reviews.manager, 'verify', return_value={'ok': True}), \
             patch.object(self.engine.reviews.manager, 'manifests',
                          return_value=({self.sid: self.record}, [])):
            return self.engine.verify()

    def search_with_records(self, *args, **kwargs):
        with patch.object(self.engine.reviews.manager, 'verify', return_value={'ok': True}), \
             patch.object(self.engine.reviews.manager, 'manifests',
                          return_value=({self.sid: self.record}, [])):
            return self.engine.search(*args, **kwargs)

    def test_chinese_search_and_trace_fields_for_accepted_page(self):
        _, acceptance_id = self.accepted(); result = self.build_with_records()
        self.assertEqual(result['accepted_count'], 1)
        found = self.search_with_records('计算机')
        self.assertEqual(len(found['results']), 1)
        item = found['results'][0]
        self.assertEqual(item['source_id'], self.sid)
        self.assertEqual(item['page_number'], 1)
        self.assertEqual(item['review_status'], 'accepted')
        self.assertIsNone(item['risk'])
        self.assertIn('[[90-Parsed-Sources/', item['obsidian_wikilink'])
        self.assertEqual(item['source_sha256'], self.sha)
        self.assertEqual(item['acceptance_event_id'], acceptance_id)

    def test_existing_accepted_corpus_with_no_match_is_not_reported_empty(self):
        self.accepted(); self.build_with_records()
        result = self.search_with_records('不存在的词')
        self.assertEqual(result['status'], 'no_matches')
        self.assertNotIn('message', result)

    def test_no_accepted_content_is_explicit_even_when_candidates_indexed(self):
        self.candidates(); self.build_with_records(include_review_candidates=True)
        result = self.search_with_records('补码')
        self.assertEqual(result['status'], 'no_approved_content')
        self.assertEqual(result['message'], '暂无已审核资料')
        self.assertEqual(result['results'], [])

    def test_preview_keeps_basic_and_enhanced_versions_distinct(self):
        self.candidates(); self.build_with_records(include_review_candidates=True)
        result = self.search_with_records('补码', include_review_candidates=True)
        self.assertEqual({item['version_kind'] for item in result['results']}, {'basic', 'enhanced'})
        self.assertTrue(all(item['risk'] == 'UNREVIEWED_CANDIDATE' for item in result['results']))
        self.assertEqual({item['parser_id'] for item in result['results']},
                         {'pymupdf-basic-text', 'enhanced_mineru_standard'})

    def test_source_page_filters_and_short_keyword_fallback(self):
        self.accepted(1, '页一 AI'); self.accepted(2, '页二 AI')
        self.build_with_records()
        result = self.search_with_records('AI', source_id=self.sid, page_number=2)
        self.assertEqual([item['page_number'] for item in result['results']], [2])

    def test_existing_index_requires_explicit_rebuild(self):
        self.accepted(); self.build_with_records()
        with self.assertRaisesRegex(search.SearchError, 'INDEX_EXISTS_USE_REBUILD'):
            self.build_with_records()
        result = self.build_with_records(rebuild=True)
        self.assertEqual(result['document_count'], 1)

    def test_verify_detects_changed_content(self):
        path, _ = self.accepted(); self.build_with_records()
        self.assertTrue(self.verify_with_records()['ok'])
        path.write_text(path.read_text('utf-8') + 'changed', encoding='utf-8')
        with self.assertRaisesRegex(search.SearchError, 'INDEX_ACCEPTANCE_STATE_INVALID'):
            self.verify_with_records()

    def test_revoke_invalidates_stale_index_and_rebuild_removes_page(self):
        _, acceptance_id = self.accepted(content='补码已审核')
        self.build_with_records()
        self.assertEqual(len(self.search_with_records('补码')['results']), 1)
        with patch.object(self.engine.reviews.manager, 'verify', return_value={'ok': True}), \
             patch.object(self.engine.reviews.manager, 'manifests',
                          return_value=({self.sid: self.record}, [])):
            self.engine.reviews.revoke(
                acceptance_id, 'synthetic-reviewer', 'synthetic revoke', apply=True)
        with self.assertRaisesRegex(
                search.SearchError, 'INDEX_ACCEPTANCE_STATE_CHANGED_REBUILD_REQUIRED'):
            self.search_with_records('补码')
        self.build_with_records(rebuild=True)
        result = self.search_with_records('补码')
        self.assertEqual(result['status'], 'no_approved_content')

    def test_integrity_failure_blocks_build(self):
        with patch.object(self.engine.manager, 'verify', return_value={'ok': False}):
            with self.assertRaisesRegex(search.SearchError, 'SOURCE_INTEGRITY_FAILED'):
                self.engine.build()
        self.assertFalse((self.root / search.INDEX_RELATIVE).exists())

    def test_invalid_inputs_and_accepted_path_escape_rejected(self):
        self.accepted(); self.build_with_records()
        for query in ('', ' '):
            with self.assertRaisesRegex(search.SearchError, 'QUERY_INVALID'):
                self.search_with_records(query)
        with self.assertRaisesRegex(search.SearchError, 'SOURCE_ID_INVALID'):
            self.search_with_records('计算机', source_id='../outside')
        with self.assertRaisesRegex(search.SearchError, 'PAGE_NUMBER_INVALID'):
            self.search_with_records('计算机', page_number=0)
        self.assertFalse(search.safe_relative('../outside'))
        self.assertFalse(search.safe_relative('C:/outside'))


if __name__ == '__main__':
    unittest.main()
