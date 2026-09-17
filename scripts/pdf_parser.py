"""Phase 2B local PDF parser: registered PDF sources to review-only Markdown.

No OCR, network, AI, formula conversion, source mutation, or logging of content.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import sys
import uuid

try:
    import fitz
except ImportError:
    fitz = None

try:
    from source_manager import SourceManager, SourceError, SID, json_bytes
except ModuleNotFoundError:
    spec = importlib.util.spec_from_file_location('source_manager_for_pdf', Path(__file__).absolute().parent / 'source_manager.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    SourceManager, SourceError, SID, json_bytes = module.SourceManager, module.SourceError, module.SID, module.json_bytes

PROJECT_ROOT = Path(__file__).absolute().parent.parent
OUTPUT_ROOT = 'vault/90-Parsed-Sources'
PARSER_NAME = 'pymupdf-basic-text'
SCHEMA_VERSION = 1
HIGH_CONFIDENCE_PATTERNS = (
    ('openai_style_api_key', re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}')),
    ('aws_access_key', re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b')),
    ('repository_access_token', re.compile(r'\b(?:ghp_|github_pat_|glpat-)[A-Za-z0-9_-]{20,}')),
    ('private_key_material', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----')),
    ('jwt_bearer_token', re.compile(r'\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}')),
)
FORMULA_CHARS = set('∫∑∏√∞≈≠≤≥∂∇∈∉⊂⊆∪∩→↔±×÷')
PAGE_META = ('source_id', 'source_page', 'derived', 'parse_status', 'review_status',
             'has_images', 'image_count', 'needs_formula_review', 'page_asset')


class ParserError(Exception):
    pass


def fail(code):
    raise ParserError(code)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def secret_risks(value):
    if not isinstance(value, str):
        return []
    found = []
    for risk, pattern in HIGH_CONFIDENCE_PATTERNS:
        for match in pattern.finditer(value):
            token = match.group(0)
            # Avoid textbook placeholders such as sk-example-example... while
            # retaining high-confidence mixed-character credentials.
            if risk == 'openai_style_api_key':
                body = token.split('-', 2)[-1]
                if len(set(body)) < 10 or not re.search(r'[A-Za-z]', body) or not re.search(r'\d', body):
                    continue
            found.append(risk)
            break
    return sorted(set(found))


def has_secret(value):
    return bool(secret_risks(value))


def markdown_text(value):
    """Preserve extracted text exactly inside a fence that disables interpretation."""
    longest = max((len(run) for run in re.findall(r'`+', value)), default=0)
    fence = '`' * max(3, longest + 1)
    separator = '' if value.endswith('\n') else '\n'
    return f'{fence}text\n{value}{separator}{fence}'


def visible_markdown(value):
    output, fence, length = [], None, 0
    for line in value.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence, length = token[0], len(token)
            elif token[0] == fence and len(token) >= length:
                fence = None
            continue
        if fence is None:
            output.append(line)
    return '\n'.join(output)


def formula_reasons(text, image_count):
    reasons = []
    if any(char in text for char in FORMULA_CHARS):
        reasons.append('math_symbols_detected')
    equation_lines = 0
    for line in text.splitlines():
        compact = line.strip()
        if compact and re.search(r'[A-Za-z0-9)]\s*(?:=|≤|≥|≈|≠|\s[+\-*/^<>]\s)\s*[(A-Za-z0-9]', compact):
            equation_lines += 1
    if equation_lines:
        reasons.append('equation_like_text_detected')
    if image_count:
        reasons.append('images_may_contain_formula_or_diagram')
    return reasons


def yaml_scalar(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if type(value) is int:
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def page_document(metadata, text, reasons):
    lines = ['---'] + [f'{key}: {yaml_scalar(metadata[key])}' for key in PAGE_META] + ['---', '', f'# 原始页码 {metadata["source_page"]}', '']
    if metadata['parse_status'] == 'error':
        lines += ['> 本页文本提取失败；错误已登记为固定代码，未跳过此页。', '']
    elif metadata['parse_status'] == 'empty':
        lines += ['> 本页未提取到可见文本，需人工确认是空白页、图片页还是扫描页。', '']
    else:
        lines += ['> 以下为数字原生 PDF 的本地机器提取文本，属于 derived，未经人工核对。', '', text, '']
    if reasons:
        lines += ['## 公式或图形复核', '', '- status: needs_formula_review',
                  f'- source_page: {metadata["source_page"]}',
                  '- uncertainty: ' + ', '.join(reasons),
                  '- asset: ' + (metadata['page_asset'] or 'not_available'), '']
    if metadata['page_asset']:
        lines += ['## 页面预览', '', f'![原始页码 {metadata["source_page"]} 页面预览]({metadata["page_asset"]})', '']
    return '\n'.join(lines)


def parse_frontmatter(text):
    lines = text.lstrip('\ufeff').splitlines()
    if not lines or lines[0] != '---':
        fail('PAGE_FRONTMATTER_MISSING')
    try:
        end = lines.index('---', 1)
    except ValueError:
        fail('PAGE_FRONTMATTER_INVALID')
    result = {}
    for line in lines[1:end]:
        if ': ' not in line:
            fail('PAGE_FRONTMATTER_INVALID')
        key, raw = line.split(': ', 1)
        if key in result or key not in PAGE_META:
            fail('PAGE_FRONTMATTER_INVALID')
        try:
            result[key] = json.loads(raw)
        except json.JSONDecodeError:
            fail('PAGE_FRONTMATTER_INVALID')
    if tuple(result) != PAGE_META:
        fail('PAGE_FRONTMATTER_INVALID')
    return result


def parse_simple_frontmatter(text):
    lines = text.lstrip('\ufeff').splitlines()
    if not lines or lines[0] != '---':
        fail('INDEX_FRONTMATTER_INVALID')
    try:
        end = lines.index('---', 1)
    except ValueError:
        fail('INDEX_FRONTMATTER_INVALID')
    result = {}
    for line in lines[1:end]:
        if ': ' not in line:
            fail('INDEX_FRONTMATTER_INVALID')
        key, raw = line.split(': ', 1)
        if key in result:
            fail('INDEX_FRONTMATTER_INVALID')
        try:
            result[key] = json.loads(raw)
        except json.JSONDecodeError:
            fail('INDEX_FRONTMATTER_INVALID')
    return result


class PDFParser:
    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root).absolute()
        self.manager = SourceManager(self.root)
        self.output_root = self.manager.path(OUTPUT_ROOT)
        if not self.output_root.is_dir():
            fail('OUTPUT_ROOT_MISSING')

    def source(self, source_id, allow_output_inconsistency=False):
        if not isinstance(source_id, str) or not SID.fullmatch(source_id):
            fail('SOURCE_ID_INVALID')
        report = self.manager.verify()
        output_errors = {'PARSE_STATE_CONFLICT', 'PARSED_OUTPUT_MISSING',
                         'PARSED_OUTPUT_MISSING_OR_UNREADABLE', 'PARSE_MANIFEST_REPORT_CONFLICT'}
        blocking = [item for item in report['issues']
                    if not allow_output_inconsistency or item.get('error') not in output_errors]
        if blocking:
            fail('SOURCE_INTEGRITY_FAILED')
        records, issues = self.manager.manifests()
        if issues or source_id not in records:
            fail('SOURCE_NOT_REGISTERED')
        record = records[source_id]
        if record['file_type'] != 'pdf':
            fail('SOURCE_NOT_PDF')
        if has_secret(record['original_filename']):
            fail('SENSITIVE_FILENAME')
        kind, digest, size = self.manager.inspect(record['stored_relative_path'])
        if kind != 'pdf' or digest != record['sha256'] or size != record['size_bytes']:
            fail('SOURCE_INTEGRITY_FAILED')
        return record

    def _open(self, record):
        if fitz is None:
            fail('PYMUPDF_UNAVAILABLE')
        path = self.manager.path(record['stored_relative_path'], 'sources-original')
        try:
            document = fitz.open(path)
        except Exception:
            fail('PDF_OPEN_FAILED')
        if document.needs_pass:
            document.close()
            fail('PDF_PASSWORD_REQUIRED')
        if document.page_count < 1 or document.page_count > 10000:
            document.close()
            fail('PDF_PAGE_COUNT_INVALID')
        return document

    def inspect(self, source_id):
        record = self.source(source_id)
        with self._open(record) as document:
            result = {'source_id': source_id, 'file_type': 'pdf', 'page_count': document.page_count,
                      'encrypted': bool(document.is_encrypted), 'sha256': record['sha256'],
                      'parser': PARSER_NAME, 'parser_version': fitz.__version__, 'read_only': True}
        # Ensure the source did not change while the PDF library was reading it.
        if self.manager.digest(record['stored_relative_path'])[0] != record['sha256']:
            fail('SOURCE_CHANGED_DURING_INSPECTION')
        return result

    def _extract_page(self, page):
        return page.get_text('text', sort=True)

    def _render(self, page, path):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        pixmap.save(path)

    def plan(self, source_id):
        if not isinstance(source_id, str) or not SID.fullmatch(source_id):
            fail('SOURCE_ID_INVALID')
        target = f'{OUTPUT_ROOT}/{source_id}'
        if self.manager.path(target).exists():
            fail('OUTPUT_EXISTS')
        info = self.inspect(source_id)
        return {'dry_run': True, **info, 'output_relative_path': target,
                'derived': True, 'review_status': 'review_required'}

    def _write_text(self, path, text):
        path.write_text(text, encoding='utf-8', newline='\n')

    def _write_json(self, path, value):
        path.write_bytes(json_bytes(value))

    def _blocked_report(self, record, page_number, risks):
        report = {'schema_version': 1, 'source_id': record['source_id'],
                  'source_sha256': record['sha256'], 'status': 'blocked_sensitive_content',
                  'error_code': 'SENSITIVE_CONTENT_BLOCKED',
                  'affected_pages': [page_number], 'risk_types': risks,
                  'created_at': now_iso(), 'contains_source_text': False}
        relative = f'review-queue/pdf-parse-blocks/{record["source_id"]}.json'
        self.manager.write_json(relative, report)

    def _build(self, record, temporary):
        pages_dir = temporary / 'pages'
        assets_dir = temporary / 'assets'
        pages_dir.mkdir()
        assets_dir.mkdir()
        entries, warnings = [], set()
        with self._open(record) as document:
            declared = document.page_count
            for index in range(declared):
                number = index + 1
                page_name = f'page-{number:04d}.md'
                asset_name = f'page-{number:04d}.png'
                status, raw, error = 'extracted', '', None
                page = document.load_page(index)
                try:
                    raw = self._extract_page(page)
                except Exception:
                    status, error = 'error', 'PAGE_TEXT_EXTRACTION_FAILED'
                    warnings.add('page_text_extraction_failed')
                risks = secret_risks(raw)
                if risks:
                    self._blocked_report(record, number, risks)
                    fail('SENSITIVE_CONTENT_BLOCKED')
                text = markdown_text(raw)
                image_count = len(page.get_images(full=True))
                reasons = formula_reasons(raw, image_count)
                if status != 'error' and not raw.strip():
                    status = 'empty'
                    warnings.add('empty_text_page')
                if image_count:
                    warnings.add('images_present')
                if reasons:
                    warnings.add('formula_or_graphics_review_required')
                asset = None
                if image_count or reasons or status in ('empty', 'error'):
                    try:
                        self._render(page, assets_dir / asset_name)
                        asset = '../assets/' + asset_name
                    except Exception:
                        warnings.add('page_preview_render_failed')
                metadata = {'source_id': record['source_id'], 'source_page': number, 'derived': True,
                            'parse_status': status, 'review_status': 'review_required',
                            'has_images': bool(image_count), 'image_count': image_count,
                            'needs_formula_review': bool(reasons), 'page_asset': asset}
                self._write_text(pages_dir / page_name, page_document(metadata, text, reasons))
                entries.append({'page_number': number, 'relative_path': 'pages/' + page_name,
                                'parse_status': status, 'character_count': len(raw),
                                'image_count': image_count, 'needs_formula_review': bool(reasons),
                                'formula_review_reasons': reasons, 'asset_relative_path': asset[3:] if asset else None,
                                'error_code': error})
        # Detect a source mutation before publication.
        if self.manager.digest(record['stored_relative_path'])[0] != record['sha256']:
            fail('SOURCE_CHANGED_DURING_PARSE')
        generated = now_iso()
        report = {'schema_version': SCHEMA_VERSION, 'source_id': record['source_id'],
                  'source_sha256': record['sha256'], 'derived': True,
                  'review_status': 'review_required', 'parser_name': PARSER_NAME,
                  'parser_version': fitz.__version__, 'parsed_at': generated,
                  'declared_page_count': declared, 'output_page_count': len(entries),
                  'total_character_count': sum(e['character_count'] for e in entries),
                  'empty_pages': [e['page_number'] for e in entries if e['parse_status'] == 'empty'],
                  'error_pages': [e['page_number'] for e in entries if e['parse_status'] == 'error'],
                  'image_pages': [e['page_number'] for e in entries if e['image_count']],
                  'image_count': sum(e['image_count'] for e in entries),
                  'formula_review_pages': [e['page_number'] for e in entries if e['needs_formula_review']],
                  'quality_warnings': sorted(warnings), 'pages': entries}
        self._write_json(temporary / 'parse-report.json', report)
        index = [
            '---', f'source_id: {yaml_scalar(record["source_id"])}', 'derived: true',
            'review_status: "review_required"', f'parser_name: {yaml_scalar(PARSER_NAME)}',
            f'parser_version: {yaml_scalar(fitz.__version__)}', f'page_count: {declared}',
            f'parsed_at: {yaml_scalar(generated)}', '---', '', '# 解析资料索引', '',
            '> 本目录是 derived 解析产物，初始状态为 review_required，不是原始资料或正式知识笔记。', '',
            f'- 来源 ID：`{record["source_id"]}`',
            f'- 原始文件名：`{record["original_filename"]}`',
            f'- 分类：`{record["course"]}` / `{record["subject"]}` / `{record["source_type"]}`',
            f'- 解析器：`{PARSER_NAME}` `{fitz.__version__}`', f'- PDF 声明页数：{declared}',
            f'- 解析时间：{generated}', '- 质量状态：review_required', '', '## 页面', ''
        ]
        index += [f'- [[{entry["relative_path"][:-3]}|原始页码 {entry["page_number"]}]] — {entry["parse_status"]}' for entry in entries]
        self._write_text(temporary / 'index.md', '\n'.join(index) + '\n')
        review = ['# 人工审核清单', '', f'- source_id: `{record["source_id"]}`',
                  '- derived: true', '- review_status: review_required', '',
                  '## 全局检查', '', '- [ ] 页数与原件一致', '- [ ] 页面顺序与原件一致',
                  '- [ ] 标题候选未被误当作正式结构', '- [ ] 公式和图形已逐页核对',
                  '- [ ] 已确认解析产物未改写原文', '', '## 逐页检查', '']
        review += [f'- [ ] 原始页码 {entry["page_number"]}：文本、图片、公式/图形与状态已核对'
                   for entry in entries]
        self._write_text(temporary / 'review.md', '\n'.join(review) + '\n')
        return report

    def _safe_cleanup(self, temporary, identity):
        try:
            info = self.manager._metadata(temporary)
        except FileNotFoundError:
            return
        if (info.st_dev, info.st_ino) != (identity.st_dev, identity.st_ino):
            fail('TEMP_IDENTITY_CHANGED')
        # Refuse cleanup if another process inserted a link/reparse point.
        for path in temporary.rglob('*'):
            self.manager._metadata(path)
        shutil.rmtree(temporary)

    def _publish(self, temporary, destination):
        os.rename(temporary, destination)  # no-overwrite semantics on Windows

    def parse(self, source_id, execute=False):
        preview = self.plan(source_id)
        if not execute:
            return preview
        with self.manager.lock():
            record = self.source(source_id)
            destination = self.manager.path(f'{OUTPUT_ROOT}/{source_id}')
            if destination.exists():
                fail('OUTPUT_EXISTS')
            temporary = self.manager.path(f'{OUTPUT_ROOT}/.tmp-{source_id}-{uuid.uuid4().hex}')
            temporary.mkdir(exist_ok=False)
            identity = self.manager._metadata(temporary)
            try:
                report = self._build(record, temporary)
                self.verify_directory(temporary, record, report)
                if destination.exists():
                    fail('OUTPUT_EXISTS')
                self._publish(temporary, destination)
                self.manager.mark_parsed(record, PARSER_NAME, fitz.__version__,
                                         report['output_page_count'], report['parsed_at'],
                                         self.manager.relative(destination))
                verified = self.verify_output(source_id)
                return {'dry_run': False, 'source_id': source_id,
                        'output_relative_path': self.manager.relative(destination),
                        'review_status': verified['review_status'],
                        'page_count': report['output_page_count'], 'manifest_status': 'parsed'}
            finally:
                self._safe_cleanup(temporary, identity)

    def _load_report(self, path):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
            fail('PARSE_REPORT_INVALID')
        if not isinstance(value, dict):
            fail('PARSE_REPORT_INVALID')
        return value

    def _safe_relative_link(self, target, base):
        target = target.split('#', 1)[0]
        if (not target or PureWindowsPath(target).drive or PureWindowsPath(target).root
                or target.startswith('/') or '\\' in target or ':' in target):
            return False
        stack = [part for part in PurePosixPath(base).parts if part not in ('', '.')]
        for part in PurePosixPath(target).parts:
            if part in ('', '.'):
                continue
            if part == '..':
                if not stack:
                    return False
                stack.pop()
            else:
                stack.append(part)
        return True

    def _link_target(self, target, path, directory, wiki=False):
        target = target.split('#', 1)[0]
        if not self._safe_relative_link(target, path.parent.relative_to(directory).as_posix()):
            fail('EXTERNAL_OR_UNSAFE_LINK')
        candidate = path.parent / target
        if wiki and not candidate.suffix:
            candidate = candidate.with_suffix('.md')
        try:
            candidate.resolve().relative_to(directory.resolve())
        except ValueError:
            fail('EXTERNAL_OR_UNSAFE_LINK')
        if not candidate.is_file():
            fail('INTERNAL_LINK_MISSING')

    def verify_directory(self, directory, record, supplied_report=None):
        if directory.name != record['source_id'] and not directory.name.startswith('.tmp-' + record['source_id'] + '-'):
            fail('OUTPUT_DIRECTORY_INVALID')
        required = {'index.md', 'review.md', 'parse-report.json', 'pages', 'assets'}
        supplemental = {'enhanced', 'quality', 'annotations', 'accepted'}
        names = {p.name for p in directory.iterdir()}
        if not required.issubset(names) or names - required - supplemental:
            fail('OUTPUT_STRUCTURE_INVALID')
        if not (directory / 'pages').is_dir() or not (directory / 'assets').is_dir():
            fail('OUTPUT_STRUCTURE_INVALID')
        if any((directory / name).exists() and not (directory / name).is_dir()
               for name in supplemental):
            fail('OUTPUT_STRUCTURE_INVALID')
        report = supplied_report or self._load_report(directory / 'parse-report.json')
        mandatory = {'schema_version', 'source_id', 'source_sha256', 'derived', 'review_status',
                     'parser_name', 'parser_version', 'parsed_at', 'declared_page_count',
                     'output_page_count', 'total_character_count', 'empty_pages', 'error_pages',
                     'image_pages', 'image_count', 'formula_review_pages', 'quality_warnings', 'pages'}
        if (set(report) != mandatory or report.get('schema_version') != SCHEMA_VERSION
                or report.get('source_id') != record['source_id'] or report.get('source_sha256') != record['sha256']
                or report.get('derived') is not True or report.get('review_status') != 'review_required'
                or report.get('parser_name') != PARSER_NAME or not isinstance(report.get('pages'), list)):
            fail('PARSE_REPORT_INVALID')
        try:
            parsed_at = datetime.fromisoformat(report['parsed_at'])
        except (TypeError, ValueError):
            fail('PARSE_REPORT_INVALID')
        if (parsed_at.tzinfo is None or not isinstance(report.get('parser_version'), str)
                or not report['parser_version'] or not isinstance(report.get('quality_warnings'), list)
                or any(not isinstance(item, str) for item in report['quality_warnings'])):
            fail('PARSE_REPORT_INVALID')
        declared = report['declared_page_count']
        if type(declared) is not int or declared < 1 or report['output_page_count'] != declared or len(report['pages']) != declared:
            fail('PAGE_COUNT_MISMATCH')
        expected_pages = {f'page-{n:04d}.md' for n in range(1, declared + 1)}
        actual_pages = {p.name for p in (directory / 'pages').iterdir() if p.is_file()}
        if actual_pages != expected_pages or any(p.is_dir() for p in (directory / 'pages').iterdir()):
            fail('PAGE_FILES_MISMATCH')
        expected_assets = set()
        computed_empty, computed_errors, computed_images, computed_formula = [], [], [], []
        computed_chars = computed_image_count = 0
        computed_warnings = set()
        for number, entry in enumerate(report['pages'], 1):
            entry_fields = {'page_number', 'relative_path', 'parse_status', 'character_count', 'image_count',
                            'needs_formula_review', 'formula_review_reasons', 'asset_relative_path',
                            'error_code'}
            if (not isinstance(entry, dict) or set(entry) != entry_fields
                    or entry.get('page_number') != number
                    or entry.get('relative_path') != f'pages/page-{number:04d}.md'
                    or entry.get('parse_status') not in {'extracted', 'empty', 'error'}
                    or type(entry.get('character_count')) is not int or entry['character_count'] < 0
                    or type(entry.get('image_count')) is not int or entry['image_count'] < 0
                    or type(entry.get('needs_formula_review')) is not bool
                    or not isinstance(entry.get('formula_review_reasons'), list)
                    or any(not isinstance(item, str) for item in entry['formula_review_reasons'])):
                fail('PAGE_REPORT_INVALID')
            if ((entry['parse_status'] == 'error') != (entry['error_code'] == 'PAGE_TEXT_EXTRACTION_FAILED')
                    or entry['needs_formula_review'] != bool(entry['formula_review_reasons'])):
                fail('PAGE_REPORT_INVALID')
            page_path = directory / entry['relative_path']
            metadata = parse_frontmatter(page_path.read_text(encoding='utf-8'))
            if (metadata['source_id'] != record['source_id'] or metadata['source_page'] != number
                    or metadata['derived'] is not True or metadata['review_status'] != 'review_required'
                    or metadata['parse_status'] != entry.get('parse_status')
                    or metadata['image_count'] != entry.get('image_count')
                    or metadata['has_images'] is not bool(entry.get('image_count'))
                    or metadata['needs_formula_review'] is not bool(entry.get('needs_formula_review'))):
                fail('PAGE_METADATA_MISMATCH')
            asset = entry.get('asset_relative_path')
            if asset:
                if asset != f'assets/page-{number:04d}.png' or metadata['page_asset'] != '../' + asset:
                    fail('PAGE_ASSET_INVALID')
                expected_assets.add(Path(asset).name)
            elif metadata['page_asset'] is not None:
                fail('PAGE_ASSET_INVALID')
            computed_chars += entry['character_count']
            computed_image_count += entry['image_count']
            if entry['parse_status'] == 'empty':
                computed_empty.append(number)
                computed_warnings.add('empty_text_page')
            if entry['parse_status'] == 'error':
                computed_errors.append(number)
                computed_warnings.add('page_text_extraction_failed')
            if entry['image_count']:
                computed_images.append(number)
                computed_warnings.add('images_present')
            if entry['needs_formula_review']:
                computed_formula.append(number)
                computed_warnings.add('formula_or_graphics_review_required')
            if (entry['parse_status'] in {'empty', 'error'} or entry['image_count']
                    or entry['needs_formula_review']) and not asset:
                computed_warnings.add('page_preview_render_failed')
        if (report['total_character_count'] != computed_chars or report['image_count'] != computed_image_count
                or report['empty_pages'] != computed_empty or report['error_pages'] != computed_errors
                or report['image_pages'] != computed_images or report['formula_review_pages'] != computed_formula
                or report['quality_warnings'] != sorted(computed_warnings)):
            fail('REPORT_METRICS_MISMATCH')
        actual_assets = {p.name for p in (directory / 'assets').iterdir() if p.is_file()}
        if actual_assets != expected_assets or any(p.is_dir() for p in (directory / 'assets').iterdir()):
            fail('ASSET_FILES_MISMATCH')
        for name in expected_assets:
            if not (directory / 'assets' / name).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                fail('ASSET_FORMAT_INVALID')
        index_text = (directory / 'index.md').read_text(encoding='utf-8')
        index_meta = parse_simple_frontmatter(index_text)
        expected_index = {'source_id': record['source_id'], 'derived': True,
                          'review_status': 'review_required', 'parser_name': PARSER_NAME,
                          'parser_version': report['parser_version'], 'page_count': declared,
                          'parsed_at': report['parsed_at']}
        if index_meta != expected_index:
            fail('INDEX_METADATA_MISMATCH')
        review_text = (directory / 'review.md').read_text(encoding='utf-8')
        if (f'- source_id: `{record["source_id"]}`' not in review_text
                or '- derived: true' not in review_text
                or '- review_status: review_required' not in review_text):
            fail('REVIEW_METADATA_MISMATCH')
        published = directory.name == record['source_id']
        if published and (record['parser_status'] != 'parsed'
                or record['parser_name'] != report['parser_name']
                or record['parser_version'] != report['parser_version']
                or record['page_count'] != declared or record['parsed_at'] != report['parsed_at']
                or record['parsed_output_relative_path'] != f'{OUTPUT_ROOT}/{record["source_id"]}'
                or record['parse_review_status'] != 'review_required'):
            fail('MANIFEST_PARSE_STATE_MISMATCH')
        core_paths = [directory / 'index.md', directory / 'review.md',
                      directory / 'parse-report.json']
        core_paths += list((directory / 'pages').iterdir())
        core_paths += list((directory / 'assets').iterdir())
        for path in core_paths:
            info = self.manager._metadata(path)
            if stat.S_ISREG(info.st_mode) and path.suffix.lower() in ('.md', '.json'):
                content = path.read_text(encoding='utf-8')
                if has_secret(content):
                    fail('SENSITIVE_PATTERN_IN_OUTPUT')
                visible = visible_markdown(content)
                for link in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', visible):
                    self._link_target(link, path, directory)
                for link in re.findall(r'!?\[\[([^\]|#]+)', visible):
                    self._link_target(link, path, directory, wiki=True)
                if re.search(r'(?<!\\)\$\$?', visible):
                    fail('UNREVIEWED_LATEX_SYNTAX')
        with self._open(record) as source_document:
            if source_document.page_count != declared:
                fail('SOURCE_PAGE_COUNT_MISMATCH')
        return {'ok': True, 'source_id': record['source_id'], 'page_count': declared,
                'review_status': 'review_required', 'quality_warnings': report['quality_warnings']}

    def verify_output(self, source_id):
        record = self.source(source_id, allow_output_inconsistency=True)
        directory = self.manager.path(f'{OUTPUT_ROOT}/{source_id}')
        if not directory.is_dir():
            fail('OUTPUT_MISSING')
        return self.verify_directory(directory, record)

    def report(self, source_id):
        verified = self.verify_output(source_id)
        path = self.manager.path(f'{OUTPUT_ROOT}/{source_id}/parse-report.json')
        report = self._load_report(path)
        return {**verified, 'declared_page_count': report['declared_page_count'],
                'output_page_count': report['output_page_count'],
                'total_character_count': report['total_character_count'],
                'empty_pages': report['empty_pages'], 'error_pages': report['error_pages'],
                'image_pages': report['image_pages'], 'image_count': report['image_count'],
                'formula_review_pages': report['formula_review_pages']}


def cli(argv=None):
    parser = argparse.ArgumentParser(description='Phase 2B local native-PDF parser; default parse mode is dry-run.')
    sub = parser.add_subparsers(dest='command', required=True)
    for command, help_text in (
        ('inspect', 'Read-only PDF metadata check'), ('verify-output', 'Verify a published derived output'),
        ('report', 'Show the verified quality report without page text')):
        child = sub.add_parser(command, help=help_text)
        child.add_argument('source_id')
    parse = sub.add_parser('parse', help='Preview parsing; --apply creates review-only derived output')
    parse.add_argument('source_id')
    parse.add_argument('--apply', action='store_true', help='Explicitly create output after integrity checks')
    args = parser.parse_args(argv)
    try:
        tool = PDFParser()
        if args.command == 'parse':
            result = tool.parse(args.source_id, execute=args.apply)
        elif args.command == 'verify-output':
            result = tool.verify_output(args.source_id)
        else:
            result = getattr(tool, args.command)(args.source_id)
        print(json_bytes(result).decode('utf-8'), end='')
        return 0
    except ParserError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
    except SourceError as exc:
        print(json.dumps({'ok': False, 'error': 'SOURCE_' + str(exc)}))
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print(json.dumps({'ok': False, 'error': 'IO_OR_INPUT_ERROR'}))
    return 1


if __name__ == '__main__':
    sys.exit(cli())
