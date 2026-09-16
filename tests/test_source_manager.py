"""Generated fixtures only, inside tests/.runtime; never use the real source store."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location('source_manager_test', ROOT / 'scripts/source_manager.py')
sm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sm)


def office_bytes(kind):
    """A synthetic container; its main part is not a learning document."""
    main = 'word/document.xml' if kind == 'docx' else 'ppt/presentation.xml'
    mime = ('application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
            if kind == 'docx' else 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml')
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/{main}" ContentType="{mime}"/></Types>')
        archive.writestr('_rels/.rels', f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="{main}"/></Relationships>')
        archive.writestr(main, '<synthetic-fixture/>')
    return data.getvalue()


class SourceTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / 'tests/.runtime'
        # Validate the exact cleanup parent before creating any scratch directory.
        guard = sm.SourceManager(ROOT)
        guard.path('tests/.runtime')
        runtime.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='source-test-', dir=runtime)
        self.root = Path(self.temp.name)
        self.assertTrue(self.root.resolve().is_relative_to(runtime.resolve()))
        for directory in ('import-inbox', 'sources-original/math1', 'sources-original/408',
                          'config/source-manifests', 'review-queue/import-plans'):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / sm.BASELINE).write_bytes(sm.json_bytes({'schema_version': 2, 'algorithm': 'sha256', 'sources': {}}))
        self.manager = sm.SourceManager(self.root)

    def tearDown(self):
        # All content under this newly generated sandbox belongs to this test.
        self.assertTrue(self.root.resolve().is_relative_to((ROOT / 'tests/.runtime').resolve()))
        self.temp.cleanup()

    def put(self, name='fixture.pdf', data=b'%PDF-1.7\nsynthetic test only\n%%EOF'):
        path = self.root / 'import-inbox' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path.relative_to(self.root).as_posix()

    def plan(self, path=None, **kwargs):
        return self.manager.plan(path or self.put(), course='math1', subject='calculus', source_type='textbook', save=True, **kwargs)

    def imported(self):
        plan = self.plan()
        result = self.manager.apply(plan['plan_path'], execute=True)
        record = self.manager.load_json(sm.MANIFESTS + '/' + result['source_id'] + '.json')
        return plan, record

    def codes(self):
        return {item['error'] for item in self.manager.verify()['issues']}

    def test_pdf_signature(self):
        self.assertEqual(self.manager.detect(self.put()), 'pdf')

    def test_fake_pdf_extension(self):
        with self.assertRaisesRegex(sm.SourceError, 'SIGNATURE_MISMATCH'):
            self.manager.detect(self.put(data=b'not a PDF'))

    def test_supported_office_containers(self):
        for kind in ('docx', 'pptx'):
            self.assertEqual(self.manager.detect(self.put('fixture.' + kind, office_bytes(kind))), kind)

    def test_office_mismatch_and_invalid_zip(self):
        for content in (b'not a ZIP', office_bytes('docx')):
            with self.assertRaises(sm.SourceError):
                self.manager.detect(self.put('fixture.pptx', content))

    def test_office_missing_structure(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('unrelated.txt', 'synthetic')
        with self.assertRaises(sm.SourceError):
            self.manager.detect(self.put('fixture.docx', data.getvalue()))

    def test_office_metadata_xxe_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('[Content_Types].xml', '<!DOCTYPE a><Types/>')
            archive.writestr('_rels/.rels', '<Relationships/>')
            archive.writestr('word/document.xml', '<fixture/>')
        with self.assertRaisesRegex(sm.SourceError, 'OFFICE_XML_UNSAFE'):
            self.manager.detect(self.put('fixture.docx', data.getvalue()))

    def test_office_embedded_traversal_refused(self):
        data = io.BytesIO(office_bytes('docx'))
        with zipfile.ZipFile(data, 'a') as archive:
            archive.writestr('../outside', 'synthetic')
        with self.assertRaisesRegex(sm.SourceError, 'OFFICE_STRUCTURE_INVALID'):
            self.manager.detect(self.put('fixture.docx', data.getvalue()))

    def test_empty_inbox(self):
        self.assertEqual(self.manager.scan(), [])
        self.assertEqual(self.manager.status()['inbox_file_count'], 0)

    def test_unsupported_not_read_or_imported(self):
        path = self.put('fixture.ppt', b'synthetic')
        with patch.object(self.manager, 'reader', side_effect=AssertionError('unsupported content read')):
            with self.assertRaisesRegex(sm.SourceError, 'UNSUPPORTED'):
                self.manager.detect(path)
        self.assertEqual(self.manager.scan()[0]['status'], 'unsupported')
        with self.assertRaisesRegex(sm.SourceError, 'UNSUPPORTED'):
            self.plan(path)

    def test_duplicate_hash_and_stable_id_after_rename(self):
        plan, record = self.imported()
        duplicate = self.put('renamed.pdf')
        digest, _ = self.manager.digest(duplicate)
        self.assertEqual(sm.source_id(digest, {record['source_id']: record['sha256']}), record['source_id'])
        with self.assertRaisesRegex(sm.SourceError, 'DUPLICATE_SOURCE'):
            self.plan(duplicate)
        self.assertTrue(all(row['status'] == 'duplicate' for row in self.manager.scan()))

    def test_duplicates_within_inbox(self):
        self.put('a.pdf')
        self.put('b.pdf')
        self.assertEqual([r['status'] for r in self.manager.scan()], ['needs_review', 'duplicate'])

    def test_same_name_different_content(self):
        first = self.plan(self.put('a/same.pdf', b'%PDF-1.7\none'))
        second = self.plan(self.put('b/same.pdf', b'%PDF-1.7\ntwo'))
        self.assertNotEqual(first['plan']['source_id'], second['plan']['source_id'])
        for plan in (first, second):
            self.manager.apply(plan['plan_path'], execute=True)
        self.assertEqual(self.manager.verify()['registered_count'], 2)
        self.assertTrue(self.manager.verify()['ok'])

    def test_id_prefix_collision_extends_without_changing_existing(self):
        first = 'a' * 12 + 'b' * 52
        second = 'a' * 12 + 'c' * 52
        sid = sm.source_id(first, {})
        self.assertEqual(sid, 'src-' + first[:12])
        self.assertEqual(sm.source_id(second, {sid: first}), 'src-' + second[:13])
        self.assertEqual(sm.source_id(first, {sid: first}), sid)

    def test_path_traversal_absolute_ads_and_wrong_area(self):
        for path in ('../outside.pdf', 'import-inbox/../outside.pdf', 'D:/outside.pdf',
                     str(ROOT / 'outside.pdf'), '\\\\server\\share\\file.pdf',
                     'import-inbox/file.pdf:stream', '/outside.pdf'):
            with self.subTest(path=path), self.assertRaises(sm.SourceError):
                self.manager.path(path, 'import-inbox')
        with self.assertRaisesRegex(sm.SourceError, 'PATH_WRONG_AREA'):
            self.manager.path('sources-original/file.pdf', 'import-inbox')

    def test_project_outside_root(self):
        with self.assertRaisesRegex(sm.SourceError, 'ROOT_OUTSIDE_PROJECT'):
            sm.SourceManager(Path('Z:/not-project'))

    def test_symlink_and_junction_rejected_before_open(self):
        for mode, attrs in ((stat.S_IFLNK, 0), (stat.S_IFDIR, 0x400)):
            with patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=mode, st_file_attributes=attrs)), \
                    patch.object(Path, 'open') as opened:
                with self.assertRaisesRegex(sm.SourceError, 'LINK_OR_REPARSE_POINT'):
                    self.manager.path('import-inbox/file.pdf')
                opened.assert_not_called()

    def test_hardlinks_refused(self):
        info = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0, st_nlink=2)
        with patch.object(Path, 'lstat', return_value=info):
            with self.assertRaisesRegex(sm.SourceError, 'HARDLINK_REFUSED'):
                self.manager._metadata(self.root / 'unused')

    def test_invalid_classification(self):
        path = self.put()
        for values in (('bad', 'calculus', 'textbook'), ('math1', 'bad', 'textbook'),
                       ('math1', 'calculus', 'bad'), ('408', 'calculus', 'textbook')):
            with self.assertRaises(sm.SourceError):
                self.manager.plan(path, *values)

    def test_unconfirmed_plan_goes_to_review(self):
        result = self.manager.plan(self.put(), save=True)
        plan = result['plan']
        self.assertEqual(plan['status'], 'needs_review')
        self.assertEqual(plan['confirmed_fields'], [])
        self.assertIsNone(plan['target_relative_path'])
        self.assertTrue(all(v['status'] == 'suggested' for v in plan['suggested'].values()))
        with self.assertRaisesRegex(sm.SourceError, 'NEEDS_REVIEW'):
            self.manager.apply(result['plan_path'], execute=True)

    def test_plan_dry_run_writes_nothing(self):
        path = self.put()
        before = set(self.root.rglob('*'))
        result = self.manager.plan(path, 'math1', 'calculus', 'textbook')
        self.assertTrue(result['dry_run'])
        self.assertEqual(set(self.root.rglob('*')), before)

    def test_apply_default_dry_run_no_copy(self):
        plan = self.plan()
        before = set(self.root.rglob('*'))
        self.assertTrue(self.manager.apply(plan['plan_path'])['dry_run'])
        self.assertEqual(set(self.root.rglob('*')), before)

    def test_apply_preserves_inbox_and_hash(self):
        plan, record = self.imported()
        self.assertTrue((self.root / plan['plan']['input_relative_path']).exists())
        self.assertEqual(self.manager.digest(record['stored_relative_path']), (record['sha256'], record['size_bytes']))
        self.assertTrue(self.manager.verify()['ok'])

    def test_changed_inbox_before_apply(self):
        plan = self.plan()
        (self.root / plan['plan']['input_relative_path']).write_bytes(b'%PDF-1.7\nchanged')
        with self.assertRaisesRegex(sm.SourceError, 'INBOX_CHANGED'):
            self.manager.apply(plan['plan_path'], execute=True)

    def test_missing_inbox_before_apply(self):
        plan = self.plan()
        (self.root / plan['plan']['input_relative_path']).unlink()  # generated fixture only
        with self.assertRaises(OSError):
            self.manager.apply(plan['plan_path'], execute=True)

    def test_existing_target_directory_refused(self):
        plan = self.plan()
        (self.root / plan['plan']['target_relative_path']).parent.mkdir(parents=True)
        with self.assertRaisesRegex(sm.SourceError, 'TARGET_EXISTS'):
            self.manager.apply(plan['plan_path'], execute=True)

    def test_existing_target_file_never_overwritten(self):
        plan = self.plan()
        target = self.root / plan['plan']['target_relative_path']
        target.parent.mkdir(parents=True)
        target.write_bytes(b'existing synthetic sentinel')
        with self.assertRaises(sm.SourceError):
            self.manager.apply(plan['plan_path'], execute=True)
        self.assertEqual(target.read_bytes(), b'existing synthetic sentinel')

    def test_atomic_publish_failure_cleans_only_own_temporaries(self):
        plan = self.plan()
        with patch.object(self.manager, '_publish', side_effect=OSError('simulated failure')):
            with self.assertRaises(OSError):
                self.manager.apply(plan['plan_path'], execute=True)
        self.assertEqual(list((self.root / 'sources-original').rglob('*.tmp')), [])
        self.assertTrue(self.manager.verify()['ok'])

    def test_partial_copy_failure(self):
        plan = self.plan()
        def broken(relative, stream):
            stream.write(b'partial')
            raise OSError('synthetic failure')
        with patch.object(self.manager, '_copy', side_effect=broken), self.assertRaises(OSError):
            self.manager.apply(plan['plan_path'], execute=True)
        self.assertTrue(self.manager.verify()['ok'])
        self.assertFalse(list((self.root / 'sources-original').rglob('*.tmp')))

    def test_copy_hash_mismatch(self):
        plan = self.plan()
        with patch.object(self.manager, '_copy', side_effect=lambda r, stream: stream.write(b'wrong')):
            with self.assertRaisesRegex(sm.SourceError, 'COPY_HASH_MISMATCH'):
                self.manager.apply(plan['plan_path'], execute=True)
        self.assertTrue(self.manager.verify()['ok'])

    def test_no_clobber_atomic_publication(self):
        temp = self.root / 'config/temp.tmp'
        existing = self.root / 'config/existing.json'
        temp.write_bytes(b'new')
        existing.write_bytes(b'old')
        with self.assertRaises(FileExistsError):
            self.manager._publish(temp, existing)
        self.assertEqual(existing.read_bytes(), b'old')

    def test_manifest_failure_keeps_published_original_and_blocks(self):
        plan = self.plan()
        with patch.object(self.manager, 'write_json', side_effect=OSError('simulated manifest failure')):
            with self.assertRaises(OSError):
                self.manager.apply(plan['plan_path'], execute=True)
        self.assertTrue((self.root / plan['plan']['target_relative_path']).exists())
        self.assertIn('UNREGISTERED_ORIGINAL', self.codes())
        with self.assertRaisesRegex(sm.SourceError, 'INTEGRITY_ERRORS'):
            self.manager.update_baseline(execute=True)

    def test_plan_atomic_failure(self):
        with patch.object(self.manager, '_publish', side_effect=OSError('simulated failure')):
            with self.assertRaises(OSError):
                self.plan()
        self.assertEqual(list((self.root / sm.PLANS).iterdir()), [])

    def test_manifest_schema_and_timezone(self):
        _, record = self.imported()
        self.assertEqual(set(record), sm.MANIFEST_FIELDS)
        self.assertTrue(sm.iso_time(record['imported_at']))
        self.assertEqual(record['parser_status'], 'not_started')
        self.assertIsNone(record['page_count'])
        self.assertFalse(Path(record['stored_relative_path']).is_absolute())
        record['stored_relative_path'] = 'C:/outside.pdf'
        with self.assertRaisesRegex(sm.SourceError, 'MANIFEST_PATH_INVALID'):
            self.manager.validate_manifest(record, record['source_id'] + '.json')

    def test_manifest_duplicate_json_key(self):
        path = self.root / sm.MANIFESTS / 'invalid.json'
        path.write_text('{"schema_version": 1, "schema_version": 2}', encoding='utf-8')
        self.assertIn('JSON_DUPLICATE_KEY', self.codes())

    def test_original_modified_same_size_restored_timestamp(self):
        _, record = self.imported()
        path = self.root / record['stored_relative_path']
        before = path.stat()
        content = path.read_bytes()
        path.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertIn('HASH_MISMATCH', self.codes())

    def test_original_missing(self):
        _, record = self.imported()
        (self.root / record['stored_relative_path']).unlink()  # generated original only
        self.assertIn('ORIGINAL_MISSING_OR_UNREADABLE', self.codes())

    def test_unregistered_original(self):
        (self.root / 'sources-original/math1/unregistered.pdf').write_bytes(b'%PDF-1.7\nfixture')
        self.assertIn('UNREGISTERED_ORIGINAL', self.codes())

    def test_missing_manifest(self):
        _, record = self.imported()
        self.manager.update_baseline(execute=True)
        (self.root / sm.MANIFESTS / (record['source_id'] + '.json')).unlink()
        self.assertIn('UNREGISTERED_ORIGINAL', self.codes())
        self.assertIn('BASELINE_SOURCE_MISSING', self.codes())

    def test_same_hash_conflicting_manifests(self):
        _, record = self.imported()
        duplicate = dict(record)
        duplicate['source_id'] = 'src-' + record['sha256'][:13]
        duplicate['stored_relative_path'] = record['stored_relative_path'].replace(record['source_id'], duplicate['source_id'])
        dest = self.root / duplicate['stored_relative_path']
        dest.parent.mkdir(parents=True)
        dest.write_bytes((self.root / record['stored_relative_path']).read_bytes())
        (self.root / sm.MANIFESTS / (duplicate['source_id'] + '.json')).write_bytes(sm.json_bytes(duplicate))
        self.assertIn('HASH_CONFLICT', self.codes())

    def test_baseline_explicit_update_only(self):
        old = (self.root / sm.BASELINE).read_bytes()
        _, record = self.imported()
        self.assertEqual((self.root / sm.BASELINE).read_bytes(), old)
        self.assertEqual(self.manager.verify()['baseline_pending'], [record['source_id']])
        self.manager.update_baseline()
        self.assertEqual((self.root / sm.BASELINE).read_bytes(), old)
        self.manager.update_baseline(execute=True)
        self.assertEqual(self.manager.verify()['baseline_pending'], [])

    def test_baseline_rebuild_refuses_corruption(self):
        _, record = self.imported()
        self.manager.update_baseline(execute=True)
        old = (self.root / sm.BASELINE).read_bytes()
        (self.root / record['stored_relative_path']).write_bytes(b'%PDF-1.7\ncorrupt')
        with self.assertRaises(sm.SourceError):
            self.manager.update_baseline(execute=True)
        self.assertEqual((self.root / sm.BASELINE).read_bytes(), old)

    def test_baseline_anchor_tampered_manifest_refused(self):
        _, record = self.imported()
        self.manager.update_baseline(execute=True)
        path = self.root / record['stored_relative_path']
        path.write_bytes(b'%PDF-1.7\nchanged')
        record['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.root / sm.MANIFESTS / (record['source_id'] + '.json')).write_bytes(sm.json_bytes(record))
        with self.assertRaises(sm.SourceError):
            self.manager.update_baseline(execute=True)

    def test_tampered_plan_target_refused(self):
        result = self.plan()
        result['plan']['target_relative_path'] = '../escape.pdf'
        (self.root / result['plan_path']).write_bytes(sm.json_bytes(result['plan']))
        with self.assertRaisesRegex(sm.SourceError, 'PLAN_TARGET_INVALID'):
            self.manager.apply(result['plan_path'], execute=True)

    def test_windows_path_and_chinese_name(self):
        path = self.put('模拟资料.pdf')
        plan = self.plan(path.replace('/', '\\'))
        self.manager.apply(plan['plan_path'], execute=True)
        self.assertIn('模拟资料.pdf', self.manager.list_sources()[0]['stored_relative_path'])

    def test_filename_sanitization(self):
        for name in ('../bad?.pdf', 'CON.pdf', 'odd:name.docx', '文件 .pdf'):
            sanitized = sm.sanitized_filename(name)
            self.assertNotIn('..', sanitized)
            self.assertFalse(any(c in sanitized for c in '<>:"/\\|?*'))
        self.assertEqual(sm.sanitized_filename('CON.pdf'), '_CON.pdf')

    def test_cli_no_document_or_secret_echo(self):
        synthetic_key = 'sk-' + 'synthetic_test_only_' * 3
        self.put(data=('%PDF-1.7\n' + synthetic_key).encode())
        output = io.StringIO()
        with patch.object(sm, 'SourceManager', return_value=self.manager), redirect_stdout(output):
            self.assertEqual(sm.cli(['scan']), 0)
        self.assertNotIn(synthetic_key, output.getvalue())
        self.assertNotIn(str(self.root), output.getvalue())
        with patch.object(sm, 'SourceManager', side_effect=OSError(synthetic_key)), redirect_stdout(output):
            self.assertEqual(sm.cli(['verify']), 1)
        self.assertNotIn(synthetic_key, output.getvalue())

    def test_read_only_commands_write_nothing(self):
        self.imported()
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for method in (self.manager.verify, self.manager.list_sources, self.manager.scan, self.manager.status):
            method()
        after = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_existing_lock_blocks_and_preserves_lock(self):
        plan = self.plan()
        lock = self.root / 'config/.source-manager.lock'
        lock.write_bytes(b'existing lock fixture')
        with self.assertRaisesRegex(sm.SourceError, 'MANAGER_LOCKED'):
            self.manager.apply(plan['plan_path'], execute=True)
        self.assertEqual(lock.read_bytes(), b'existing lock fixture')

    def test_status_excludes_already_imported_inbox_from_pending(self):
        self.imported()
        report = self.manager.status()
        self.assertEqual(report['inbox_file_count'], 1)
        self.assertEqual(report['inbox_pending_count'], 0)
        self.assertEqual(report['pending_plans'], 0)

    def test_malformed_plan_reported_without_crashing_status(self):
        (self.root / sm.PLANS / 'invalid.json').write_bytes(b'{"sha256": []}')
        self.assertEqual(self.manager.status()['invalid_plans'], 1)

    def test_manifest_publication_no_overwrite(self):
        relative = sm.MANIFESTS + '/existing.json'
        (self.root / relative).write_bytes(b'preserve generated sentinel')
        with self.assertRaisesRegex(sm.SourceError, 'TARGET_EXISTS'):
            self.manager.write_json(relative, {})
        self.assertEqual((self.root / relative).read_bytes(), b'preserve generated sentinel')

    def test_baseline_conflict_on_relocated_original(self):
        _, record = self.imported()
        self.manager.update_baseline(execute=True)
        old_path = self.root / record['stored_relative_path']
        new_path = old_path.with_name('renamed.pdf')
        old_path.rename(new_path)  # Own generated fixture; simulate forbidden external relocation.
        record['original_filename'] = 'renamed.pdf'
        record['stored_relative_path'] = new_path.relative_to(self.root).as_posix()
        (self.root / sm.MANIFESTS / (record['source_id'] + '.json')).write_bytes(sm.json_bytes(record))
        self.assertIn('BASELINE_CONFLICT', self.codes())
        with self.assertRaisesRegex(sm.SourceError, 'INTEGRITY_ERRORS'):
            self.manager.update_baseline(execute=True)

    def test_list_does_not_read_original_bytes(self):
        self.imported()
        original_reader = self.manager.reader
        def metadata_only(relative):
            self.assertTrue(relative.startswith(sm.MANIFESTS + '/'))
            return original_reader(relative)
        with patch.object(self.manager, 'reader', side_effect=metadata_only):
            self.assertEqual(len(self.manager.list_sources()), 1)

    def test_all_command_help(self):
        for command in ('scan', 'plan', 'apply', 'verify', 'list', 'status', 'baseline-update'):
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                sm.cli([command, '--help'])
            self.assertEqual(result.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
