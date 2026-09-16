"""Phase 2C architecture: parser contracts, quality routing and traceable states.

Only the PyMuPDF adapter is implemented. Enhanced/cloud adapters are inert
interfaces. The CLI reads existing Phase 2B outputs and can save one routing
plan; it never reparses or mutates originals or existing parsed output.
"""
from abc import ABC, abstractmethod
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
PARSER_IDS = {
    'basic_pymupdf', 'enhanced_mineru_pipeline',
    'enhanced_docling_formula', 'optional_mathpix_formula_crop',
}
ROUTES = {
    'basic_accepted_candidate', 'review_required', 'enhanced_parse_queued',
    'manual_or_optional_cloud_review',
}
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
                     'checkpoint_relative_path', 'limits', 'execution'}:
        fail('LIMIT_SCHEMA_INVALID')
    if value['schema_version'] != 1 or Path(value['project_root_constraint']) != root:
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
                    'enhanced_mineru_pipeline', 'enhanced_docling_formula'}
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
            initial_state = 'encoding_degraded' if metrics['font_encoding_warning'] else 'quality_scored'
            next_state = {
                'basic_accepted_candidate': 'review_required',
                'review_required': 'review_required',
                'enhanced_parse_queued': 'enhanced_queued',
                'manual_or_optional_cloud_review': 'manual_correction_pending',
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
                    f'vault/90-Parsed-Sources/{source_id}/enhanced/mineru/page-{page_number:04d}.json'
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


def cli(argv=None):
    parser = argparse.ArgumentParser(description='Phase 2C read-only quality routing architecture.')
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('validate-config', help='Validate parsing profiles and resource limits')
    check.set_defaults(command='validate-config')
    plan = sub.add_parser('plan-source', help='Plan page routing from an existing verified basic output')
    plan.add_argument('source_id')
    plan.add_argument('--profile', required=True)
    plan.add_argument('--save', action='store_true', help='Save one non-content routing plan')
    verify = sub.add_parser('verify-plan', help='Validate a saved routing plan against its source')
    verify.add_argument('source_id')
    args = parser.parse_args(argv)
    try:
        planner = RoutingPlanner()
        if args.command == 'validate-config':
            result = {'ok': True, 'profiles': sorted(planner.profiles['profiles']),
                      'max_concurrent_jobs': planner.limits['limits']['max_concurrent_jobs']}
        elif args.command == 'plan-source':
            result = planner.plan_existing(args.source_id, args.profile)
            if args.save:
                result = {'saved': True, 'plan_path': planner.save_plan(result),
                          'source_id': result['source_id'], 'page_count': result['page_count']}
        else:
            result = planner.verify_plan(args.source_id)
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
