"""Phase 2C/2D-0 architecture: quality routing and dry-run batch planning.

Only the PyMuPDF adapter is implemented. Enhanced/cloud adapters are inert
interfaces. The CLI reads registered metadata and existing Phase 2B outputs.
It can save plans and queue metadata, but never parses, reparses, or mutates
originals and existing parsed output.
"""
from abc import ABC, abstractmethod
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys

try:
    import yaml
except ImportError:
    yaml = None

try:
    import fitz
except ImportError:
    fitz = None

try:
    from source_manager import SourceManager, SourceError, SID, json_bytes
except ModuleNotFoundError:
    spec = importlib.util.spec_from_file_location(
        'source_manager_for_architecture', Path(__file__).absolute().parent / 'source_manager.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    SourceManager, SourceError, SID, json_bytes = (
        module.SourceManager, module.SourceError, module.SID, module.json_bytes)

PROJECT_ROOT = Path(__file__).absolute().parent.parent
PROFILES_FILE = 'config/parsing-profiles.yaml'
LIMITS_FILE = 'config/resource-limits.yaml'
ROUTING_QUEUE = 'review-queue/parsing-routing'
JOB_QUEUE = 'review-queue/parsing-jobs'
CHECKPOINT_QUEUE = 'review-queue/parsing-checkpoints'
PARSER_IDS = {
    'basic_pymupdf', 'paddleocr_vl_local', 'enhanced_mineru_pipeline',
    'enhanced_docling_formula', 'optional_mathpix_formula_crop',
}
ROUTES = {
    'basic_accepted_candidate', 'review_required', 'enhanced_parse_queued',
    'manual_or_optional_cloud_review',
}
BATCH_CATEGORIES = {
    'basic', 'enhanced', 'manual_review', 'resource_deferred',
    'already_queued', 'unsupported'
}
VALID_COURSES = {'math1', '408'}
VALID_SUBJECTS = {
    'calculus', 'linear-algebra', 'probability', 'data-structure',
    'computer-organization', 'operating-system', 'computer-network',
}
VALID_SOURCE_TYPES = {
    'textbook', 'wangdao', 'zhangyu', 'teacher-ppt', 'past-paper',
    'exercise', 'notes', 'other',
}


def enhanced_output_path(source_id, page_number, parser_id):
    """Return the isolated candidate location for a routed enhanced parser."""
    folders = {
        'paddleocr_vl_local': 'paddleocr-vl',
        'enhanced_mineru_pipeline': 'mineru',
        'enhanced_docling_formula': 'docling',
    }
    if parser_id not in folders:
        fail('PARSER_NOT_LOCAL_ENHANCED')
    return (f'vault/90-Parsed-Sources/{source_id}/enhanced/{folders[parser_id]}/'
            f'page-{page_number:04d}')
METRIC_FIELDS = {
    'character_count', 'replacement_char_count', 'replacement_char_rate',
    'subscript_or_superscript_risk', 'formula_density', 'matrix_or_fraction_risk',
    'code_density', 'low_text_density', 'image_only_page', 'table_risk',
    'multi_column_risk', 'reading_order_risk', 'font_encoding_warning',
    'formula_candidate', 'image_count', 'basic_failed', 'unsupported',
}
STATES = {
    'not_started', 'basic_parsed', 'quality_scored', 'enhanced_queued',
    'enhanced_candidate_ready', 'review_required', 'accepted_for_retrieval',
    'blocked', 'failed', 'encoding_degraded', 'manual_correction_pending',
}
TRANSITIONS = {
    'not_started': {'basic_parsed', 'blocked', 'failed'},
    'basic_parsed': {'quality_scored', 'encoding_degraded', 'failed'},
    'quality_scored': {'enhanced_queued', 'review_required',
                       'encoding_degraded', 'blocked', 'failed'},
    'encoding_degraded': {'enhanced_queued', 'review_required',
                          'manual_correction_pending', 'failed'},
    'enhanced_queued': {'enhanced_candidate_ready', 'failed', 'blocked'},
    'enhanced_candidate_ready': {'review_required', 'manual_correction_pending', 'failed'},
    'review_required': {'accepted_for_retrieval', 'enhanced_queued',
                        'manual_correction_pending', 'blocked'},
    'manual_correction_pending': {'review_required', 'blocked'},
    'failed': {'enhanced_queued', 'manual_correction_pending', 'blocked'},
    'accepted_for_retrieval': set(),
    'blocked': set(),
}


class ArchitectureError(Exception):
    """Only fixed codes may cross the CLI boundary."""


