"""Automatic local page parsing with PaddleOCR-VL and exception-only review."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
import uuid

try:
    import fitz
except ImportError:
    fitz = None

try:
    from source_manager import SourceManager, SID, json_bytes
except ModuleNotFoundError:
    spec = importlib.util.spec_from_file_location(
        'source_manager_for_auto_parse', Path(__file__).absolute().parent / 'source_manager.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    SourceManager, SID, json_bytes = module.SourceManager, module.SID, module.json_bytes

try:
    from pdf_parser import secret_risks
except ModuleNotFoundError:
    spec = importlib.util.spec_from_file_location(
        'pdf_parser_for_auto_parse', Path(__file__).absolute().parent / 'pdf_parser.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    secret_risks = module.secret_risks

PROJECT_ROOT = Path(__file__).absolute().parent.parent
CONFIG = 'config/auto-parsing.example.json'
ROUTING = 'review-queue/parsing-routing'
OUTPUT = 'vault/90-Parsed-Sources'
QUARANTINE = 'review-queue/candidate-quarantine'


class AutoParseError(Exception):
    pass


def fail(code):
    raise AutoParseError(code)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(value, prefix=None):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ('', '.', '..') for part in path.parts):
        return False
    return prefix is None or value == prefix or value.startswith(prefix.rstrip('/') + '/')


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('xb') as stream:
        stream.write(json_bytes(value)); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def parse_pages(value, maximum):
    pages = set()
    for part in value.split(','):
        part = part.strip()
        match = re.fullmatch(r'(\d+)(?:-(\d+))?', part)
        if not match:
            fail('PAGE_RANGE_INVALID')
        start = int(match.group(1)); end = int(match.group(2) or start)
        if start < 1 or end < start or end > maximum:
            fail('PAGE_RANGE_INVALID')
        pages.update(range(start, end + 1))
    return sorted(pages)


def basic_text(path):
    if not path.is_file():
        return ''
    content = path.read_text('utf-8')
    match = re.search(r'(?ms)^## 提取文本\s*\n\s*```text\s*\n(.*?)\n```', content)
    return match.group(1).strip() if match else ''


def question_numbers(text):
    return {int(item) for item in re.findall(r'(?m)^\s*(\d{1,3})[、.]', text)}


def balanced_math(markdown):
    if markdown.count('$') % 2:
        return False
    for segment in re.findall(r'\${1,2}(.*?)\${1,2}', markdown, re.S):
        depth = 0
        for index, char in enumerate(segment):
            if index and segment[index - 1] == '\\':
                continue
            if char == '{': depth += 1
            elif char == '}':
                depth -= 1
                if depth < 0: return False
        if depth:
            return False
    return True


def formula_integrity_issues(markdown):
    issues = []
    pattern = re.compile(r'(?s)(?<!\\)(\$\$|\$)(.*?)(?<!\\)\1')
    for _delimiter, raw in pattern.findall(markdown):
        formula = raw.strip()
        # A trailing equals sign is valid for fill-in questions; a trailing + or -
        # inside a closed math span is a strong truncation signal.
        if re.search(r'(?:[+\-]|\\(?:times|div))\s*$', formula):
            issues.append('FORMULA_DANGLING_OPERATOR')
        for opening, closing in (('(', ')'), ('[', ']')):
            if formula.count(opening) != formula.count(closing):
                issues.append('FORMULA_GROUP_DELIMITER_UNBALANCED')
                break
        if re.search(r'^\s*f(?:\\left)?\(.*\\mid\s*=', formula, re.S):
            issues.append('FORMULA_ABSOLUTE_VALUE_SUSPECT')
    return sorted(set(issues))


class AutoParser:
    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root).absolute()
        self.manager = SourceManager(self.root)
        self.config = self.manager.load_json(CONFIG)
        self._validate_config()

    def _validate_config(self):
        required = {'schema_version', 'parser_id', 'parser_version', 'pipeline_version',
                    'environment_relative_path', 'worker_relative_path',
                    'model_cache_relative_path', 'layout_model_relative_path',
                    'vl_model_relative_path', 'device', 'network_policy',
                    'max_pages_per_batch', 'concurrency', 'sample_review_percent',
                    'critical_model_files', 'quality_thresholds'}
        value = self.config
        if (set(value) != required or value['schema_version'] != 1
                or value['parser_id'] != 'paddleocr_vl_local'
                or value['network_policy'] != 'local_models_and_socket_blocking'
                or value['concurrency'] != 1 or value['max_pages_per_batch'] > 25
                or not 0 <= value['sample_review_percent'] <= 100):
            fail('CONFIG_INVALID')
        for key in ('environment_relative_path', 'worker_relative_path',
                    'model_cache_relative_path', 'layout_model_relative_path',
                    'vl_model_relative_path'):
            if not safe_relative(value[key]): fail('CONFIG_PATH_INVALID')
            self.manager.path(value[key])
        thresholds = value['quality_thresholds']
        if set(thresholds) != {'minimum_characters', 'minimum_basic_coverage_ratio',
                              'maximum_basic_expansion_ratio',
                              'minimum_question_number_recall'}:
            fail('CONFIG_INVALID')
        for item in value['critical_model_files']:
            if (set(item) != {'relative_path', 'sha256'}
                    or not safe_relative(item['relative_path'], 'models/cache')
                    or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])):
                fail('CONFIG_MODEL_INVALID')

    def model_status(self, hash_files=True):
        python = self.manager.path(
            self.config['environment_relative_path'] + '/Scripts/python.exe',
            self.config['environment_relative_path'])
        issues = [] if python.is_file() else ['ENVIRONMENT_MISSING']
        files = []
        for item in self.config['critical_model_files']:
            path = self.manager.path(item['relative_path'], 'models/cache')
            actual = digest_file(path) if path.is_file() and hash_files else None
            ready = path.is_file() and (not hash_files or actual == item['sha256'])
            if not ready: issues.append('MODEL_FILE_INVALID')
            files.append({'relative_path': item['relative_path'], 'ready': ready,
                          'sha256_verified': bool(hash_files and ready)})
        return {'ok': not issues, 'issues': sorted(set(issues)),
                'parser_id': self.config['parser_id'],
                'parser_version': self.config['parser_version'],
                'pipeline_version': self.config['pipeline_version'],
                'device': self.config['device'], 'critical_model_files': files}

    def _source(self, source_id, page):
        if not isinstance(source_id, str) or not SID.fullmatch(source_id):
            fail('SOURCE_ID_INVALID')
        if type(page) is not int or page < 1: fail('PAGE_NUMBER_INVALID')
        integrity = self.manager.verify()
        if not integrity['ok']: fail('SOURCE_INTEGRITY_FAILED')
        records, issues = self.manager.manifests()
        if issues or source_id not in records: fail('SOURCE_NOT_REGISTERED')
        record = records[source_id]
        if (record['file_type'] != 'pdf' or record['parser_status'] != 'parsed'
                or page > record['page_count']):
            fail('SOURCE_PAGE_UNAVAILABLE')
        plan = self.manager.load_json(f'{ROUTING}/{source_id}.json', 16 * 1024 * 1024)
        decisions = plan.get('decisions') if isinstance(plan, dict) else None
        if (plan.get('source_id') != source_id or plan.get('page_count') != record['page_count']
                or not isinstance(decisions, list) or len(decisions) != record['page_count']):
            fail('ROUTING_PLAN_INVALID')
        decision = decisions[page - 1]
        if decision.get('page_number') != page: fail('ROUTING_PLAN_INVALID')
        return record, decision

    def inspect(self, source_id, page):
        record, decision = self._source(source_id, page)
        return {'ok': True, 'source_id': source_id, 'page_number': page,
                'source_sha256': record['sha256'], 'route': decision['route'],
                'quality_score': decision['quality_score'],
                'eligible': decision['route'] in {'enhanced_parse_queued', 'review_required'},
                'target_relative_path':
                    f'{OUTPUT}/{source_id}/enhanced/paddleocr-vl/page-{page:04d}',
                'models': self.model_status()}

    def _render(self, source, page, destination):
        if fitz is None: fail('PYMUPDF_REQUIRED')
        document = fitz.open(source)
        try:
            pixmap = document[page - 1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            pixmap.save(destination)
        finally:
            document.close()

    def _run_worker(self, preview, output):
        python = self.manager.path(
            self.config['environment_relative_path'] + '/Scripts/python.exe',
            self.config['environment_relative_path'])
        worker = self.manager.path(self.config['worker_relative_path'], 'scripts')
        layout = self.manager.path(self.config['layout_model_relative_path'], 'models/cache')
        vl_model = self.manager.path(self.config['vl_model_relative_path'], 'models/cache')
        command = [str(python), str(worker), '--input-image', str(preview),
                   '--output-dir', str(output), '--layout-model', str(layout),
                   '--vl-model', str(vl_model), '--pipeline-version',
                   self.config['pipeline_version'], '--device', self.config['device']]
        environment = os.environ.copy()
        environment.update({
            'PADDLE_PDX_CACHE_HOME': str(self.manager.path(
                self.config['model_cache_relative_path'], 'models/cache')),
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
            'HF_HOME': str(self.manager.path('models/cache/huggingface', 'models/cache')),
        })
        started = time.perf_counter()
        try:
            completed = subprocess.run(command, cwd=self.root, env=environment,
                                       capture_output=True, timeout=900, check=False)
        except subprocess.TimeoutExpired:
            fail('LOCAL_INFERENCE_TIMEOUT')
        if completed.returncode != 0: fail('LOCAL_INFERENCE_FAILED')
        report = self.manager.load_json(
            output.relative_to(self.root).as_posix() + '/worker-report.json')
        if report.get('ok') is not True: fail('LOCAL_INFERENCE_FAILED')
        report['controller_elapsed_seconds'] = round(time.perf_counter() - started, 3)
        return report

    def _quality(self, source_id, page, markdown, decision):
        thresholds = self.config['quality_thresholds']
        plain = re.sub(r'<[^>]+>|[`#$*_\\{}\[\]()]', '', markdown)
        basic = basic_text(self.manager.path(
            f'{OUTPUT}/{source_id}/pages/page-{page:04d}.md', OUTPUT))
        issues = []
        if len(plain.strip()) < thresholds['minimum_characters']:
            issues.append('TEXT_TOO_SHORT')
        if '\ufffd' in markdown: issues.append('REPLACEMENT_CHARACTER')
        if not balanced_math(markdown): issues.append('MATH_DELIMITER_OR_BRACE_UNBALANCED')
        issues.extend(formula_integrity_issues(markdown))
        if re.search(r'\]\((?:https?://|/|[A-Za-z]:|\.\.)', markdown):
            issues.append('UNSAFE_LINK')
        basic_length = max(1, len(re.sub(r'\s+', '', basic)))
        ratio = len(re.sub(r'\s+', '', plain)) / basic_length
        if basic and ratio < thresholds['minimum_basic_coverage_ratio']:
            issues.append('BASIC_TEXT_COVERAGE_LOW')
        if basic and ratio > thresholds['maximum_basic_expansion_ratio']:
            issues.append('TEXT_EXPANSION_SUSPICIOUS')
        expected = question_numbers(basic); actual = question_numbers(markdown)
        recall = len(expected & actual) / len(expected) if expected else 1.0
        if expected and recall < thresholds['minimum_question_number_recall']:
            issues.append('QUESTION_NUMBER_COVERAGE_LOW')
        if ('formula_candidate' in decision.get('reasons', [])
                and '$' not in markdown and '\\begin{' not in markdown):
            issues.append('FORMULA_MARKUP_MISSING')
        sampled = int(hashlib.sha256(f'{source_id}:{page}'.encode()).hexdigest()[:8], 16) % 100 \
            < self.config['sample_review_percent']
        status = 'exception_review' if issues else (
            'sample_review' if sampled else 'machine_checked_candidate')
        return {'status': status, 'issues': sorted(set(issues)),
                'sampled_for_review': sampled, 'character_count': len(markdown),
                'replacement_character_count': markdown.count('\ufffd'),
                'basic_text_coverage_ratio': round(ratio, 3),
                'basic_question_numbers': sorted(expected),
                'recognized_question_numbers': sorted(actual),
                'question_number_recall': round(recall, 3),
                'formula_markup_present': '$' in markdown or '\\begin{' in markdown}

    def parse(self, source_id, page, apply=False):
        record, decision = self._source(source_id, page)
        if decision['route'] not in {'enhanced_parse_queued', 'review_required'}:
            fail('PAGE_NOT_QUEUED_FOR_ENHANCEMENT')
        target_relative = f'{OUTPUT}/{source_id}/enhanced/paddleocr-vl/page-{page:04d}'
        target = self.manager.path(target_relative, f'{OUTPUT}/{source_id}/enhanced')
        if target.exists(): fail('TARGET_EXISTS')
        result = {'apply': apply, 'source_id': source_id, 'page_number': page,
                  'target_relative_path': target_relative,
                  'would_modify_basic_output': False, 'would_modify_source': False}
        if not apply: return result
        if not self.model_status()['ok']: fail('MODEL_NOT_READY')
        parent = target.parent; parent.mkdir(parents=True, exist_ok=True)
        temporary = parent / f'.tmp-page-{page:04d}-{uuid.uuid4().hex}'
        temporary.mkdir()
        try:
            source = self.manager.path(record['stored_relative_path'], 'sources-original')
            preview = temporary / 'page-preview.png'
            self._render(source, page, preview)
            report = self._run_worker(preview, temporary)
            markdown_path = temporary / 'paddleocr.md'
            raw_path = temporary / 'paddleocr-result.json'
            if not markdown_path.is_file() or not raw_path.is_file():
                fail('OUTPUT_INCOMPLETE')
            markdown = markdown_path.read_text('utf-8')
            risks = secret_risks(markdown)
            if risks: fail('SENSITIVE_CONTENT_BLOCKED')
            quality = self._quality(source_id, page, markdown, decision)
            atomic_json(temporary / 'quality-report.json', quality)
            manifest = {
                'schema_version': 1, 'derived': True, 'candidate_only': True,
                'source_id': source_id, 'source_sha256': record['sha256'],
                'source_page': page, 'parser_id': self.config['parser_id'],
                'parser_version': self.config['parser_version'],
                'pipeline_version': self.config['pipeline_version'],
                'review_status': quality['status'], 'quality_issues': quality['issues'],
                'created_at': now_iso(), 'input_preview_sha256': digest_file(preview),
                'content_sha256': digest_file(markdown_path),
                'output_relative_path': target_relative + '/paddleocr.md',
                'network_policy': report['network_policy'],
                'device': self.config['device'],
                'timing_seconds': {
                    key: report[key] for key in (
                        'constructor_seconds', 'inference_seconds', 'total_seconds',
                        'controller_elapsed_seconds') if key in report
                },
            }
            atomic_json(temporary / 'candidate-manifest.json', manifest)
            (temporary / 'review.md').write_text(
                '# 自动质量检查\n\n'
                f'- 状态：`{quality["status"]}`\n'
                f'- 原始 PDF 页码：{page}\n'
                f'- 异常：{", ".join(quality["issues"]) if quality["issues"] else "无规则异常"}\n'
                '- 本状态表示机器检查结果，不等同于人工确认数学正确。\n',
                encoding='utf-8', newline='\n')
            if digest_file(source) != record['sha256']: fail('SOURCE_CHANGED_DURING_PARSE')
            temporary.replace(target)
            result.update({'published': True, 'quality_status': quality['status'],
                           'quality_issues': quality['issues']})
            return result
        except Exception as error:
            code = str(error) if isinstance(error, AutoParseError) else 'AUTO_PARSE_FAILED'
            try:
                if temporary.is_dir() and not (temporary / 'failure.json').exists():
                    atomic_json(temporary / 'failure.json', {'ok': False, 'error': code,
                                'source_id': source_id, 'page_number': page})
            finally:
                if isinstance(error, AutoParseError): raise
                fail('AUTO_PARSE_FAILED')

    def verify_output(self, source_id, page):
        record, decision = self._source(source_id, page)
        relative = f'{OUTPUT}/{source_id}/enhanced/paddleocr-vl/page-{page:04d}'
        target = self.manager.path(relative, f'{OUTPUT}/{source_id}/enhanced')
        required = {'page-preview.png', 'paddleocr.md', 'paddleocr-result.json',
                    'worker-report.json', 'quality-report.json',
                    'candidate-manifest.json', 'review.md'}
        if not target.is_dir() or {item.name for item in target.iterdir()} != required:
            fail('OUTPUT_STRUCTURE_INVALID')
        manifest = self.manager.load_json(relative + '/candidate-manifest.json')
        quality = self.manager.load_json(relative + '/quality-report.json')
        current_quality = self._quality(
            source_id, page, (target / 'paddleocr.md').read_text('utf-8'), decision)
        timing = manifest.get('timing_seconds')
        if (manifest.get('source_id') != source_id or manifest.get('source_page') != page
                or manifest.get('source_sha256') != record['sha256']
                or manifest.get('content_sha256') != digest_file(target / 'paddleocr.md')
                or manifest.get('input_preview_sha256') != digest_file(target / 'page-preview.png')
                or manifest.get('review_status') != quality.get('status')
                or manifest.get('review_status') not in {
                    'machine_checked_candidate', 'sample_review', 'exception_review'}
                or (timing is not None and (
                    not isinstance(timing, dict)
                    or any(type(value) not in {int, float} or value < 0
                           for value in timing.values())))):
            fail('CANDIDATE_METADATA_INVALID')
        effective_status = ('exception_review' if current_quality['issues']
                            else current_quality['status'])
        return {'ok': True, 'source_id': source_id, 'page_number': page,
                'stored_review_status': manifest['review_status'],
                'review_status': effective_status,
                'quality_issues': current_quality['issues'],
                'quality_reaudited': True}

    def batch(self, source_id, pages_value, apply=False):
        records, issues = self.manager.manifests()
        if issues or source_id not in records: fail('SOURCE_NOT_REGISTERED')
        pages = parse_pages(pages_value, records[source_id].get('page_count') or 0)
        if len(pages) > self.config['max_pages_per_batch']: fail('BATCH_LIMIT_EXCEEDED')
        results = []
        for page in pages:
            target = self.manager.path(
                f'{OUTPUT}/{source_id}/enhanced/paddleocr-vl/page-{page:04d}',
                f'{OUTPUT}/{source_id}/enhanced')
            if target.exists():
                results.append({'page_number': page, 'status': 'already_complete'})
                continue
            try:
                parsed = self.parse(source_id, page, apply=apply)
                results.append({'page_number': page, 'status':
                    parsed.get('quality_status', 'planned'),
                    'quality_issues': parsed.get('quality_issues', [])})
            except AutoParseError as error:
                results.append({'page_number': page, 'status': 'failed', 'error': str(error)})
        return {'apply': apply, 'source_id': source_id, 'page_count': len(pages),
                'concurrency': 1, 'results': results}

    def status(self, source_id):
        records, issues = self.manager.manifests()
        if issues or source_id not in records: fail('SOURCE_NOT_REGISTERED')
        root = self.manager.path(f'{OUTPUT}/{source_id}/enhanced/paddleocr-vl',
                                 f'{OUTPUT}/{source_id}/enhanced')
        counts = {'machine_checked_candidate': 0, 'sample_review': 0,
                  'exception_review': 0, 'invalid': 0}
        invalid_pages = []
        if root.is_dir():
            for path in root.glob('page-[0-9][0-9][0-9][0-9]'):
                try:
                    page = int(path.name[5:])
                    value = self.verify_output(source_id, page)
                    counts[value['review_status']] += 1
                except (ValueError, AutoParseError) as error:
                    counts['invalid'] += 1
                    invalid_pages.append({
                        'page_number': int(path.name[5:]) if path.name[5:].isdigit() else None,
                        'error': str(error) if isinstance(error, AutoParseError)
                        else 'PAGE_DIRECTORY_INVALID',
                    })
        return {'source_id': source_id, 'page_count': records[source_id]['page_count'],
                'counts': counts, 'invalid_pages': invalid_pages}


def cli(argv=None, root=PROJECT_ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('model-status')
    inspect = commands.add_parser('inspect'); inspect.add_argument('source_id'); inspect.add_argument('page', type=int)
    parse = commands.add_parser('parse'); parse.add_argument('source_id'); parse.add_argument('page', type=int); parse.add_argument('--apply', action='store_true')
    verify = commands.add_parser('verify-output'); verify.add_argument('source_id'); verify.add_argument('page', type=int)
    batch = commands.add_parser('batch'); batch.add_argument('source_id'); batch.add_argument('--pages', required=True); batch.add_argument('--apply', action='store_true')
    status = commands.add_parser('status'); status.add_argument('source_id')
    args = parser.parse_args(argv); tool = AutoParser(root)
    if args.command == 'model-status': result = tool.model_status()
    elif args.command == 'inspect': result = tool.inspect(args.source_id, args.page)
    elif args.command == 'parse': result = tool.parse(args.source_id, args.page, args.apply)
    elif args.command == 'verify-output': result = tool.verify_output(args.source_id, args.page)
    elif args.command == 'batch': result = tool.batch(args.source_id, args.pages, args.apply)
    else: result = tool.status(args.source_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(cli())
    except AutoParseError as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
