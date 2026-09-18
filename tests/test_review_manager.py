"""Synthetic tests for traceable acceptance and revocation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location(
    'review_manager_test', ROOT / 'scripts/review_manager.py')
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


class ReviewManagerTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / 'tests/.runtime'; runtime.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='review-', dir=runtime)
        self.root = Path(self.temp.name)
        self.sid = 'src-aaaaaaaaaaaa'
        for relative in ('config', 'indexes', 'review-queue/acceptance-events',
                         'vault/90-Parsed-Sources'):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self.source = self.root / f'sources-original/408/computer-organization/{self.sid}/synthetic.pdf'
        self.source.parent.mkdir(parents=True); self.source.write_bytes(b'%PDF-1.4 synthetic')
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.record = {
            'source_id': self.sid, 'sha256': self.sha,
            'stored_relative_path': self.source.relative_to(self.root).as_posix(),
            'parser_status': 'parsed', 'parser_name': 'pymupdf-basic-text',
            'parser_version': '1.0', 'page_count': 2,
        }
        self.candidate = self.root / 'review-queue/corrected.md'
        metadata = {
            'source_id': self.sid, 'source_sha256': self.sha, 'source_page': 1,
            'derived': True, 'review_status': 'review_required',
            'parser_id': 'manual-corrected-transcription', 'parser_version': '1.0.0',
        }
        self.candidate.write_text('---\n' + '\n'.join(
            f'{key}: {json.dumps(value, ensure_ascii=False)}' for key, value in metadata.items()
        ) + '\n---\n人工核对后的补码内容\n', encoding='utf-8')
        self.manager = review.ReviewManager(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def source_context(self):
        return patch.multiple(
            self.manager.manager,
            verify=unittest.mock.Mock(return_value={'ok': True}),
            manifests=unittest.mock.Mock(return_value=({self.sid: self.record}, [])),
        )

    def accept(self, apply=True):
        with self.source_context():
            return self.manager.accept(
                self.sid, 1, 'review-queue/corrected.md', 'tester',
                '逐项对照合成原页', apply=apply)

    def verify(self):
        with self.source_context():
            return self.manager.verify()

    def test_accept_defaults_to_dry_run_and_writes_nothing(self):
        before = sorted(p.relative_to(self.root).as_posix()
                        for p in self.root.rglob('*') if p.is_file())
        result = self.accept(apply=False)
        after = sorted(p.relative_to(self.root).as_posix()
                       for p in self.root.rglob('*') if p.is_file())
        self.assertFalse(result['apply'])
        self.assertFalse(result['index_rebuild_required'])
        self.assertEqual(before, after)
        self.assertFalse(list((self.root / 'review-queue/acceptance-events').glob('*.json')))

    def test_paddle_machine_candidate_requires_explicit_accept(self):
        relative = (f'vault/90-Parsed-Sources/{self.sid}/enhanced/paddleocr-vl/'
                    'page-0001')
        folder = self.root / relative
        folder.mkdir(parents=True)
        (folder / 'paddleocr.md').write_text('合成候选 $x_{1}$', encoding='utf-8')
        (folder / 'candidate-manifest.json').write_text(json.dumps({
            'source_id': self.sid, 'source_page': 1,
            'review_status': 'machine_checked_candidate', 'candidate_only': True,
            'parser_id': 'paddleocr_vl_local', 'parser_version': '3.7.0',
        }), encoding='utf-8')
        candidate = relative + '/paddleocr.md'
        with self.source_context():
            preview = self.manager.accept(
                self.sid, 1, candidate, 'tester', 'synthetic explicit review')
        self.assertFalse(preview['apply'])
        self.assertEqual(preview['candidate_kind'], 'enhanced')
        self.assertFalse(list((self.root / 'review-queue/acceptance-events').glob('*.json')))

    def test_apply_creates_immutable_snapshot_and_trace_event(self):
        result = self.accept()
        snapshot = self.root / result['snapshot_relative_path']
        event = self.root / f'review-queue/acceptance-events/{result["event_id"]}.json'
        self.assertTrue(snapshot.is_file()); self.assertTrue(event.is_file())
        self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), result['snapshot_sha256'])
        self.assertTrue(self.verify()['ok'])
        with self.source_context():
            active = self.manager.active_snapshots()
        self.assertEqual([item['event_id'] for item in active], [result['event_id']])
        self.assertEqual(active[0]['content'], '人工核对后的补码内容')

    def test_candidate_change_invalidates_acceptance(self):
        self.accept()
        self.candidate.write_text(self.candidate.read_text('utf-8') + 'changed', encoding='utf-8')
        result = self.verify()
        self.assertFalse(result['ok'])
        self.assertEqual(result['issues'][0]['error'], 'ACCEPTED_CANDIDATE_CHANGED')

    def test_snapshot_tampering_invalidates_acceptance(self):
        accepted = self.accept()
        snapshot = self.root / accepted['snapshot_relative_path']
        snapshot.write_text(snapshot.read_text('utf-8') + 'tampered', encoding='utf-8')
        result = self.verify()
        self.assertFalse(result['ok'])
        self.assertEqual(result['issues'][0]['error'], 'ACCEPTED_SNAPSHOT_CHANGED')

    def test_source_integrity_failure_blocks_acceptance(self):
        with patch.object(self.manager.manager, 'verify', return_value={
                'ok': False, 'issues': [{'error': 'HASH_MISMATCH'}]}):
            with self.assertRaisesRegex(review.ReviewError, 'SOURCE_INTEGRITY_FAILED'):
                self.manager.accept(
                    self.sid, 1, 'review-queue/corrected.md', 'tester', 'notes')

    def test_status_skips_registered_sources_not_yet_parsed(self):
        waiting = {
            **self.record, 'source_id': 'src-bbbbbbbbbbbb',
            'sha256': 'b' * 64, 'parser_status': 'not_started',
            'parser_name': None, 'parser_version': None, 'page_count': None,
        }
        with patch.object(self.manager.manager, 'verify', return_value={'ok': True}), \
             patch.object(self.manager.manager, 'manifests', return_value=(
                 {self.sid: self.record, waiting['source_id']: waiting}, [])):
            result = self.manager.status()
        self.assertTrue(result['ok'])
        self.assertEqual(result['active_accepted_count'], 0)

    def test_revoke_is_append_only_and_preserves_snapshot(self):
        accepted = self.accept(); snapshot = self.root / accepted['snapshot_relative_path']
        snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        with self.source_context():
            preview = self.manager.revoke(accepted['event_id'], 'tester', '发现校对问题')
        self.assertFalse(preview['apply'])
        self.assertEqual(len(list((self.root / 'review-queue/acceptance-events').glob('rev-*.json'))), 0)
        with self.source_context():
            applied = self.manager.revoke(
                accepted['event_id'], 'tester', '发现校对问题', apply=True)
        self.assertTrue(applied['snapshot_preserved'])
        self.assertTrue(snapshot.is_file())
        self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), snapshot_hash)
        verified = self.verify()
        self.assertTrue(verified['ok'])
        self.assertEqual(verified['active_accepted_count'], 0)
        self.assertEqual(verified['revoked_acceptance_count'], 1)

    def test_second_active_acceptance_is_refused(self):
        self.accept()
        with self.assertRaisesRegex(review.ReviewError, 'PAGE_ALREADY_ACCEPTED'):
            self.accept()

    def test_page_can_be_reaccepted_only_after_append_only_revoke(self):
        first = self.accept()
        with self.source_context():
            self.manager.revoke(first['event_id'], 'tester', '修订后重新审核', apply=True)
        second = self.accept()
        self.assertNotEqual(first['event_id'], second['event_id'])
        verified = self.verify()
        self.assertTrue(verified['ok'])
        self.assertEqual(verified['acceptance_count'], 2)
        self.assertEqual(verified['active_accepted_count'], 1)
        self.assertEqual(verified['revoked_acceptance_count'], 1)

    def test_path_traversal_and_unknown_candidate_are_refused(self):
        with self.source_context():
            with self.assertRaisesRegex(review.ReviewError, 'CANDIDATE_PATH_INVALID'):
                self.manager.accept(self.sid, 1, '../outside.md', 'tester', 'notes')
        other = self.root / 'review-queue/unstructured.md'; other.write_text('text', encoding='utf-8')
        with self.source_context():
            with self.assertRaisesRegex(review.ReviewError, 'CANDIDATE_FRONTMATTER_INVALID'):
                self.manager.accept(self.sid, 1, 'review-queue/unstructured.md', 'tester', 'notes')

    def test_orphan_snapshot_blocks_verification_but_is_not_deleted(self):
        orphan = self.root / f'vault/90-Parsed-Sources/{self.sid}/accepted/pages/page-0001/acc-{"b"*32}.md'
        orphan.parent.mkdir(parents=True); orphan.write_text('orphan', encoding='utf-8')
        result = self.verify()
        self.assertFalse(result['ok'])
        self.assertEqual(result['issues'][0]['error'], 'ACCEPTED_SNAPSHOT_INVENTORY_MISMATCH')
        self.assertTrue(orphan.exists())

    def test_event_publish_failure_never_creates_active_acceptance(self):
        original = self.manager.manager.write_json
        with self.source_context(), patch.object(
                self.manager.manager, 'write_json', side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):
                self.manager.accept(self.sid, 1, 'review-queue/corrected.md',
                                    'tester', 'notes', apply=True)
        snapshots = list((self.root / 'vault/90-Parsed-Sources').glob(
            'src-*/accepted/pages/page-*/*.md'))
        self.assertEqual(len(snapshots), 1)
        self.assertFalse(list((self.root / 'review-queue/acceptance-events').glob('acc-*.json')))
        self.assertTrue(snapshots[0].exists())

    def test_all_commands_have_help(self):
        for command in ('inspect', 'accept', 'revoke', 'verify', 'status'):
            with self.assertRaises(SystemExit) as raised:
                review.cli([command, '--help'])
            self.assertEqual(raised.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