def fail(code):
    raise ArchitectureError(code)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def timezone_iso(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def safe_relative(value, prefix=None):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') for p in path.parts):
        return False
    return prefix is None or value == prefix or value.startswith(prefix.rstrip('/') + '/')


def load_yaml(path):
    if yaml is None:
        fail('PYYAML_UNAVAILABLE')
    try:
        class UniqueSafeLoader(yaml.SafeLoader):
            def construct_mapping(self, node, deep=False):
                result = {}
                for key_node, value_node in node.value:
                    key = self.construct_object(key_node, deep=deep)
                    if not isinstance(key, str) or key in result:
                        fail('CONFIG_DUPLICATE_KEY')
                    result[key] = self.construct_object(value_node, deep=deep)
                return result
        with path.open('r', encoding='utf-8') as stream:
            value = yaml.load(stream, Loader=UniqueSafeLoader)
    except (OSError, UnicodeError, yaml.YAMLError):
        fail('CONFIG_INVALID')
    if not isinstance(value, dict):
        fail('CONFIG_INVALID')
    return value


def validate_profiles(value):
    if set(value) != {'schema_version', 'parser_catalog', 'profiles', 'routing'}:
        fail('PROFILE_SCHEMA_INVALID')
    if value['schema_version'] != 1 or set(value['parser_catalog']) != PARSER_IDS:
        fail('PROFILE_SCHEMA_INVALID')
    for parser_id, parser in value['parser_catalog'].items():
        if (not isinstance(parser, dict)
                or set(parser) != {'implementation_status', 'parser_mode', 'network_allowed'}
                or not isinstance(parser['parser_mode'], str)
                or type(parser['network_allowed']) is not bool):
            fail('PROFILE_SCHEMA_INVALID')
        if parser_id == 'optional_mathpix_formula_crop' and parser['network_allowed']:
            fail('NETWORK_PARSER_MUST_BE_DISABLED')
    if set(value['profiles']) != {'math1_formula_dense', 'cs408_general', 'cs408_symbol_dense'}:
        fail('PROFILE_SCHEMA_INVALID')
    threshold_fields = {
        'replacement_char_count', 'replacement_char_rate',
        'subscript_or_superscript_risk', 'formula_density', 'matrix_or_fraction_risk',
        'code_density', 'low_text_density', 'image_only_page', 'table_risk',
        'multi_column_risk', 'reading_order_risk', 'font_encoding_warning',
    }
    for name, profile in value['profiles'].items():
        if set(profile) != {'course', 'subjects', 'preferred_enhanced_parser',
                           'fallback_enhanced_parser', 'thresholds'}:
            fail('PROFILE_SCHEMA_INVALID')
        if profile['course'] not in {'math1', '408'} or not isinstance(profile['subjects'], list):
            fail('PROFILE_SCHEMA_INVALID')
        if (profile['preferred_enhanced_parser'] not in PARSER_IDS
                or profile['fallback_enhanced_parser'] not in PARSER_IDS):
            fail('PROFILE_SCHEMA_INVALID')
        thresholds = profile['thresholds']
        if not isinstance(thresholds, dict) or set(thresholds) != threshold_fields:
            fail('PROFILE_SCHEMA_INVALID')
        for key, threshold in thresholds.items():
            if key.endswith('_risk') or key in {'image_only_page', 'font_encoding_warning'}:
                if type(threshold) is not bool:
                    fail('PROFILE_SCHEMA_INVALID')
            elif not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or threshold < 0:
                fail('PROFILE_SCHEMA_INVALID')
    routing = value['routing']
    if (routing.get('normal') != 'basic_accepted_candidate'
            or routing.get('mild_anomaly') != 'review_required'
            or routing.get('formula_symbol_or_encoding_anomaly') != 'enhanced_parse_queued'
            or routing.get('high_risk_or_unsupported') != 'manual_or_optional_cloud_review'
            or any(routing.get(k) is not False for k in (
                'automatic_knowledge_note_entry', 'enhanced_may_overwrite_basic',
                'latex_syntax_implies_semantic_correctness'))):
        fail('PROFILE_SCHEMA_INVALID')
    return value


def validate_limits(value, root):
    if set(value) != {'schema_version', 'hardware_profile', 'project_root_constraint',
                     'model_cache_relative_path', 'queue_relative_path',
                     'checkpoint_relative_path', 'limits', 'execution', 'planning'}:
        fail('LIMIT_SCHEMA_INVALID')
    if value['schema_version'] != 2 or Path(value['project_root_constraint']) != root:
        fail('LIMIT_ROOT_INVALID')
    for key in ('model_cache_relative_path', 'queue_relative_path', 'checkpoint_relative_path'):
        if not safe_relative(value[key]):
            fail('LIMIT_PATH_INVALID')
        candidate = root.joinpath(*PurePosixPath(value[key]).parts).absolute()
        if not candidate.is_relative_to(root):
            fail('LIMIT_PATH_INVALID')
    required_limits = {
        'max_concurrent_jobs', 'max_pages_per_run', 'max_single_file_size_bytes',
        'max_render_pixels_per_page', 'max_processing_seconds_per_page',
        'max_memory_bytes', 'max_vram_bytes', 'max_retry_count_per_page',
    }
    if set(value['limits']) != required_limits:
        fail('LIMIT_SCHEMA_INVALID')
    if any(type(v) is not int or v <= 0 for v in value['limits'].values()):
        fail('LIMIT_SCHEMA_INVALID')
    if value['limits']['max_concurrent_jobs'] != 1:
        fail('CONCURRENCY_LIMIT_UNSAFE')
    required_execution = {
        'checkpoint_after_each_page', 'resume_from_last_verified_page', 'retry_scope',
        'heavy_parsers_for_anomaly_pages_only', 'prohibit_concurrent_bulk_reruns',
        'preserve_previous_results', 'require_explicit_acceptance_for_retrieval',
        'require_explicit_authorization_for_cloud',
    }
    execution = value['execution']
    if set(execution) != required_execution or execution['retry_scope'] != 'single_page_only':
        fail('LIMIT_SCHEMA_INVALID')
    if any(execution[k] is not True for k in required_execution - {'retry_scope'}):
        fail('LIMIT_SCHEMA_INVALID')
    required_planning = {
        'default_batch_pages', 'require_dry_run_by_default',
        'forbid_unconfirmed_inbox', 'heavy_jobs_exclusive',
        'estimated_basic_bytes_per_page', 'estimated_enhanced_bytes_per_page',
        'estimated_basic_peak_memory_bytes', 'estimated_enhanced_peak_memory_bytes',
        'estimated_enhanced_peak_vram_bytes', 'hardware_memory_bytes',
        'hardware_vram_bytes',
    }
    planning = value['planning']
    if not isinstance(planning, dict) or set(planning) != required_planning:
        fail('LIMIT_SCHEMA_INVALID')
    boolean_fields = {'require_dry_run_by_default', 'forbid_unconfirmed_inbox',
                      'heavy_jobs_exclusive'}
    if any(planning[key] is not True for key in boolean_fields):
        fail('LIMIT_SCHEMA_INVALID')
    for key in required_planning - boolean_fields:
        if type(planning[key]) is not int or planning[key] <= 0:
            fail('LIMIT_SCHEMA_INVALID')
    if (planning['default_batch_pages'] != value['limits']['max_pages_per_run']
            or planning['hardware_memory_bytes'] < value['limits']['max_memory_bytes']
            or planning['hardware_vram_bytes'] < value['limits']['max_vram_bytes']):
        fail('LIMIT_SCHEMA_INVALID')
    return value


@dataclass(frozen=True)
class PageParseResult:
    parser_id: str
    parser_version: str
    parser_mode: str
    page_number: int
    text: str
    formula_candidates: list
    image_candidates: list
    layout_warnings: list
    extraction_metrics: dict
    review_status: str
    output_relative_path: str

    def validate(self):
        if (self.parser_id not in PARSER_IDS or not self.parser_version
                or not self.parser_mode or type(self.page_number) is not int
                or self.page_number < 1 or not isinstance(self.text, str)
                or not all(isinstance(v, list) for v in (
                    self.formula_candidates, self.image_candidates, self.layout_warnings))
                or not isinstance(self.extraction_metrics, dict)
                or self.review_status not in {'review_required', 'candidate_only'}
                or not safe_relative(self.output_relative_path, 'vault/90-Parsed-Sources')):
            fail('PARSER_RESULT_INVALID')
        return asdict(self)


class ParserAdapter(ABC):
    parser_id = None
    parser_mode = None

    @abstractmethod
    def parse_page(self, source_id, page_number, source_relative_path, output_relative_path):
        raise NotImplementedError


class BasicPyMuPDFAdapter(ParserAdapter):
    parser_id = 'basic_pymupdf'
    parser_mode = 'local_basic_text'

    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root).absolute()
        self.manager = SourceManager(self.root)

    def parse_page(self, source_id, page_number, source_relative_path, output_relative_path):
        if fitz is None:
            fail('PYMUPDF_UNAVAILABLE')
        if not SID.fullmatch(source_id) or type(page_number) is not int or page_number < 1:
            fail('PAGE_IDENTITY_INVALID')
        if not safe_relative(source_relative_path, 'sources-original'):
            fail('SOURCE_PATH_INVALID')
        if not safe_relative(output_relative_path,
                             f'vault/90-Parsed-Sources/{source_id}/basic'):
            fail('OUTPUT_PATH_INVALID')
        path = self.manager.path(source_relative_path, 'sources-original')
        before = self.manager.digest(source_relative_path)
        try:
            with fitz.open(path) as document:
                if page_number > document.page_count:
                    fail('PAGE_NUMBER_INVALID')
                page = document.load_page(page_number - 1)
                text = page.get_text('text', sort=True)
                images = [{'source_page': page_number, 'index': n + 1}
                          for n, _ in enumerate(page.get_images(full=True))]
        except ArchitectureError:
            raise
        except Exception:
            fail('BASIC_PARSE_FAILED')
        if self.manager.digest(source_relative_path) != before:
            fail('SOURCE_CHANGED_DURING_READ')
        metrics = metrics_from_text(text, len(images))
        formula = ([{'source_page': page_number, 'reason': 'formula_risk_detected'}]
                   if metrics['formula_candidate'] else [])
        return PageParseResult(
            self.parser_id, fitz.__version__, self.parser_mode, page_number, text,
            formula, images, [], metrics, 'review_required', output_relative_path)


