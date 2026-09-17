"""Safe single-page MinerU candidate parser for registered PDF sources."""
import argparse
import ctypes
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
    from source_manager import SourceManager, SourceError, SID, json_bytes
except ModuleNotFoundError:
    spec = importlib.util.spec_from_file_location(
        'source_manager_for_enhanced', Path(__file__).absolute().parent / 'source_manager.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    SourceManager, SourceError, SID, json_bytes = (
        module.SourceManager, module.SourceError, module.SID, module.json_bytes)

try:
    from pdf_parser import secret_risks
except ModuleNotFoundError:
    pdf_spec = importlib.util.spec_from_file_location(
        'pdf_parser_for_enhanced', Path(__file__).absolute().parent / 'pdf_parser.py')
    pdf_module = importlib.util.module_from_spec(pdf_spec)
    pdf_spec.loader.exec_module(pdf_module)
    secret_risks = pdf_module.secret_risks

PROJECT_ROOT = Path(__file__).absolute().parent.parent
CONFIG = 'config/enhanced-parser.example.json'
ROUTING = 'review-queue/parsing-routing'
OUTPUT_ROOT = 'vault/90-Parsed-Sources'


class EnhancedError(Exception):
    pass


def fail(code):
    raise EnhancedError(code)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest_file(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


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
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def process_memory_bytes(pid):
    if os.name != 'nt':
        return 0
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('PageFaultCount', ctypes.c_ulong),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t), ('PagefileUsage', ctypes.c_size_t),
                    ('PeakPagefileUsage', ctypes.c_size_t)]
    handle = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0400, False, pid)
    if not handle:
        return 0
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
        return 0
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def available_memory_bytes():
    if os.name != 'nt':
        return 0
    class Status(ctypes.Structure):
        _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
    status = Status()
    status.dwLength = ctypes.sizeof(status)
    return int(status.ullAvailPhys) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)) else 0


def gpu_used_bytes():
    try:
        completed = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5, check=True)
        return int(completed.stdout.splitlines()[0].strip()) * 1024 * 1024
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return 0


