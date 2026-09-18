"""Phase 2C tests use synthetic data and project-local scratch only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fitz
import yaml

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location('parsing_architecture_test', ROOT / 'scripts/parsing_architecture.py')
arch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(arch)


class ArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = arch.validate_profiles(arch.load_yaml(ROOT / arch.PROFILES_FILE))
        cls.limits = arch.validate_limits(arch.load_yaml(ROOT / arch.LIMITS_FILE), ROOT)
        cls.evaluation = json.loads(
            (ROOT / 'tests/fixtures/parsing-evaluation/evaluation-manifest.json').read_text(encoding='utf-8'))

    def test_all_evaluation_routes(self):
        for case in self.evaluation['cases']:
            with self.subTest(case=case['case_id']):
                _, route, _ = arch.score_and_route(
                    case['metrics'], self.profiles['profiles'][case['profile']])
                self.assertEqual(route, case['expected_route'])

    def test_representative_cs408_page_2_routes_to_enhanced(self):
        meta = self.evaluation['representative_cs408_metadata_only']
        metrics = dict(self.evaluation['cases'][2]['metrics'])
        metrics['replacement_char_count'] = meta['page_2_replacement_char_count']
        metrics['replacement_char_rate'] = metrics['replacement_char_count'] / metrics['character_count']
        _, route, reasons = arch.score_and_route(metrics, self.profiles['profiles']['cs408_symbol_dense'])
        self.assertEqual(route, 'enhanced_parse_queued')
        self.assertIn('replacement_char_count', reasons)
        self.assertFalse(meta['contains_pdf_text'])

    def test_metrics_not_only_character_count(self):
        clean = arch.metrics_from_text('普通合成文本 ' * 50)
        degraded = arch.metrics_from_text(('普通合成文本 ' * 50) + '\ufffd')
        profile = self.profiles['profiles']['cs408_symbol_dense']
        self.assertEqual(arch.score_and_route(clean, profile)[1], 'basic_accepted_candidate')
        self.assertEqual(arch.score_and_route(degraded, profile)[1], 'enhanced_parse_queued')

    def test_metric_schema_and_types_rejected(self):
        metrics = dict(self.evaluation['cases'][0]['metrics'])
        del metrics['replacement_char_count']
        with self.assertRaisesRegex(arch.ArchitectureError, 'QUALITY_METRICS_INVALID'):
            arch.score_and_route(metrics, self.profiles['profiles']['cs408_general'])
        metrics = dict(self.evaluation['cases'][0]['metrics'])
        metrics['image_count'] = -1
        with self.assertRaisesRegex(arch.ArchitectureError, 'QUALITY_METRICS_INVALID'):
            arch.score_and_route(metrics, self.profiles['profiles']['cs408_general'])

    def test_legal_state_history_is_traceable(self):
        machine = arch.PageStateMachine('src-' + 'a' * 12, 2)
        for state, reason in (('basic_parsed', 'basic complete'),
                              ('quality_scored', 'quality complete'),
                              ('enhanced_queued', 'encoding warning'),
                              ('enhanced_candidate_ready', 'candidate complete'),
                              ('review_required', 'human review required'),
                              ('accepted_for_retrieval', 'explicit acceptance')):
            event = machine.transition(state, 'basic_pymupdf', reason,
                                       '2026-09-16T12:00:00+00:00')
            self.assertEqual(event['source_id'], machine.source_id)
            self.assertEqual(event['page_number'], 2)
        self.assertEqual(len(machine.history), 6)

    def test_source_state_and_illegal_transitions(self):
        source = arch.SourceStateMachine('src-' + 'b' * 12)
        event = source.transition('basic_parsed', 'basic_pymupdf', 'source basic complete')
        self.assertIsNone(event['page_number'])
        with self.assertRaisesRegex(arch.ArchitectureError, 'STATE_TRANSITION_INVALID'):
            source.transition('accepted_for_retrieval', 'basic_pymupdf', 'skip review')
        with self.assertRaisesRegex(arch.ArchitectureError, 'STATE_TRANSITION_INVALID'):
            arch.PageStateMachine('src-' + 'a' * 12, 1).transition(
                'enhanced_candidate_ready', 'basic_pymupdf', 'illegal skip')

    def test_single_page_retry_and_limit(self):
        machine = arch.PageStateMachine('src-' + 'c' * 12, 3, state='failed')
        task = machine.retry_task('enhanced_mineru_pipeline', 'generated test retry', 0, 2)
        self.assertEqual(task['scope'], 'single_page_only')
        self.assertEqual(task['page_number'], 3)
        with self.assertRaisesRegex(arch.ArchitectureError, 'RETRY_LIMIT_REACHED'):
            machine.retry_task('enhanced_mineru_pipeline', 'limit', 2, 2)

    def test_checkpoint_jobs_skip_completed_and_non_enhanced(self):
        decisions = [
            {'source_id': 'src-' + 'd' * 12, 'page_number': 1,
             'route': 'enhanced_parse_queued', 'preferred_enhanced_parser': 'enhanced_mineru_pipeline'},
            {'source_id': 'src-' + 'd' * 12, 'page_number': 2,
             'route': 'review_required', 'preferred_enhanced_parser': None},
            {'source_id': 'src-' + 'd' * 12, 'page_number': 3,
             'route': 'enhanced_parse_queued', 'preferred_enhanced_parser': 'enhanced_mineru_pipeline'},
        ]
        jobs = arch.build_page_jobs(decisions, {1}, self.limits)
        self.assertEqual([job['page_number'] for job in jobs], [3])
        self.assertTrue(jobs[0]['preserve_basic_output'])

    def test_resource_limits_are_local_and_low_concurrency(self):
        self.assertEqual(self.limits['limits']['max_concurrent_jobs'], 1)
        self.assertEqual(self.limits['execution']['retry_scope'], 'single_page_only')
        for key in ('model_cache_relative_path', 'queue_relative_path', 'checkpoint_relative_path'):
            self.assertTrue(arch.safe_relative(self.limits[key]))
        changed = json.loads(json.dumps(self.limits))
        changed['model_cache_relative_path'] = '../outside'
        with self.assertRaisesRegex(arch.ArchitectureError, 'LIMIT_PATH_INVALID'):
            arch.validate_limits(changed, ROOT)

    def test_profiles_route_enhanced_pages_to_isolated_paddle_candidates(self):
        for profile in self.profiles['profiles'].values():
            self.assertEqual(profile['preferred_enhanced_parser'], 'paddleocr_vl_local')
        self.assertEqual(
            arch.enhanced_output_path('src-aaaaaaaaaaaa', 7, 'paddleocr_vl_local'),
            'vault/90-Parsed-Sources/src-aaaaaaaaaaaa/enhanced/paddleocr-vl/page-0007')

    def test_profile_config_rejects_network_cloud_and_duplicate_key(self):
        changed = json.loads(json.dumps(self.profiles))
        changed['parser_catalog']['optional_mathpix_formula_crop']['network_allowed'] = True
        with self.assertRaisesRegex(arch.ArchitectureError, 'NETWORK_PARSER_MUST_BE_DISABLED'):
            arch.validate_profiles(changed)
        runtime = ROOT / 'tests/.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='arch-yaml-', dir=runtime) as name:
            path = Path(name) / 'duplicate.yaml'
            path.write_text('schema_version: 1\nschema_version: 2\n', encoding='utf-8')
            with self.assertRaisesRegex(arch.ArchitectureError, 'CONFIG_DUPLICATE_KEY'):
                arch.load_yaml(path)

    def test_parser_contract_and_inert_enhanced_adapters(self):
        result = arch.PageParseResult(
            'basic_pymupdf', '1.0', 'local_basic_text', 1, 'synthetic', [], [], [],
            {'character_count': 9}, 'review_required',
            'vault/90-Parsed-Sources/src-aaaaaaaaaaaa/basic/pages/page-0001.json')
        self.assertEqual(result.validate()['page_number'], 1)
        adapter = arch.UnavailableAdapter('enhanced_mineru_pipeline', 'local_formula_layout_enhanced')
        with self.assertRaisesRegex(arch.ArchitectureError, 'PARSER_NOT_INSTALLED'):
            adapter.parse_page('src-' + 'a' * 12, 1, 'sources-original/x.pdf',
                               'vault/90-Parsed-Sources/src-aaaaaaaaaaaa/enhanced/mineru/page.json')

    def test_basic_adapter_reads_one_synthetic_page_without_writes(self):
        runtime = ROOT / 'tests/.runtime'; runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='arch-basic-', dir=runtime) as name:
            root = Path(name)
            source = root / 'sources-original/math1/calculus/src-aaaaaaaaaaaa/synthetic.pdf'
            source.parent.mkdir(parents=True)
            document = fitz.open(); page = document.new_page(); page.insert_text((72, 72), 'x1 = 2 synthetic')
            source.write_bytes(document.tobytes()); document.close()
            before = source.read_bytes()
            adapter = arch.BasicPyMuPDFAdapter(root)
            result = adapter.parse_page('src-' + 'a' * 12, 1,
                source.relative_to(root).as_posix(),
                'vault/90-Parsed-Sources/src-aaaaaaaaaaaa/basic/pages/page-0001.json')
            self.assertIn('synthetic', result.text)
            self.assertEqual(source.read_bytes(), before)
            self.assertFalse((root / 'vault').exists())
            self.assertTrue(result.validate()['extraction_metrics']['subscript_or_superscript_risk'])

    def test_basic_adapter_rejects_path_escape_and_original_output(self):
        adapter = arch.BasicPyMuPDFAdapter(ROOT)
        for output in ('../outside', 'sources-original/math1/result.json',
                       'vault/90-Parsed-Sources/src-bbbbbbbbbbbb/basic/page.json'):
            with self.subTest(output=output), self.assertRaisesRegex(
                    arch.ArchitectureError, 'OUTPUT_PATH_INVALID'):
                adapter.parse_page('src-' + 'a' * 12, 1,
                    'sources-original/math1/calculus/src-aaaaaaaaaaaa/a.pdf', output)

    def test_existing_page_text_extractor_preserves_only_fence(self):
        markdown = '---\nsource_page: 1\n---\n```text\nraw $ x1\n```\nmetadata 2022'
        self.assertEqual(arch.extracted_text_from_page(markdown), 'raw $ x1\n')

    def test_evaluation_report_has_all_required_dimensions(self):
        text = (ROOT / 'tests/fixtures/parsing-evaluation/comparison-report-template.md').read_text(encoding='utf-8')
        for label in ('替换字符数量', '下标恢复率', '公式 LaTeX 可渲染率', '中文正文保真率',
                      '代码标识符保留率', '表格结构质量', '页面阅读顺序', '每页耗时',
                      '峰值内存', '峰值显存', '磁盘增量', '失败率'):
            self.assertIn(label, text)
        self.assertIn('不能单独决定解析器质量', text)

    def test_planner_reads_existing_basic_output_and_saves_without_overwrite(self):
        runtime = ROOT / 'tests/.runtime'; runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='arch-plan-', dir=runtime) as name:
            root = Path(name)
            for directory in ('config/source-manifests', 'vault/90-Parsed-Sources',
                              'review-queue/parsing-routing',
                              'sources-original/408/computer-organization'):
                (root / directory).mkdir(parents=True)
            profiles = yaml.safe_load((ROOT / arch.PROFILES_FILE).read_text(encoding='utf-8'))
            limits = yaml.safe_load((ROOT / arch.LIMITS_FILE).read_text(encoding='utf-8'))
            limits['project_root_constraint'] = root.as_posix()
            (root / arch.PROFILES_FILE).write_text(yaml.safe_dump(profiles, allow_unicode=True), encoding='utf-8')
            (root / arch.LIMITS_FILE).write_text(yaml.safe_dump(limits, allow_unicode=True), encoding='utf-8')
            pdf_data = b'%PDF-1.7\nsynthetic architecture fixture\n%%EOF'
            digest = hashlib.sha256(pdf_data).hexdigest()
            sid = 'src-' + digest[:12]
            source_rel = f'sources-original/408/computer-organization/{sid}/synthetic.pdf'
            output_rel = f'vault/90-Parsed-Sources/{sid}'
            source = root / source_rel; source.parent.mkdir(parents=True); source.write_bytes(pdf_data)
            manifest = {
                'schema_version': 1, 'source_id': sid, 'sha256': digest,
                'original_filename': 'synthetic.pdf', 'stored_relative_path': source_rel,
                'file_type': 'pdf', 'size_bytes': len(pdf_data), 'course': '408',
                'subject': 'computer-organization', 'source_type': 'exercise',
                'classification_status': 'confirmed', 'import_status': 'imported',
                'imported_at': '2026-09-16T12:00:00+00:00', 'parser_status': 'parsed',
                'parser_name': 'pymupdf-basic-text', 'parser_version': '1.26.7',
                'page_count': 3, 'parsed_at': '2026-09-16T12:01:00+00:00',
                'parsed_output_relative_path': output_rel,
                'parse_review_status': 'review_required', 'notes': ''}
            (root / f'config/source-manifests/{sid}.json').write_text(json.dumps(manifest), encoding='utf-8')
            baseline = {'schema_version': 2, 'algorithm': 'sha256', 'sources': {
                sid: {'sha256': digest, 'stored_relative_path': source_rel,
                      'size_bytes': len(pdf_data)}}}
            (root / 'config/sources-original.baseline.json').write_text(json.dumps(baseline), encoding='utf-8')
            output = root / output_rel; (output / 'pages').mkdir(parents=True)
            texts = ('formula candidate', 'broken \ufffd symbol', 'plain synthetic page')
            entries = []
            for number, text in enumerate(texts, 1):
                page = output / f'pages/page-{number:04d}.md'
                page.write_text(f'```text\n{text}\n```\n', encoding='utf-8')
                entries.append({'page_number': number, 'relative_path': f'pages/page-{number:04d}.md',
                    'parse_status': 'extracted', 'character_count': len(text) + 1,
                    'image_count': 0, 'needs_formula_review': number == 1})
            report = {'source_id': sid, 'source_sha256': digest, 'parser_name': 'pymupdf-basic-text',
                'parser_version': '1.26.7', 'parsed_at': '2026-09-16T12:01:00+00:00',
                'declared_page_count': 3, 'output_page_count': 3,
                'review_status': 'review_required', 'derived': True, 'pages': entries}
            (output / 'parse-report.json').write_text(json.dumps(report), encoding='utf-8')
            planner = arch.RoutingPlanner(root)
            before = {p.relative_to(root).as_posix(): p.read_bytes() for p in output.rglob('*') if p.is_file()}
            plan = planner.plan_existing(sid, 'cs408_symbol_dense')
            self.assertEqual(plan['decisions'][1]['route'], 'enhanced_parse_queued')
            self.assertTrue(plan['does_not_reparse'])
            self.assertEqual(before, {p.relative_to(root).as_posix(): p.read_bytes() for p in output.rglob('*') if p.is_file()})
            report_path = output / 'parse-report.json'
            report['pages'][0]['relative_path'] = '../../outside.md'
            report_path.write_text(json.dumps(report), encoding='utf-8')
            with self.assertRaisesRegex(arch.ArchitectureError, 'BASIC_PAGE_PATH_INVALID'):
                planner.plan_existing(sid, 'cs408_symbol_dense')
            report['pages'][0]['relative_path'] = 'pages/page-0001.md'
            report_path.write_text(json.dumps(report), encoding='utf-8')
            path = planner.save_plan(plan)
            self.assertEqual(path, f'review-queue/parsing-routing/{sid}.json')
            self.assertTrue(planner.verify_plan(sid)['ok'])
            with self.assertRaisesRegex(arch.SourceError, 'TARGET_EXISTS'):
                planner.save_plan(plan)

    def test_routing_plan_rejects_path_and_state_tampering(self):
        sid = 'src-' + 'a' * 12
        case = self.evaluation['cases'][2]
        score, route, reasons = arch.score_and_route(
            case['metrics'], self.profiles['profiles'][case['profile']])
        decision = {
            'source_id': sid, 'page_number': 1, 'source_page': 1,
            'profile': case['profile'], 'basic_parser_id': 'basic_pymupdf',
            'basic_parser_version': '1.0', 'quality_score': score,
            'metrics': case['metrics'], 'route': route, 'reasons': reasons,
            'current_state': 'encoding_degraded', 'planned_state': 'enhanced_queued',
            'preferred_enhanced_parser': 'enhanced_mineru_pipeline',
            'review_status': 'review_required',
            'planned_transition': {'from': 'encoding_degraded', 'to': 'enhanced_queued',
                'timestamp': '2026-09-16T12:00:00+00:00', 'parser_id': 'basic_pymupdf',
                'reason': 'encoding', 'source_id': sid, 'page_number': 1},
            'basic_output_relative_path': f'vault/90-Parsed-Sources/{sid}/pages/page-0001.md',
            'enhanced_output_relative_path': f'vault/90-Parsed-Sources/{sid}/enhanced/mineru/page-0001.json'}
        plan = {'schema_version': 1, 'plan_type': 'quality_routing_only',
            'source_id': sid, 'source_sha256': 'a' * 64, 'profile': case['profile'],
            'created_at': '2026-09-16T12:00:00+00:00',
            'basic_output_layout': 'phase2b_legacy_flat_read_only',
            'future_output_root': f'vault/90-Parsed-Sources/{sid}',
            'does_not_reparse': True, 'does_not_modify_existing_output': True,
            'automatic_knowledge_note_entry': False, 'source_state': 'review_required',
            'source_transition': {'from': 'quality_scored', 'to': 'review_required',
                'timestamp': '2026-09-16T12:00:00+00:00', 'parser_id': 'basic_pymupdf',
                'reason': 'page_quality_routing_completed', 'source_id': sid,
                'page_number': None},
            'page_count': 1, 'decisions': [decision]}
        self.assertEqual(arch.validate_routing_plan(plan), plan)
        decision['enhanced_output_relative_path'] = '../outside.json'
        with self.assertRaisesRegex(arch.ArchitectureError, 'ROUTING_PLAN_INVALID'):
            arch.validate_routing_plan(plan)


if __name__ == '__main__':
    unittest.main()
