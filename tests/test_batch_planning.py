"""Phase 2D-0 tests use metadata-only synthetic fixtures inside tests/.runtime."""
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location(
    'parsing_architecture_batch_test', ROOT / 'scripts/parsing_architecture.py')
arch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(arch)


class BatchPlanningTests(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / 'tests/.runtime'
        runtime.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='batch-plan-', dir=runtime)
        self.root = Path(self.temp.name)
        for directory in ('config/source-manifests', 'review-queue/parsing-routing',
                          'review-queue/parsing-jobs', 'review-queue/parsing-checkpoints',
                          'sources-original/408', 'vault/90-Parsed-Sources'):
            (self.root / directory).mkdir(parents=True)
        profiles = yaml.safe_load((ROOT / arch.PROFILES_FILE).read_text(encoding='utf-8'))
        limits = yaml.safe_load((ROOT / arch.LIMITS_FILE).read_text(encoding='utf-8'))
        limits['project_root_constraint'] = self.root.as_posix()
        (self.root / arch.PROFILES_FILE).write_text(
            yaml.safe_dump(profiles, allow_unicode=True), encoding='utf-8')
        (self.root / arch.LIMITS_FILE).write_text(
            yaml.safe_dump(limits, allow_unicode=True), encoding='utf-8')
        self.planner = arch.BatchPlanner(self.root)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def record(source_id='src-' + 'a' * 12, parsed=True, file_type='pdf',
               size=1024, course='408', subject='computer-organization',
               source_type='exercise'):
        return {
            'source_id': source_id, 'course': course, 'subject': subject,
            'source_type': source_type, 'file_type': file_type, 'size_bytes': size,
            'parser_status': 'parsed' if parsed else 'not_started',
            'page_count': 4 if parsed else None,
        }

    @staticmethod
    def routing(source_id='src-' + 'a' * 12, routes=None):
        routes = routes or ['enhanced_parse_queued', 'enhanced_parse_queued',
                            'enhanced_parse_queued', 'basic_accepted_candidate']
        timestamp = '2026-09-17T00:00:00+00:00'
        decisions = []
        for number, route in enumerate(routes, 1):
            current = 'quality_scored'
            target = {'enhanced_parse_queued': 'enhanced_queued',
                      'basic_accepted_candidate': 'review_required',
                      'review_required': 'review_required',
                      'manual_or_optional_cloud_review': 'blocked'}[route]
            metrics = arch.metrics_from_text('synthetic page')
            decisions.append({
                'source_id': source_id, 'page_number': number, 'source_page': number,
                'profile': 'cs408_symbol_dense', 'basic_parser_id': 'basic_pymupdf',
                'basic_parser_version': '1.26.7', 'quality_score': 50,
                'metrics': metrics, 'route': route, 'reasons': ['synthetic_reason'],
                'current_state': current, 'planned_state': target,
                'preferred_enhanced_parser': ('enhanced_mineru_pipeline'
                                              if route == 'enhanced_parse_queued' else None),
                'review_status': 'review_required',
                'planned_transition': {'from': current, 'to': target,
                    'timestamp': timestamp, 'parser_id': 'basic_pymupdf',
                    'reason': 'synthetic_reason', 'source_id': source_id,
                    'page_number': number},
                'basic_output_relative_path':
                    f'vault/90-Parsed-Sources/{source_id}/pages/page-{number:04d}.md',
                'enhanced_output_relative_path':
                    (f'vault/90-Parsed-Sources/{source_id}/enhanced/mineru/page-{number:04d}.json'
                     if route == 'enhanced_parse_queued' else None),
            })
        return {
            'schema_version': 1, 'plan_type': 'quality_routing_only',
            'source_id': source_id, 'source_sha256': 'a' * 64,
            'profile': 'cs408_symbol_dense', 'created_at': timestamp,
            'basic_output_layout': 'phase2b_legacy_flat_read_only',
            'future_output_root': f'vault/90-Parsed-Sources/{source_id}',
            'does_not_reparse': True, 'does_not_modify_existing_output': True,
            'automatic_knowledge_note_entry': False,
            'source_state': 'review_required',
            'source_transition': {'from': 'quality_scored', 'to': 'review_required',
                'timestamp': timestamp, 'parser_id': 'basic_pymupdf',
                'reason': 'page_quality_routing_completed', 'source_id': source_id,
                'page_number': None},
            'page_count': len(decisions), 'decisions': decisions,
        }

    def install_routing(self, plan):
        arch.validate_routing_plan(plan)
        path = self.root / arch.ROUTING_QUEUE / f'{plan["source_id"]}.json'
        path.write_text(json.dumps(plan), encoding='utf-8')

    def patched_records(self, records):
        verify = patch.object(self.planner.manager, 'verify', return_value={'ok': True})
        manifests = patch.object(self.planner.manager, 'manifests', return_value=(records, []))
        return verify, manifests

    def test_current_shape_routes_three_enhanced_and_one_basic_without_writes(self):
        record = self.record()
        self.install_routing(self.routing())
        before = list((self.root / 'review-queue/parsing-jobs').iterdir())
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            plan = self.planner.batch_plan(source_ids=[record['source_id']])
        self.assertEqual(len(plan['categories']['enhanced']), 3)
        self.assertEqual(len(plan['categories']['basic']), 1)
        self.assertFalse(plan['categories']['basic'][0]['requires_basic_parse'])
        self.assertTrue(plan['dry_run'])
        self.assertFalse(plan['would_parse'])
        self.assertEqual(before, list((self.root / 'review-queue/parsing-jobs').iterdir()))

    def test_unfiltered_batch_requires_explicit_whole_library_confirmation(self):
        record = self.record()
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests, self.assertRaisesRegex(
                arch.ArchitectureError, 'BATCH_SCOPE_CONFIRMATION_REQUIRED'):
            self.planner.batch_plan()
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            plan = self.planner.batch_plan(confirm_all_sources=True)
        self.assertTrue(plan['full_library_scope_confirmed'])

    def test_enhanced_batches_split_at_25_and_never_mix_heavy_work(self):
        record = self.record()
        routes = ['enhanced_parse_queued'] * 30
        record['page_count'] = 30
        self.install_routing(self.routing(routes=routes))
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            plan = self.planner.batch_plan(source_ids=[record['source_id']])
        self.assertEqual([len(batch['tasks']) for batch in plan['batches']], [25, 5])
        self.assertTrue(all(batch['heavy'] for batch in plan['batches']))
        self.assertTrue(all(batch['max_concurrent_jobs'] == 1 for batch in plan['batches']))

    def test_unparsed_pdf_is_basic_task_and_office_is_unsupported(self):
        pdf = self.record(parsed=False)
        office = self.record('src-' + 'b' * 12, parsed=False, file_type='docx')
        verify, manifests = self.patched_records({pdf['source_id']: pdf,
                                                  office['source_id']: office})
        with verify, manifests:
            plan = self.planner.batch_plan(course='408')
        self.assertEqual(len(plan['categories']['basic']), 1)
        self.assertTrue(plan['categories']['basic'][0]['requires_basic_parse'])
        self.assertEqual(len(plan['categories']['unsupported']), 1)
        self.assertEqual(plan['resource_estimate']['basic_parse_task_count'], 1)

    def test_file_over_limit_is_deferred(self):
        record = self.record(parsed=False,
                             size=self.planner.limits['limits']['max_single_file_size_bytes'] + 1)
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            plan = self.planner.batch_plan(source_ids=[record['source_id']])
        self.assertEqual(len(plan['categories']['resource_deferred']), 1)
        self.assertEqual(plan['resource_estimate']['resource_deferred_count'], 1)

    def test_filters_and_explicit_compatible_profile(self):
        record = self.record(parsed=False)
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            result = self.planner.source_status(
                course='408', subject='computer-organization', source_type='exercise',
                profile='cs408_symbol_dense')
        self.assertEqual(result['source_count'], 1)
        self.assertEqual(result['sources'][0]['parsing_profile'], 'cs408_symbol_dense')
        with self.assertRaisesRegex(arch.ArchitectureError, 'FILTER_INVALID'):
            self.planner.source_status(course='invalid')

    def test_resource_estimate_uses_current_hardware_budget_and_concurrency_one(self):
        record = self.record()
        self.install_routing(self.routing())
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            estimate = self.planner.batch_plan(source_ids=[record['source_id']])['resource_estimate']
        self.assertEqual(estimate['known_page_count'], 4)
        self.assertEqual(estimate['enhanced_parse_task_count'], 3)
        self.assertEqual(estimate['max_concurrent_jobs'], 1)
        self.assertFalse(estimate['exceeds_16gb_physical_memory'])
        self.assertFalse(estimate['exceeds_8gb_physical_vram'])

    def test_saved_batch_is_metadata_only_and_duplicate_refuses_overwrite(self):
        record = self.record(parsed=False)
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            plan = self.planner.batch_plan(source_ids=[record['source_id']])
        relative = self.planner.save_batch_plan(plan)
        saved = json.loads((self.root / relative).read_text(encoding='utf-8'))
        self.assertFalse(saved['would_parse'])
        self.assertFalse(saved['would_modify_originals'])
        with self.assertRaisesRegex(arch.SourceError, 'TARGET_EXISTS'):
            self.planner.save_batch_plan(plan)

    def test_existing_queue_plan_prevents_duplicate_page_scheduling(self):
        record = self.record()
        self.install_routing(self.routing())
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            first = self.planner.batch_plan(source_ids=[record['source_id']])
        self.planner.save_batch_plan(first)
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            second = self.planner.batch_plan(source_ids=[record['source_id']])
        self.assertEqual(len(second['categories']['enhanced']), 0)
        self.assertEqual(len(second['categories']['already_queued']), 3)
        self.assertEqual(second['resource_estimate']['already_queued_count'], 3)

    def test_queue_status_counts_only_metadata_documents(self):
        queue = self.root / arch.JOB_QUEUE
        (queue / 'batch.json').write_text(json.dumps({
            'document_type': 'batch_plan', 'status': 'planned'}), encoding='utf-8')
        (queue / 'retry.json').write_text(json.dumps({
            'document_type': 'single_page_retry', 'status': 'planned'}), encoding='utf-8')
        status = self.planner.queue_status()
        self.assertEqual(status['queue_documents'], 2)
        self.assertEqual(status['by_type']['single_page_retry'], 1)
        self.assertEqual(status['max_concurrent_jobs'], 1)

    def test_single_page_retry_requires_failed_checkpoint_and_obeys_limit(self):
        record = self.record()
        self.install_routing(self.routing())
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests, self.assertRaisesRegex(
                arch.ArchitectureError, 'RETRY_CHECKPOINT_REQUIRED'):
            self.planner.retry_page(record['source_id'], 2)
        checkpoint = {'schema_version': 1, 'source_id': record['source_id'],
            'page_number': 2, 'status': 'failed', 'retry_count': 0,
            'parser_id': 'enhanced_mineru_pipeline', 'error_code': 'PARSER_FAILED',
            'updated_at': '2026-09-17T00:00:00+00:00'}
        path = self.root / arch.CHECKPOINT_QUEUE / f'{record["source_id"]}-page-0002.json'
        path.write_text(json.dumps(checkpoint), encoding='utf-8')
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            task = self.planner.retry_page(record['source_id'], 2)
        self.assertEqual(task['page_number'], 2)
        self.assertEqual(task['scope'], 'single_page_only')
        self.assertFalse(task['would_parse'])
        checkpoint['retry_count'] = self.planner.limits['limits']['max_retry_count_per_page']
        path.write_text(json.dumps(checkpoint), encoding='utf-8')
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests, self.assertRaisesRegex(
                arch.ArchitectureError, 'RETRY_LIMIT_REACHED'):
            self.planner.retry_page(record['source_id'], 2)

    def test_resume_check_reports_completed_failed_and_pending_pages(self):
        sid = 'src-' + 'a' * 12
        folder = self.root / arch.CHECKPOINT_QUEUE
        for number, status in enumerate(('completed', 'failed', 'queued'), 1):
            (folder / f'{sid}-page-{number:04d}.json').write_text(json.dumps({
                'source_id': sid, 'page_number': number, 'status': status}), encoding='utf-8')
        result = self.planner.resume_check(sid)
        self.assertEqual(result['checkpoint_counts'],
                         {'completed': 1, 'failed': 1, 'pending': 1})
        self.assertFalse(result['whole_library_rerun_allowed'])

    def test_source_status_excludes_unconfirmed_inbox(self):
        record = self.record()
        (self.root / 'import-inbox').mkdir()
        (self.root / 'import-inbox/unconfirmed.pdf').write_bytes(b'%PDF synthetic')
        verify, manifests = self.patched_records({record['source_id']: record})
        with verify, manifests:
            result = self.planner.source_status(source_ids=[record['source_id']])
        self.assertEqual(result['source_count'], 1)
        self.assertTrue(result['unconfirmed_inbox_excluded'])

    def test_all_phase2d0_commands_have_help(self):
        for command in ('source-status', 'batch-plan', 'queue-status',
                        'estimate-resources', 'retry-page', 'resume-check'):
            with self.subTest(command=command), redirect_stdout(io.StringIO()), \
                    self.assertRaises(SystemExit) as raised:
                arch.cli([command, '--help'])
            self.assertEqual(raised.exception.code, 0)


if __name__ == '__main__':
    unittest.main()