class EnhancedParser:
    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root).absolute()
        self.manager = SourceManager(self.root)
        self.config = self.manager.load_json(CONFIG)
        self._validate_config()

    def _validate_config(self):
        required = {'schema_version', 'parser_id', 'parser_version',
                    'environment_relative_path', 'worker_relative_path',
                    'model_home_relative_path', 'tier', 'small_backend', 'vlm_engine',
                    'model_repositories', 'critical_model_files', 'timeouts',
                    'network_policy', 'max_pages_per_run', 'review_status'}
        value = self.config
        if (set(value) != required or value['schema_version'] != 1
                or value['parser_id'] != 'enhanced_mineru_standard'
                or value['tier'] != 'standard' or value['small_backend'] != 'onnx'
                or value['vlm_engine'] != 'llama-cpp'
                or value['network_policy'] != 'local_models_and_socket_blocking'
                or value['max_pages_per_run'] != 1
                or value['review_status'] != 'review_required'):
            fail('CONFIG_INVALID')
        for key in ('environment_relative_path', 'worker_relative_path',
                    'model_home_relative_path'):
            if not safe_relative(value[key]):
                fail('CONFIG_PATH_INVALID')
            self.manager.path(value[key])
        if set(value['timeouts']) != {
                'model_readiness_seconds', 'cold_start_seconds', 'single_page_seconds'}:
            fail('CONFIG_INVALID')
        if any(type(item) is not int or item <= 0 for item in value['timeouts'].values()):
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
        worker = self.manager.path(self.config['worker_relative_path'], 'scripts')
        issues = []
        if not python.is_file():
            issues.append('ENVIRONMENT_MISSING')
        if not worker.is_file():
            issues.append('WORKER_MISSING')
        files = []
        for item in self.config['critical_model_files']:
            path = self.manager.path(item['relative_path'], 'models/cache')
            actual = digest_file(path) if path.is_file() and hash_files else None
            ready = path.is_file() and (not hash_files or actual == item['sha256'])
            if not ready:
                issues.append('MODEL_FILE_INVALID')
            files.append({'relative_path': item['relative_path'], 'ready': ready,
                          'sha256_verified': bool(hash_files and ready)})
        return {'ok': not issues, 'issues': sorted(set(issues)),
                'parser_id': self.config['parser_id'],
                'parser_version': self.config['parser_version'],
                'tier': self.config['tier'], 'network_policy': self.config['network_policy'],
                'critical_model_files': files}

    def _source(self, source_id, page_number):
        if not isinstance(source_id, str) or not SID.fullmatch(source_id):
            fail('SOURCE_ID_INVALID')
        if type(page_number) is not int or page_number < 1:
            fail('PAGE_NUMBER_INVALID')
        integrity = self.manager.verify()
        if not integrity['ok']:
            fail('SOURCE_INTEGRITY_FAILED')
        records, issues = self.manager.manifests()
        if issues or source_id not in records:
            fail('SOURCE_NOT_REGISTERED')
        record = records[source_id]
        if (record['file_type'] != 'pdf' or record['parser_status'] != 'parsed'
                or page_number > record['page_count']):
            fail('SOURCE_PAGE_UNAVAILABLE')
        route = self.manager.load_json(f'{ROUTING}/{source_id}.json', 8 * 1024 * 1024)
        decisions = route.get('decisions') if isinstance(route, dict) else None
        if (route.get('source_id') != source_id or route.get('page_count') != record['page_count']
                or not isinstance(decisions, list) or len(decisions) != record['page_count']):
            fail('ROUTING_PLAN_INVALID')
        decision = decisions[page_number - 1]
        if (decision.get('page_number') != page_number
                or decision.get('route') != 'enhanced_parse_queued'):
            fail('PAGE_NOT_QUEUED_FOR_ENHANCEMENT')
        return record, decision

    def inspect(self, source_id, page_number):
        record, decision = self._source(source_id, page_number)
        models = self.model_status(hash_files=True)
        return {'ok': models['ok'], 'source_id': source_id, 'page_number': page_number,
                'source_sha256': record['sha256'], 'route': decision['route'],
                'quality_score': decision['quality_score'], 'models': models,
                'output_relative_path':
                    f'{OUTPUT_ROOT}/{source_id}/enhanced/mineru/page-{page_number:04d}',
                'would_modify_basic_output': False, 'review_status': 'review_required'}

    def _environment(self):
        environment = os.environ.copy()
        home = str(self.manager.path(self.config['model_home_relative_path'], 'models/cache'))
        environment.update({
            'MINERU_HOME': home, 'MINERU_MODEL_SOURCE': 'local',
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
            'HF_HOME': str(self.manager.path('models/cache/huggingface', 'models/cache')),
            'HUGGINGFACE_HUB_CACHE': str(self.manager.path(
                'models/cache/huggingface/hub', 'models/cache')),
            'MODELSCOPE_CACHE': str(self.manager.path('models/cache/modelscope', 'models/cache')),
        })
        return environment

    def _run_worker(self, input_path, page_number, temporary):
        python = self.manager.path(
            self.config['environment_relative_path'] + '/Scripts/python.exe',
            self.config['environment_relative_path'])
        worker = self.manager.path(self.config['worker_relative_path'], 'scripts')
        command = [str(python), str(worker), '--input', str(input_path), '--page',
                   str(page_number), '--output-dir', str(temporary), '--tier', self.config['tier']]
        before_gpu = gpu_used_bytes()
        peak_gpu = before_gpu
        peak_memory = 0
        available_before = available_memory_bytes()
        minimum_available = available_before
        started = time.perf_counter()
        process = subprocess.Popen(command, cwd=self.root, env=self._environment(),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        timeout = (self.config['timeouts']['cold_start_seconds']
                   + self.config['timeouts']['single_page_seconds'])
        while process.poll() is None:
            elapsed = time.perf_counter() - started
            if elapsed > timeout:
                process.kill()
                process.communicate(timeout=30)
                fail('LOCAL_INFERENCE_TIMEOUT')
            peak_memory = max(peak_memory, process_memory_bytes(process.pid))
            current_available = available_memory_bytes()
            if current_available:
                minimum_available = min(minimum_available or current_available, current_available)
            if int(elapsed * 5) % 5 == 0:
                peak_gpu = max(peak_gpu, gpu_used_bytes())
            time.sleep(0.2)
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode != 0:
            fail('LOCAL_INFERENCE_FAILED')
        report = json.loads((temporary / 'worker-report.json').read_text(encoding='utf-8'))
        if report.get('ok') is not True:
            fail('LOCAL_INFERENCE_FAILED')
        report['peak_worker_process_memory_bytes'] = peak_memory
        report['available_system_memory_before_bytes'] = available_before
        report['minimum_available_system_memory_bytes'] = minimum_available
        report['observed_system_memory_drop_bytes'] = max(
            0, available_before - minimum_available) if available_before and minimum_available else 0
        report['gpu_memory_before_bytes'] = before_gpu
        report['peak_gpu_memory_bytes'] = peak_gpu
        report['captured_output_bytes'] = len(stdout) + len(stderr)
        return report

    def parse(self, source_id, page_number, apply=False):
        record, decision = self._source(source_id, page_number)
        target_relative = f'{OUTPUT_ROOT}/{source_id}/enhanced/mineru/page-{page_number:04d}'
        target = self.manager.path(target_relative, f'{OUTPUT_ROOT}/{source_id}')
        if target.exists():
            fail('TARGET_EXISTS')
        models = self.model_status(hash_files=True)
        if not models['ok']:
            fail('MODEL_NOT_READY')
        preview = {'source_id': source_id, 'page_number': page_number,
                   'target_relative_path': target_relative, 'apply': bool(apply),
                   'parser_id': self.config['parser_id'], 'tier': self.config['tier'],
                   'review_status': 'review_required', 'would_overwrite': False,
                   'would_modify_original': False, 'would_modify_basic_output': False}
        if not apply:
            return preview
        if fitz is None:
            fail('PYMUPDF_UNAVAILABLE')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f'.tmp-page-{page_number:04d}-{uuid.uuid4().hex}'
        temporary.mkdir()
        source_path = self.manager.path(record['stored_relative_path'], 'sources-original')
        before_hash, before_size = self.manager.digest(record['stored_relative_path'])
        try:
            with fitz.open(source_path) as document:
                page = document.load_page(page_number - 1)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                (temporary / 'page-preview.png').write_bytes(pixmap.tobytes('png'))
            preview_hash = digest_file(temporary / 'page-preview.png')
            worker = self._run_worker(source_path, page_number, temporary)
            markdown = (temporary / 'mineru.md').read_text(encoding='utf-8')
            risks = secret_risks(markdown)
            if risks:
                atomic_json(temporary / 'failure.json', {
                    'ok': False, 'error': 'SENSITIVE_CONTENT_BLOCKED',
                    'source_id': source_id, 'page_number': page_number,
                    'risk_types': risks, 'contains_source_text': False,
                    'created_at': now_iso(),
                })
                fail('SENSITIVE_CONTENT_BLOCKED')
            warnings = []
            if '\ufffd' in markdown:
                warnings.append('replacement_char_present')
            if re.search(r'https?://|file:|[A-Za-z]:[/\\]', markdown):
                warnings.append('external_or_absolute_link_present')
            metadata = {
                'schema_version': 1, 'source_id': source_id,
                'source_sha256': record['sha256'], 'source_page': page_number,
                'input_size_bytes': before_size, 'page_preview_sha256': preview_hash,
                'parser_id': self.config['parser_id'],
                'parser_version': self.config['parser_version'], 'tier': 'standard',
                'small_backend': 'onnx', 'vlm_engine': 'llama-cpp',
                'model_repositories': self.config['model_repositories'],
                'critical_model_files': self.config['critical_model_files'],
                'created_at': now_iso(), 'derived': True, 'candidate_only': True,
                'review_status': 'review_required', 'quality_score_before': decision['quality_score'],
                'route_reasons': decision['reasons'], 'markdown_characters': len(markdown),
                'replacement_char_count': markdown.count('\ufffd'),
                'formula_delimiter_count': markdown.count('$'), 'warnings': warnings,
                'network_policy': self.config['network_policy'], 'runtime_metrics': worker,
                'basic_output_modified': False, 'original_modified': False,
            }
            atomic_json(temporary / 'candidate-manifest.json', metadata)
            (temporary / 'review.md').write_text(
                '# 增强候选人工审核\n\n'
                f'- source_id：`{source_id}`\n- 原始页码：{page_number}\n'
                '- 状态：`review_required`\n- [ ] 对照页面预览检查下标和上下标\n'
                '- [ ] 检查补码、负号、不等号和二进制位号\n'
                '- [ ] 检查题干、选项和阅读顺序\n- [ ] 检查公式数学含义\n'
                '- [ ] 记录仍无法确认的区域\n', encoding='utf-8', newline='\n')
            after_hash, after_size = self.manager.digest(record['stored_relative_path'])
            if (before_hash, before_size) != (after_hash, after_size):
                fail('SOURCE_CHANGED_DURING_PARSE')
            if not all((temporary / name).is_file() for name in (
                    'page-preview.png', 'mineru.md', 'mineru-result.json',
                    'worker-report.json', 'candidate-manifest.json', 'review.md')):
                fail('CANDIDATE_INCOMPLETE')
            temporary.rename(target)
            return {**preview, 'apply': True, 'published': True,
                    'warnings': warnings, 'runtime_metrics': worker}
        except EnhancedError:
            failure = temporary / 'failure.json'
            if not failure.exists():
                atomic_json(failure, {'ok': False, 'error': 'ENHANCED_PARSE_FAILED',
                                     'source_id': source_id, 'page_number': page_number,
                                     'created_at': now_iso()})
            raise
        except Exception:
            failure = temporary / 'failure.json'
            if not failure.exists():
                atomic_json(failure, {'ok': False, 'error': 'ENHANCED_PARSE_FAILED',
                                     'source_id': source_id, 'page_number': page_number,
                                     'created_at': now_iso()})
            fail('ENHANCED_PARSE_FAILED')

    def verify_output(self, source_id, page_number):
        record, _ = self._source(source_id, page_number)
        relative = f'{OUTPUT_ROOT}/{source_id}/enhanced/mineru/page-{page_number:04d}'
        folder = self.manager.path(relative, f'{OUTPUT_ROOT}/{source_id}')
        if not folder.is_dir():
            fail('CANDIDATE_MISSING')
        expected = {'page-preview.png', 'mineru.md', 'mineru-result.json',
                    'worker-report.json', 'candidate-manifest.json', 'review.md'}
        actual = {item.name for item in folder.iterdir() if item.is_file()}
        if actual != expected or any(item.is_dir() for item in folder.iterdir()):
            fail('CANDIDATE_FILESET_INVALID')
        metadata = json.loads((folder / 'candidate-manifest.json').read_text(encoding='utf-8'))
        if (metadata.get('source_id') != source_id
                or metadata.get('source_sha256') != record['sha256']
                or metadata.get('source_page') != page_number
                or metadata.get('derived') is not True
                or metadata.get('candidate_only') is not True
                or metadata.get('review_status') != 'review_required'
                or metadata.get('page_preview_sha256') != digest_file(folder / 'page-preview.png')):
            fail('CANDIDATE_METADATA_INVALID')
        if secret_risks((folder / 'mineru.md').read_text(encoding='utf-8')):
            fail('SENSITIVE_CONTENT_BLOCKED')
        if digest_file(self.manager.path(record['stored_relative_path'], 'sources-original')) != record['sha256']:
            fail('SOURCE_HASH_MISMATCH')
        return {'ok': True, 'source_id': source_id, 'page_number': page_number,
                'parser_id': metadata['parser_id'], 'parser_version': metadata['parser_version'],
                'review_status': metadata['review_status'], 'warnings': metadata['warnings']}

    def report(self, source_id, page_number):
        verified = self.verify_output(source_id, page_number)
        folder = self.manager.path(
            f'{OUTPUT_ROOT}/{source_id}/enhanced/mineru/page-{page_number:04d}',
            f'{OUTPUT_ROOT}/{source_id}')
        metadata = json.loads((folder / 'candidate-manifest.json').read_text(encoding='utf-8'))
        return {**verified, 'markdown_characters': metadata['markdown_characters'],
                'replacement_char_count': metadata['replacement_char_count'],
                'formula_delimiter_count': metadata['formula_delimiter_count'],
                'runtime_metrics': metadata['runtime_metrics']}


def cli(argv=None):
    parser = argparse.ArgumentParser(description='Local one-page MinerU enhancement; default dry-run.')
    sub = parser.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect')
    inspect.add_argument('source_id'); inspect.add_argument('page', type=int)
    parse = sub.add_parser('parse')
    parse.add_argument('source_id'); parse.add_argument('page', type=int)
    parse.add_argument('--apply', action='store_true')
    verify = sub.add_parser('verify-output')
    verify.add_argument('source_id'); verify.add_argument('page', type=int)
    report = sub.add_parser('report')
    report.add_argument('source_id'); report.add_argument('page', type=int)
    status = sub.add_parser('model-status')
    status.add_argument('--skip-hash', action='store_true')
    args = parser.parse_args(argv)
    try:
        engine = EnhancedParser()
        if args.command == 'inspect':
            result = engine.inspect(args.source_id, args.page)
        elif args.command == 'parse':
            result = engine.parse(args.source_id, args.page, args.apply)
        elif args.command == 'verify-output':
            result = engine.verify_output(args.source_id, args.page)
        elif args.command == 'report':
            result = engine.report(args.source_id, args.page)
        else:
            result = engine.model_status(hash_files=not args.skip_hash)
        print(json_bytes(result).decode('utf-8'), end='')
        return 0
    except EnhancedError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
    except SourceError as exc:
        print(json.dumps({'ok': False, 'error': 'SOURCE_' + str(exc)}))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        print(json.dumps({'ok': False, 'error': 'IO_OR_INPUT_ERROR'}))
    return 1


if __name__ == '__main__':
    sys.exit(cli())