class UnavailableAdapter(ParserAdapter):
    def __init__(self, parser_id, parser_mode):
        if parser_id not in PARSER_IDS or parser_id == 'basic_pymupdf':
            fail('PARSER_ID_INVALID')
        self.parser_id, self.parser_mode = parser_id, parser_mode

    def parse_page(self, source_id, page_number, source_relative_path, output_relative_path):
        fail('PARSER_NOT_INSTALLED')


def metrics_from_text(text, image_count=0, basic_failed=False):
    if not isinstance(text, str) or type(image_count) is not int or image_count < 0:
        fail('METRICS_INPUT_INVALID')
    characters = len(text)
    replacement = text.count('\ufffd')
    nonspace = sum(not c.isspace() for c in text)
    formula_tokens = len(re.findall(r'[=+−±×÷√∫∑∏≠≤≥^/]', text))
    code_tokens = len(re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', text))
    subscript = bool(re.search(r'[\u2070-\u209f]|[A-Za-z][\[_]?\d+[\]]?', text))
    matrix = bool(re.search(r'\[[^\]\n]+[,;][^\]\n]+\]|\b(?:det|matrix)\b|\S+\s*/\s*\S+', text, re.I))
    table = bool('\t' in text or re.search(r'\S +\S +\S', text))
    formula_density = formula_tokens / max(nonspace, 1)
    code_density = sum(len(t) for t in re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', text)) / max(nonspace, 1)
    return {
        'character_count': characters,
        'replacement_char_count': replacement,
        'replacement_char_rate': replacement / max(characters, 1),
        'subscript_or_superscript_risk': subscript,
        'formula_density': formula_density,
        'matrix_or_fraction_risk': matrix,
        'code_density': code_density,
        'low_text_density': characters,
        'image_only_page': image_count > 0 and not text.strip(),
        'table_risk': table,
        'multi_column_risk': False,
        'reading_order_risk': False,
        'font_encoding_warning': replacement > 0,
        'formula_candidate': formula_tokens > 0,
        'image_count': image_count,
        'basic_failed': bool(basic_failed),
        'unsupported': False,
    }


def extracted_text_from_page(markdown):
    """Return only the Phase 2B fenced source text, never surrounding metadata."""
    lines = markdown.splitlines(keepends=True)
    for index, line in enumerate(lines):
        found = re.fullmatch(r'(`{3,})text\r?\n', line)
        if not found:
            continue
        fence = found.group(1)
        for end in range(index + 1, len(lines)):
            if lines[end].rstrip('\r\n') == fence:
                return ''.join(lines[index + 1:end])
        fail('BASIC_PAGE_TEXT_INVALID')
    # Empty/error pages intentionally have no source-text fence.
    return ''


def validate_metrics(metrics):
    if not isinstance(metrics, dict) or set(metrics) != METRIC_FIELDS:
        fail('QUALITY_METRICS_INVALID')
    integer_fields = {'character_count', 'replacement_char_count', 'low_text_density', 'image_count'}
    rate_fields = {'replacement_char_rate', 'formula_density', 'code_density'}
    for key in integer_fields:
        if type(metrics[key]) is not int or metrics[key] < 0:
            fail('QUALITY_METRICS_INVALID')
    for key in rate_fields:
        if not isinstance(metrics[key], (int, float)) or isinstance(metrics[key], bool) or metrics[key] < 0:
            fail('QUALITY_METRICS_INVALID')
    for key in METRIC_FIELDS - integer_fields - rate_fields:
        if type(metrics[key]) is not bool:
            fail('QUALITY_METRICS_INVALID')


def score_and_route(metrics, profile):
    validate_metrics(metrics)
    thresholds = profile['thresholds']
    reasons = []
    if metrics['basic_failed']:
        reasons.append('basic_parse_failed')
    if metrics['unsupported']:
        reasons.append('unsupported_page')
    if reasons:
        return 0, 'manual_or_optional_cloud_review', reasons
    enhanced = []
    if metrics['replacement_char_count'] >= thresholds['replacement_char_count'] > 0:
        enhanced.append('replacement_char_count')
    if metrics['replacement_char_rate'] >= thresholds['replacement_char_rate'] > 0:
        enhanced.append('replacement_char_rate')
    for key in ('subscript_or_superscript_risk', 'matrix_or_fraction_risk', 'font_encoding_warning'):
        if thresholds[key] and metrics[key]:
            enhanced.append(key)
    if metrics['formula_density'] >= thresholds['formula_density'] > 0:
        enhanced.append('formula_density')
    if thresholds['image_only_page'] and metrics['image_only_page']:
        enhanced.append('image_only_page')
    mild = []
    for key in ('table_risk', 'multi_column_risk', 'reading_order_risk'):
        if thresholds[key] and metrics[key]:
            mild.append(key)
    if metrics['formula_candidate']:
        mild.append('formula_candidate')
    if metrics['image_count']:
        mild.append('images_present')
    if metrics['character_count'] < thresholds['low_text_density']:
        mild.append('low_text_density')
    penalty = min(90, len(set(enhanced)) * 18 + len(set(mild)) * 7
                  + min(metrics['replacement_char_count'], 20))
    score = max(0, 100 - penalty)
    if enhanced:
        return score, 'enhanced_parse_queued', sorted(set(enhanced + mild))
    if mild:
        return score, 'review_required', sorted(set(mild))
    return score, 'basic_accepted_candidate', []


class PageStateMachine:
    def __init__(self, source_id, page_number, state='not_started', history=None):
        if not isinstance(source_id, str) or not SID.fullmatch(source_id):
            fail('PAGE_IDENTITY_INVALID')
        if type(page_number) is not int or page_number < 1 or state not in STATES:
            fail('PAGE_IDENTITY_INVALID')
        self.source_id, self.page_number, self.state = source_id, page_number, state
        self.history = list(history or [])

    def transition(self, target, parser_id, reason, timestamp=None):
        if target not in STATES or target not in TRANSITIONS[self.state]:
            fail('STATE_TRANSITION_INVALID')
        if parser_id not in PARSER_IDS or not isinstance(reason, str) or not reason.strip():
            fail('STATE_EVENT_INVALID')
        event = {'source_id': self.source_id, 'page_number': self.page_number,
                 'from': self.state, 'to': target, 'timestamp': timestamp or now_iso(),
                 'parser_id': parser_id, 'reason': reason}
        if not timezone_iso(event['timestamp']):
            fail('STATE_EVENT_INVALID')
        self.history.append(event)
        self.state = target
        return event

    def retry_task(self, parser_id, reason, retry_count, max_retries):
        if self.state not in {'failed', 'encoding_degraded', 'manual_correction_pending'}:
            fail('RETRY_STATE_INVALID')
        if type(retry_count) is not int or retry_count < 0 or retry_count >= max_retries:
            fail('RETRY_LIMIT_REACHED')
        if parser_id not in PARSER_IDS:
            fail('PARSER_ID_INVALID')
        return {'source_id': self.source_id, 'page_number': self.page_number,
                'parser_id': parser_id, 'reason': reason, 'retry_count': retry_count + 1,
                'scope': 'single_page_only', 'status': 'queued'}


class SourceStateMachine:
    def __init__(self, source_id, state='not_started', history=None):
        if not isinstance(source_id, str) or not SID.fullmatch(source_id) or state not in STATES:
            fail('SOURCE_ID_INVALID')
        self.source_id, self.state, self.history = source_id, state, list(history or [])

    def transition(self, target, parser_id, reason, timestamp=None):
        if target not in STATES or target not in TRANSITIONS[self.state]:
            fail('STATE_TRANSITION_INVALID')
        if parser_id not in PARSER_IDS or not isinstance(reason, str) or not reason.strip():
            fail('STATE_EVENT_INVALID')
        value = timestamp or now_iso()
        if not timezone_iso(value):
            fail('STATE_EVENT_INVALID')
        event = {'source_id': self.source_id, 'page_number': None,
                 'from': self.state, 'to': target, 'timestamp': value,
                 'parser_id': parser_id, 'reason': reason}
        self.history.append(event)
        self.state = target
        return event


def build_page_jobs(decisions, completed_pages, limits):
    """Build bounded page-only jobs; verified pages are checkpoints and skipped."""
    if not isinstance(decisions, list) or not isinstance(completed_pages, (set, list, tuple)):
        fail('QUEUE_INPUT_INVALID')
    completed = set(completed_pages)
    maximum = limits['limits']['max_pages_per_run']
    jobs = []
    for decision in decisions:
        page = decision.get('page_number') if isinstance(decision, dict) else None
        if type(page) is not int or page < 1:
            fail('QUEUE_INPUT_INVALID')
        if page in completed or decision.get('route') != 'enhanced_parse_queued':
            continue
        jobs.append({'source_id': decision['source_id'], 'page_number': page,
                     'parser_id': decision['preferred_enhanced_parser'],
                     'status': 'queued', 'scope': 'single_page_only',
                     'preserve_basic_output': True})
        if len(jobs) >= maximum:
            break
    return jobs


def validate_routing_plan(plan):
    fields = {'schema_version', 'plan_type', 'source_id', 'source_sha256', 'profile',
              'created_at', 'basic_output_layout', 'future_output_root',
              'does_not_reparse', 'does_not_modify_existing_output',
              'automatic_knowledge_note_entry', 'source_state', 'source_transition',
              'page_count', 'decisions'}
    if not isinstance(plan, dict) or set(plan) != fields or plan.get('schema_version') != 1:
        fail('ROUTING_PLAN_INVALID')
    sid = plan.get('source_id')
    if (not isinstance(sid, str) or not SID.fullmatch(sid)
            or not re.fullmatch(r'[0-9a-f]{64}', plan.get('source_sha256', ''))
            or not plan['source_sha256'].startswith(sid[4:])
            or plan.get('plan_type') != 'quality_routing_only'
            or plan.get('basic_output_layout') != 'phase2b_legacy_flat_read_only'
            or plan.get('future_output_root') != f'vault/90-Parsed-Sources/{sid}'
            or plan.get('does_not_reparse') is not True
            or plan.get('does_not_modify_existing_output') is not True
            or plan.get('automatic_knowledge_note_entry') is not False
            or plan.get('source_state') != 'review_required'
            or not timezone_iso(plan.get('created_at'))
            or type(plan.get('page_count')) is not int or plan['page_count'] < 1
            or not isinstance(plan.get('decisions'), list)
            or len(plan['decisions']) != plan['page_count']):
        fail('ROUTING_PLAN_INVALID')
    source_transition = plan['source_transition']
    if (not isinstance(source_transition, dict)
            or set(source_transition) != {'from', 'to', 'timestamp', 'parser_id',
                                          'reason', 'source_id', 'page_number'}
            or source_transition['from'] != 'quality_scored'
            or source_transition['to'] != 'review_required'
            or source_transition['source_id'] != sid
            or source_transition['page_number'] is not None
            or source_transition['parser_id'] != 'basic_pymupdf'
            or source_transition['reason'] != 'page_quality_routing_completed'
            or not timezone_iso(source_transition['timestamp'])):
        fail('ROUTING_PLAN_INVALID')
    decision_fields = {
        'source_id', 'page_number', 'source_page', 'profile', 'basic_parser_id',
        'basic_parser_version', 'quality_score', 'metrics', 'route', 'reasons',
        'current_state', 'planned_state', 'preferred_enhanced_parser', 'review_status',
        'planned_transition', 'basic_output_relative_path', 'enhanced_output_relative_path',
    }
    for number, decision in enumerate(plan['decisions'], 1):
        if not isinstance(decision, dict) or set(decision) != decision_fields:
            fail('ROUTING_PLAN_INVALID')
        validate_metrics(decision['metrics'])
        expected_basic = f'vault/90-Parsed-Sources/{sid}/pages/page-{number:04d}.md'
        if (decision['source_id'] != sid or decision['page_number'] != number
                or decision['source_page'] != number or decision['profile'] != plan['profile']
                or decision['basic_parser_id'] != 'basic_pymupdf'
                or not isinstance(decision['basic_parser_version'], str)
                or type(decision['quality_score']) is not int
                or not 0 <= decision['quality_score'] <= 100
                or decision['route'] not in ROUTES
                or not isinstance(decision['reasons'], list)
                or any(not isinstance(v, str) for v in decision['reasons'])
                or decision['current_state'] not in STATES or decision['planned_state'] not in STATES
                or decision['review_status'] != 'review_required'
                or decision['basic_output_relative_path'] != expected_basic):
            fail('ROUTING_PLAN_INVALID')
        enhanced = decision['enhanced_output_relative_path']
        if decision['route'] == 'enhanced_parse_queued':
            if (decision['preferred_enhanced_parser'] not in {
                    'paddleocr_vl_local', 'enhanced_mineru_pipeline',
                    'enhanced_docling_formula'}
                    or not safe_relative(enhanced,
                        f'vault/90-Parsed-Sources/{sid}/enhanced')):
                fail('ROUTING_PLAN_INVALID')
        elif enhanced is not None or decision['preferred_enhanced_parser'] is not None:
            fail('ROUTING_PLAN_INVALID')
        transition = decision['planned_transition']
        if (not isinstance(transition, dict)
                or set(transition) != {'from', 'to', 'timestamp', 'parser_id', 'reason',
                                       'source_id', 'page_number'}
                or transition['from'] != decision['current_state']
                or transition['to'] != decision['planned_state']
                or transition['to'] not in TRANSITIONS[transition['from']]
                or transition['source_id'] != sid or transition['page_number'] != number
                or transition['parser_id'] != 'basic_pymupdf'
                or not isinstance(transition['reason'], str) or not transition['reason']
                or not timezone_iso(transition['timestamp'])):
            fail('ROUTING_PLAN_INVALID')
    return plan


class RoutingPlanner:
    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root).absolute()
        self.manager = SourceManager(self.root)
        self.profiles = validate_profiles(load_yaml(self.manager.path(PROFILES_FILE)))
        self.limits = validate_limits(load_yaml(self.manager.path(LIMITS_FILE)), self.root)

    def _existing_report(self, source_id):
        integrity = self.manager.verify()
        if not integrity['ok']:
            fail('SOURCE_OR_BASIC_INTEGRITY_FAILED')
        records, issues = self.manager.manifests()
        if issues or source_id not in records:
            fail('SOURCE_NOT_REGISTERED')
        record = records[source_id]
        if record['parser_status'] != 'parsed':
            fail('BASIC_OUTPUT_REQUIRED')
        output = record['parsed_output_relative_path']
        report = self.manager.load_json(output + '/parse-report.json', 32 * 1024 * 1024)
        if (not isinstance(report.get('pages'), list)
                or report.get('output_page_count') != record['page_count']
                or len(report['pages']) != record['page_count']):
            fail('BASIC_REPORT_INVALID')
        return record, report, self.manager.path(output, 'vault/90-Parsed-Sources')

    def plan_existing(self, source_id, profile_name):
        if not isinstance(source_id, str) or not SID.fullmatch(source_id):
            fail('SOURCE_ID_INVALID')
        if profile_name not in self.profiles['profiles']:
            fail('PROFILE_NOT_FOUND')
        profile = self.profiles['profiles'][profile_name]
        record, report, output = self._existing_report(source_id)
        if record['course'] != profile['course'] or record['subject'] not in profile['subjects']:
            fail('PROFILE_SOURCE_MISMATCH')
        decisions = []
        for entry in report['pages']:
            page_number = entry['page_number']
            expected_page = f'pages/page-{page_number:04d}.md'
            if entry.get('relative_path') != expected_page:
                fail('BASIC_PAGE_PATH_INVALID')
            page_relative = record['parsed_output_relative_path'] + '/' + expected_page
            page_path = self.manager.path(page_relative, record['parsed_output_relative_path'])
            with self.manager.reader(page_relative) as stream:
                try:
                    markdown = stream.read().decode('utf-8')
                except UnicodeError:
                    fail('BASIC_PAGE_TEXT_INVALID')
            text = extracted_text_from_page(markdown)
            metrics = metrics_from_text(text, entry['image_count'], entry['parse_status'] == 'error')
            metrics['character_count'] = entry['character_count']
            metrics['low_text_density'] = entry['character_count']
            metrics['replacement_char_rate'] = (
                metrics['replacement_char_count'] / max(entry['character_count'], 1))
            # Phase 2B's explicit formula flag is authoritative routing evidence.
            metrics['formula_candidate'] = bool(entry['needs_formula_review'])
            score, route, reasons = score_and_route(metrics, profile)
            initial_state = ('encoding_degraded'
                             if metrics['font_encoding_warning']
                             and route != 'manual_or_optional_cloud_review'
                             else 'quality_scored')
            next_state = {
                'basic_accepted_candidate': 'review_required',
                'review_required': 'review_required',
                'enhanced_parse_queued': 'enhanced_queued',
                'manual_or_optional_cloud_review': 'blocked',
            }[route]
            transition_reason = ','.join(reasons) if reasons else 'basic_quality_normal_candidate'
            decisions.append({
                'source_id': source_id, 'page_number': page_number,
                'source_page': page_number, 'profile': profile_name,
                'basic_parser_id': 'basic_pymupdf',
                'basic_parser_version': report['parser_version'],
                'quality_score': score, 'metrics': metrics, 'route': route,
                'reasons': reasons, 'current_state': initial_state,
                'planned_state': next_state,
                'preferred_enhanced_parser': profile['preferred_enhanced_parser'] if route == 'enhanced_parse_queued' else None,
                'review_status': 'review_required',
                'planned_transition': {
                    'from': initial_state, 'to': next_state, 'timestamp': now_iso(),
                    'parser_id': 'basic_pymupdf', 'reason': transition_reason,
                    'source_id': source_id, 'page_number': page_number,
                },
                'basic_output_relative_path': self.manager.relative(page_path),
                'enhanced_output_relative_path': (
                    enhanced_output_path(source_id, page_number,
                                         profile['preferred_enhanced_parser'])
                    if route == 'enhanced_parse_queued' else None),
            })
        return validate_routing_plan({
            'schema_version': 1, 'plan_type': 'quality_routing_only',
            'source_id': source_id, 'source_sha256': record['sha256'],
            'profile': profile_name, 'created_at': now_iso(),
            'basic_output_layout': 'phase2b_legacy_flat_read_only',
            'future_output_root': f'vault/90-Parsed-Sources/{source_id}',
            'does_not_reparse': True, 'does_not_modify_existing_output': True,
            'automatic_knowledge_note_entry': False,
            'source_state': 'review_required',
            'source_transition': {
                'from': 'quality_scored', 'to': 'review_required',
                'timestamp': now_iso(), 'parser_id': 'basic_pymupdf',
                'reason': 'page_quality_routing_completed',
                'source_id': source_id, 'page_number': None,
            },
            'page_count': report['output_page_count'], 'decisions': decisions,
        })

    def save_plan(self, plan):
        validate_routing_plan(plan)
        relative = f'{ROUTING_QUEUE}/{plan["source_id"]}.json'
        self.manager.write_json(relative, plan)
        return relative

    def verify_plan(self, source_id):
        if not isinstance(source_id, str) or not SID.fullmatch(source_id):
            fail('SOURCE_ID_INVALID')
        relative = f'{ROUTING_QUEUE}/{source_id}.json'
        plan = validate_routing_plan(self.manager.load_json(relative, 8 * 1024 * 1024))
        record, report, _ = self._existing_report(source_id)
        if (plan['source_sha256'] != record['sha256']
                or plan['page_count'] != report['output_page_count']):
            fail('ROUTING_PLAN_SOURCE_MISMATCH')
        counts = {route: 0 for route in sorted(ROUTES)}
        for decision in plan['decisions']:
            counts[decision['route']] += 1
        return {'ok': True, 'source_id': source_id, 'page_count': plan['page_count'],
                'profile': plan['profile'], 'route_counts': counts}


def stable_plan_id(prefix, value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    return prefix + '-' + hashlib.sha256(encoded).hexdigest()[:16]


def chunks(values, size):
    return [values[index:index + size] for index in range(0, len(values), size)]


class BatchPlanner(RoutingPlanner):
    """Plan metadata-only batches. No method invokes a parser."""

    def _optional_json(self, relative, limit=8 * 1024 * 1024):
        path = self.manager.path(relative)
        if not path.exists():
            return None
        return self.manager.load_json(relative, limit)

    def _routing_plan(self, source_id):
        value = self._optional_json(f'{ROUTING_QUEUE}/{source_id}.json')
        return validate_routing_plan(value) if value is not None else None

    def _default_profile(self, record):
        if record['course'] == 'math1':
            return 'math1_formula_dense'
        return 'cs408_general'

    def _validate_filters(self, course=None, subject=None, source_type=None,
                          profile=None, source_ids=None):
        if course is not None and course not in VALID_COURSES:
            fail('FILTER_INVALID')
        if subject is not None and subject not in VALID_SUBJECTS:
            fail('FILTER_INVALID')
        if source_type is not None and source_type not in VALID_SOURCE_TYPES:
            fail('FILTER_INVALID')
        if profile is not None and profile not in self.profiles['profiles']:
            fail('PROFILE_NOT_FOUND')
        for source_id in source_ids or []:
            if not isinstance(source_id, str) or not SID.fullmatch(source_id):
                fail('SOURCE_ID_INVALID')

    def _selected(self, course=None, subject=None, source_type=None,
                  profile=None, source_ids=None):
        self._validate_filters(course, subject, source_type, profile, source_ids)
        integrity = self.manager.verify()
        if not integrity['ok']:
            fail('SOURCE_INTEGRITY_FAILED')
        records, issues = self.manager.manifests()
        if issues:
            fail('SOURCE_MANIFEST_INVALID')
        requested = set(source_ids or [])
        if requested - set(records):
            fail('SOURCE_NOT_REGISTERED')
        selected = []
        for source_id in sorted(records):
            record = records[source_id]
            if requested and source_id not in requested:
                continue
            if course is not None and record['course'] != course:
                continue
            if subject is not None and record['subject'] != subject:
                continue
            if source_type is not None and record['source_type'] != source_type:
                continue
            routing = self._routing_plan(source_id)
            if routing:
                effective_profile = routing['profile']
            elif profile is not None:
                candidate = self.profiles['profiles'][profile]
                if record['course'] != candidate['course'] or record['subject'] not in candidate['subjects']:
                    continue
                effective_profile = profile
            else:
                effective_profile = self._default_profile(record)
            if profile is not None and effective_profile != profile:
                continue
            selected.append((record, routing, effective_profile))
        return selected

    def source_status(self, **filters):
        selected = self._selected(**filters)
        sources = []
        for record, routing, profile in selected:
            counts = {route: 0 for route in sorted(ROUTES)}
            if routing:
                for decision in routing['decisions']:
                    counts[decision['route']] += 1
            sources.append({
                'source_id': record['source_id'], 'course': record['course'],
                'subject': record['subject'], 'source_type': record['source_type'],
                'file_type': record['file_type'], 'size_bytes': record['size_bytes'],
                'parser_status': record['parser_status'], 'page_count': record['page_count'],
                'parsing_profile': profile, 'routing_plan_present': routing is not None,
                'route_counts': counts,
            })
        return {'ok': True, 'read_only': True, 'source_count': len(sources),
                'sources': sources, 'unconfirmed_inbox_excluded': True}

    def _queue_documents(self):
        values = []
        for relative in self.manager.walk(JOB_QUEUE):
            if relative == JOB_QUEUE + '/.gitkeep':
                continue
            if PurePosixPath(relative).parent.as_posix() != JOB_QUEUE or not relative.endswith('.json'):
                fail('QUEUE_FILE_INVALID')
            value = self.manager.load_json(relative, 8 * 1024 * 1024)
            if value.get('document_type') not in {'batch_plan', 'single_page_retry'}:
                fail('QUEUE_FILE_INVALID')
            values.append((relative, value))
        return values

    def queue_status(self):
        by_type = {'batch_plan': 0, 'single_page_retry': 0}
        by_status = {}
        for _, value in self._queue_documents():
            by_type[value['document_type']] += 1
            status = value.get('status', 'unknown')
            by_status[status] = by_status.get(status, 0) + 1
        checkpoints = []
        for relative in self.manager.walk(CHECKPOINT_QUEUE):
            if relative != CHECKPOINT_QUEUE + '/.gitkeep':
                checkpoints.append(relative)
        return {'ok': True, 'read_only': True, 'queue_documents': sum(by_type.values()),
                'by_type': by_type, 'by_status': dict(sorted(by_status.items())),
                'checkpoint_files': len(checkpoints), 'max_concurrent_jobs': 1,
                'heavy_jobs_exclusive': True}

    def _retry_count(self):
        return sum(value.get('document_type') == 'single_page_retry'
                   for _, value in self._queue_documents())

    def _queued_task_keys(self):
        keys = set()
        for _, value in self._queue_documents():
            if value.get('status') not in {'planned', 'queued', 'running'}:
                continue
            if value['document_type'] == 'single_page_retry':
                keys.add((value.get('source_id'), value.get('page_number'), 'enhanced'))
                continue
            for batch in value.get('batches', []):
                category = batch.get('batch_type')
                for task in batch.get('tasks', []):
                    keys.add((task.get('source_id'), task.get('page_number'), category))
        return keys

    def _resource_estimate(self, selected, categories):
        planning = self.limits['planning']
        basic_pages = sum(1 for item in categories['basic']
                          if item.get('page_number') is not None
                          and item.get('requires_basic_parse'))
        unknown_basic_bytes = sum(
            item['size_bytes'] * 3 // 2 for item in categories['basic']
            if item.get('page_number') is None and item.get('requires_basic_parse'))
        enhanced_pages = sum(1 for item in categories['enhanced']
                             if item.get('page_number') is not None)
        estimated_disk = (basic_pages * planning['estimated_basic_bytes_per_page']
                          + unknown_basic_bytes
                          + enhanced_pages * planning['estimated_enhanced_bytes_per_page'])
        basic_tasks = sum(1 for item in categories['basic'] if item['requires_basic_parse'])
        peak_memory = 0
        peak_vram = 0
        if basic_tasks:
            peak_memory = planning['estimated_basic_peak_memory_bytes']
        if enhanced_pages:
            peak_memory = max(peak_memory, planning['estimated_enhanced_peak_memory_bytes'])
            peak_vram = planning['estimated_enhanced_peak_vram_bytes']
        known_pages = sum(record['page_count'] or 0 for record, _, _ in selected)
        return {
            'file_count': len(selected), 'known_page_count': known_pages,
            'unknown_page_count_files': sum(record['page_count'] is None
                                            for record, _, _ in selected),
            'basic_parse_task_count': basic_tasks,
            'enhanced_parse_task_count': enhanced_pages,
            'single_page_retry_task_count': self._retry_count(),
            'manual_review_page_count': len(categories['manual_review']),
            'resource_deferred_count': len(categories['resource_deferred']),
            'already_queued_count': len(categories['already_queued']),
            'unsupported_count': len(categories['unsupported']),
            'estimated_disk_increment_bytes': estimated_disk,
            'estimated_peak_memory_bytes': peak_memory,
            'estimated_peak_vram_bytes': peak_vram,
            'max_concurrent_jobs': self.limits['limits']['max_concurrent_jobs'],
            'exceeds_configured_memory_budget': peak_memory > self.limits['limits']['max_memory_bytes'],
            'exceeds_configured_vram_budget': peak_vram > self.limits['limits']['max_vram_bytes'],
            'exceeds_16gb_physical_memory': peak_memory > planning['hardware_memory_bytes'],
            'exceeds_8gb_physical_vram': peak_vram > planning['hardware_vram_bytes'],
            'estimation_notes': [
                'Unparsed PDFs have unknown page counts; disk uses 1.5x source size.',
                'Enhanced estimates are planning values only; no enhanced parser is installed.',
                'Peak estimates assume concurrency 1 and heavy-job exclusivity.',
            ],
        }

    def batch_plan(self, confirm_all_sources=False, **filters):
        scoped = any(value for value in (
            filters.get('course'), filters.get('subject'), filters.get('source_type'),
            filters.get('profile'), filters.get('source_ids')))
        if not scoped and not confirm_all_sources:
            fail('BATCH_SCOPE_CONFIRMATION_REQUIRED')
        selected = self._selected(**filters)
        categories = {name: [] for name in sorted(BATCH_CATEGORIES)}
        queued_keys = self._queued_task_keys()
        max_size = self.limits['limits']['max_single_file_size_bytes']
        for record, routing, profile in selected:
            common = {'source_id': record['source_id'], 'profile': profile,
                      'course': record['course'], 'subject': record['subject'],
                      'source_type': record['source_type']}
            if record['file_type'] != 'pdf':
                categories['unsupported'].append({**common, 'page_number': None,
                    'reason': 'phase2d0_pdf_only', 'file_type': record['file_type']})
                continue
            if record['size_bytes'] > max_size:
                categories['resource_deferred'].append({**common, 'page_number': None,
                    'reason': 'single_file_size_limit', 'size_bytes': record['size_bytes']})
                continue
            if record['parser_status'] == 'not_started':
                item = {**common, 'page_number': None,
                    'reason': 'basic_parse_not_started', 'size_bytes': record['size_bytes'],
                    'requires_basic_parse': True}
                target = ('already_queued' if (record['source_id'], None, 'basic') in queued_keys
                          else 'basic')
                if target == 'already_queued':
                    item['reason'] = 'matching_basic_task_already_queued'
                categories[target].append(item)
                continue
            if routing is None:
                categories['manual_review'].append({**common, 'page_number': None,
                    'reason': 'routing_plan_missing'})
                continue
            for decision in routing['decisions']:
                item = {**common, 'page_number': decision['page_number'],
                        'quality_score': decision['quality_score'],
                        'reason': ','.join(decision['reasons']) or 'quality_normal'}
                if decision['route'] == 'basic_accepted_candidate':
                    categories['basic'].append({**item, 'requires_basic_parse': False})
                elif decision['route'] == 'enhanced_parse_queued':
                    enhanced = {**item,
                        'parser_id': decision['preferred_enhanced_parser'],
                        'status': 'waiting_for_future_parser'}
                    target = ('already_queued'
                              if (record['source_id'], decision['page_number'], 'enhanced') in queued_keys
                              else 'enhanced')
                    if target == 'already_queued':
                        enhanced['reason'] = 'matching_enhanced_task_already_queued'
                    categories[target].append(enhanced)
                elif decision['route'] == 'review_required':
                    categories['manual_review'].append(item)
                else:
                    categories['unsupported'].append(item)
        limit = self.limits['planning']['default_batch_pages']
        basic_tasks = [item for item in categories['basic'] if item['requires_basic_parse']]
        enhanced_tasks = list(categories['enhanced'])
        batches = []
        # Unknown-page sources stay isolated so one source cannot silently exceed a batch.
        for item in basic_tasks:
            batches.append({'batch_type': 'basic', 'heavy': False,
                            'max_concurrent_jobs': 1, 'tasks': [item]})
        for group in chunks(enhanced_tasks, limit):
            batches.append({'batch_type': 'enhanced', 'heavy': True,
                            'max_concurrent_jobs': 1, 'tasks': group})
        filters_record = {key: filters.get(key) for key in
                          ('course', 'subject', 'source_type', 'profile')}
        filters_record['source_ids'] = sorted(filters.get('source_ids') or [])
        identity = {'filters': filters_record,
                    'sources': [record['source_id'] for record, _, _ in selected],
                    'routes': {key: len(value) for key, value in categories.items()}}
        result = {
            'schema_version': 1, 'document_type': 'batch_plan',
            'plan_id': stable_plan_id('batch', identity), 'created_at': now_iso(),
            'status': 'planned', 'dry_run': True, 'would_parse': False,
            'would_modify_originals': False, 'would_modify_existing_outputs': False,
            'unconfirmed_inbox_excluded': True, 'full_library_scope_confirmed': bool(confirm_all_sources),
            'filters': filters_record, 'source_count': len(selected),
            'default_max_pages_per_batch': limit, 'max_concurrent_jobs': 1,
            'heavy_jobs_exclusive': True, 'resume_supported': True,
            'single_page_retry_supported': True, 'categories': categories,
            'batches': batches,
        }
        result['resource_estimate'] = self._resource_estimate(selected, categories)
        return result

    def save_batch_plan(self, plan):
        if plan.get('document_type') != 'batch_plan' or plan.get('would_parse') is not False:
            fail('BATCH_PLAN_INVALID')
        relative = f'{JOB_QUEUE}/{plan["plan_id"]}.json'
        self.manager.write_json(relative, plan)
        return relative

    def retry_page(self, source_id, page_number, save=False):
        if not isinstance(source_id, str) or not SID.fullmatch(source_id):
            fail('SOURCE_ID_INVALID')
        if type(page_number) is not int or page_number < 1:
            fail('PAGE_IDENTITY_INVALID')
        if not self._selected(source_ids=[source_id]):
            fail('SOURCE_NOT_REGISTERED')
        plan = self._routing_plan(source_id)
        if plan is None or page_number > plan['page_count']:
            fail('ROUTING_PLAN_REQUIRED')
        decision = plan['decisions'][page_number - 1]
        checkpoint_relative = f'{CHECKPOINT_QUEUE}/{source_id}-page-{page_number:04d}.json'
        checkpoint = self._optional_json(checkpoint_relative)
        if checkpoint is None:
            fail('RETRY_CHECKPOINT_REQUIRED')
        required = {'schema_version', 'source_id', 'page_number', 'status',
                    'retry_count', 'parser_id', 'error_code', 'updated_at'}
        if (set(checkpoint) != required or checkpoint['schema_version'] != 1
                or checkpoint['source_id'] != source_id
                or checkpoint['page_number'] != page_number
                or checkpoint['status'] != 'failed'
                or type(checkpoint['retry_count']) is not int
                or checkpoint['retry_count'] < 0
                or not isinstance(checkpoint['error_code'], str)
                or not re.fullmatch(r'[A-Z][A-Z0-9_]{2,63}', checkpoint['error_code'])
                or not timezone_iso(checkpoint['updated_at'])):
            fail('CHECKPOINT_INVALID')
        parser_id = decision['preferred_enhanced_parser'] or 'basic_pymupdf'
        task = PageStateMachine(source_id, page_number, 'failed').retry_task(
            parser_id, checkpoint['error_code'], checkpoint['retry_count'],
            self.limits['limits']['max_retry_count_per_page'])
        identity = {'source_id': source_id, 'page_number': page_number,
                    'retry_count': task['retry_count']}
        result = {'schema_version': 1, 'document_type': 'single_page_retry',
                  'job_id': stable_plan_id('retry', identity), 'created_at': now_iso(),
                  'status': 'planned', 'dry_run': not save, 'would_parse': False,
                  'preserve_basic_output': True, **task}
        if save:
            relative = f'{JOB_QUEUE}/{result["job_id"]}.json'
            self.manager.write_json(relative, result)
            result = {**result, 'saved_relative_path': relative}
        return result

    def resume_check(self, source_id=None):
        if source_id is not None and not SID.fullmatch(source_id):
            fail('SOURCE_ID_INVALID')
        statuses = {'completed': 0, 'failed': 0, 'pending': 0}
        pages = []
        for relative in self.manager.walk(CHECKPOINT_QUEUE):
            if relative == CHECKPOINT_QUEUE + '/.gitkeep':
                continue
            value = self.manager.load_json(relative)
            if source_id is not None and value.get('source_id') != source_id:
                continue
            status = value.get('status')
            bucket = 'completed' if status == 'completed' else ('failed' if status == 'failed' else 'pending')
            statuses[bucket] += 1
            pages.append({'source_id': value.get('source_id'),
                          'page_number': value.get('page_number'), 'status': status})
        return {'ok': True, 'read_only': True, 'source_id': source_id,
                'checkpoint_counts': statuses, 'pages': pages,
                'resume_from_last_verified_page': True,
                'whole_library_rerun_allowed': False}


def cli(argv=None):
    parser = argparse.ArgumentParser(
        description='Phase 2C quality routing and Phase 2D-0 metadata-only batch planning.')
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('validate-config', help='Validate parsing profiles and resource limits')
    check.set_defaults(command='validate-config')
    plan = sub.add_parser('plan-source', help='Plan page routing from an existing verified basic output')
    plan.add_argument('source_id')
    plan.add_argument('--profile', required=True)
    plan.add_argument('--save', action='store_true', help='Save one non-content routing plan')
    verify = sub.add_parser('verify-plan', help='Validate a saved routing plan against its source')
    verify.add_argument('source_id')

    def add_filters(command, allow_save=False):
        command.add_argument('--source-id', action='append', dest='source_ids')
        command.add_argument('--course')
        command.add_argument('--subject')
        command.add_argument('--source-type')
        command.add_argument('--profile')
        if allow_save:
            command.add_argument('--save', action='store_true',
                                 help='Save metadata-only plan; never starts parsing')

    source_status = sub.add_parser('source-status', help='Show registered source planning status')
    add_filters(source_status)
    batch = sub.add_parser('batch-plan', help='Create a dry-run batch plan; never parses')
    add_filters(batch, allow_save=True)
    batch.add_argument('--confirm-all-sources', action='store_true',
                       help='Explicitly allow an unfiltered whole-library planning view')
    queue = sub.add_parser('queue-status', help='Read local plan/retry queue metadata')
    queue.set_defaults(command='queue-status')
    estimate = sub.add_parser('estimate-resources', help='Estimate a dry-run batch resource envelope')
    add_filters(estimate)
    estimate.add_argument('--confirm-all-sources', action='store_true')
    retry = sub.add_parser('retry-page', help='Plan one failed page retry without parsing')
    retry.add_argument('source_id')
    retry.add_argument('page_number', type=int)
    retry.add_argument('--save', action='store_true',
                       help='Save retry metadata only; never invokes a parser')
    resume = sub.add_parser('resume-check', help='Read checkpoints for safe resume planning')
    resume.add_argument('--source-id')
    args = parser.parse_args(argv)
    try:
        planner = BatchPlanner()
        if args.command == 'validate-config':
            result = {'ok': True, 'profiles': sorted(planner.profiles['profiles']),
                      'max_concurrent_jobs': planner.limits['limits']['max_concurrent_jobs']}
        elif args.command == 'plan-source':
            result = planner.plan_existing(args.source_id, args.profile)
            if args.save:
                result = {'saved': True, 'plan_path': planner.save_plan(result),
                          'source_id': result['source_id'], 'page_count': result['page_count']}
        elif args.command == 'verify-plan':
            result = planner.verify_plan(args.source_id)
        elif args.command == 'source-status':
            result = planner.source_status(
                course=args.course, subject=args.subject, source_type=args.source_type,
                profile=args.profile, source_ids=args.source_ids)
        elif args.command == 'batch-plan':
            result = planner.batch_plan(
                confirm_all_sources=args.confirm_all_sources, course=args.course,
                subject=args.subject, source_type=args.source_type,
                profile=args.profile, source_ids=args.source_ids)
            if args.save:
                result = {**result, 'saved_relative_path': planner.save_batch_plan(result)}
        elif args.command == 'queue-status':
            result = planner.queue_status()
        elif args.command == 'estimate-resources':
            plan_result = planner.batch_plan(
                confirm_all_sources=args.confirm_all_sources, course=args.course,
                subject=args.subject, source_type=args.source_type,
                profile=args.profile, source_ids=args.source_ids)
            result = {'ok': True, 'dry_run': True, 'filters': plan_result['filters'],
                      'resource_estimate': plan_result['resource_estimate']}
        elif args.command == 'retry-page':
            result = planner.retry_page(args.source_id, args.page_number, args.save)
        else:
            result = planner.resume_check(args.source_id)
        print(json_bytes(result).decode('utf-8'), end='')
        return 0
    except ArchitectureError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
    except SourceError as exc:
        print(json.dumps({'ok': False, 'error': 'SOURCE_' + str(exc)}))
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print(json.dumps({'ok': False, 'error': 'IO_OR_INPUT_ERROR'}))
    return 1


if __name__ == '__main__':
    sys.exit(cli())
