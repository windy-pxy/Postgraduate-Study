"""Phase 2A: local, conservative, copy-only source registration (standard library).

This module never extracts document text or contacts a network. CLI roots are fixed
to the project; constructor overrides are restricted to its subtree for tests.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import sys
import unicodedata
import uuid
import xml.etree.ElementTree as ET
import zipfile

PROJECT_ROOT = Path(__file__).absolute().parent.parent
SUBJECTS = {
    'math1': {'calculus', 'linear-algebra', 'probability'},
    '408': {'data-structure', 'computer-organization', 'operating-system', 'computer-network'},
}
SOURCE_TYPES = {'textbook', 'wangdao', 'zhangyu', 'teacher-ppt', 'past-paper', 'exercise', 'notes', 'other'}
FORMATS = {'pdf', 'pptx', 'docx'}
BASELINE = 'config/sources-original.baseline.json'
MANIFESTS = 'config/source-manifests'
PLANS = 'review-queue/import-plans'
PLACEHOLDERS = {'math1/.gitkeep', '408/.gitkeep'}
HEX = re.compile(r'[0-9a-f]{64}')
SID = re.compile(r'src-[0-9a-f]{12,64}')
MANIFEST_FIELDS = {
    'schema_version', 'source_id', 'sha256', 'original_filename', 'stored_relative_path',
    'file_type', 'size_bytes', 'course', 'subject', 'source_type', 'classification_status',
    'import_status', 'imported_at', 'parser_status', 'parser_name', 'parser_version', 'page_count',
    'parsed_at', 'parsed_output_relative_path', 'parse_review_status', 'notes',
}


class SourceError(Exception):
    """Only constant error codes cross the CLI boundary; never raw exceptions."""


def fail(code):
    raise SourceError(code)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def iso_time(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
        return 'T' in value and parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail('JSON_DUPLICATE_KEY')
        result[key] = value
    return result


def sanitized_filename(name):
    name = unicodedata.normalize('NFKC', name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', name)
    name = re.sub(r'\.{2,}', '_', name).strip(' .')
    if not name:
        fail('FILENAME_INVALID')
    base, ext = os.path.splitext(name)
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', base):
        base = '_' + base
    return base[:160] + ext[:12]


def classify(course, subject, source_type, complete=False):
    if course is not None and (not isinstance(course, str) or course not in SUBJECTS):
        fail('COURSE_INVALID')
    if subject is not None and (not isinstance(subject, str) or subject not in set().union(*SUBJECTS.values())):
        fail('SUBJECT_INVALID')
    if course is not None and subject is not None and subject not in SUBJECTS[course]:
        fail('SUBJECT_COURSE_MISMATCH')
    if source_type is not None and (not isinstance(source_type, str) or source_type not in SOURCE_TYPES):
        fail('SOURCE_TYPE_INVALID')
    if complete and None in (course, subject, source_type):
        fail('CLASSIFICATION_REQUIRED')
    return {'course': course, 'subject': subject, 'source_type': source_type}


def source_id(digest, occupied):
    if not isinstance(digest, str) or not HEX.fullmatch(digest):
        fail('HASH_INVALID')
    for sid, existing in occupied.items():
        if existing == digest:
            return sid
    for length in range(12, 65):
        candidate = 'src-' + digest[:length]
        if candidate not in occupied:
            return candidate
    fail('SOURCE_ID_COLLISION')


class SourceManager:
    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root).absolute()
        try:
            relative = self.root.relative_to(PROJECT_ROOT)
        except ValueError:
            fail('ROOT_OUTSIDE_PROJECT')
        current = PROJECT_ROOT
        self._metadata(current)
        for part in relative.parts:
            current /= part
            self._metadata(current)

    @staticmethod
    def _metadata(path):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            fail('LINK_OR_REPARSE_POINT')
        if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
            fail('NONREGULAR_FILE')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            fail('HARDLINK_REFUSED')
        return info

    def path(self, relative, area=None):
        if not isinstance(relative, str) or not relative or PureWindowsPath(relative).drive or PureWindowsPath(relative).root:
            fail('PATH_OUTSIDE_PROJECT')
        parts = relative.replace('\\', '/').split('/')
        if any(p in ('', '.', '..', '.git', '.obsidian') or re.search(r'[<>:"|?*\x00-\x1f\x7f]', p)
               or p.endswith((' ', '.')) or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', p.split('.')[0]) for p in parts):
            fail('PATH_INVALID')
        if area and parts[:len(area.split('/'))] != area.split('/'):
            fail('PATH_WRONG_AREA')
        current = self.root
        self._metadata(current)
        for part in parts:
            current /= part
            try:
                self._metadata(current)
            except FileNotFoundError:
                pass
        return current

    def relative(self, path):
        return path.relative_to(self.root).as_posix()

    @contextmanager
    def reader(self, relative):
        path = self.path(relative)
        before = self._metadata(path)
        if not stat.S_ISREG(before.st_mode):
            fail('FILE_REQUIRED')
        with path.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino) or opened.st_nlink != 1:
                fail('FILE_CHANGED_DURING_OPEN')
            yield stream
            after = self._metadata(self.path(relative))
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                fail('FILE_CHANGED_DURING_READ')

    def digest(self, relative):
        h = hashlib.sha256()
        size = 0
        with self.reader(relative) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(block)
                size += len(block)
        return h.hexdigest(), size

    def inspect(self, relative):
        before = self._metadata(self.path(relative))
        kind = self.detect(relative)
        digest, size = self.digest(relative)
        after = self._metadata(self.path(relative))
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            fail('FILE_CHANGED_DURING_INSPECTION')
        return kind, digest, size

    def load_json(self, relative, max_bytes=1024 * 1024):
        with self.reader(relative) as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            fail('JSON_TOO_LARGE')
        try:
            value = json.loads(data, object_pairs_hook=strict_object,
                               parse_constant=lambda _: fail('JSON_NONFINITE'))
        except (ValueError, UnicodeError, RecursionError):
            fail('JSON_INVALID')
        if not isinstance(value, dict):
            fail('JSON_OBJECT_REQUIRED')
        return value

    def walk(self, area):
        base = self.path(area)
        if not base.is_dir():
            fail('DIRECTORY_REQUIRED')
        found = []
        def descend(folder):
            for child in sorted(folder.iterdir()):
                info = self._metadata(child)
                if stat.S_ISDIR(info.st_mode):
                    descend(child)
                else:
                    found.append(self.relative(child))
        descend(base)
        return found

    def detect(self, relative):
        path = self.path(relative)
        kind = path.suffix.lower().lstrip('.')
        if kind not in FORMATS:
            fail('UNSUPPORTED')
        with self.reader(relative) as stream:
            if kind == 'pdf':
                if stream.read(5) != b'%PDF-':
                    fail('SIGNATURE_MISMATCH')
                return kind
            try:
                with zipfile.ZipFile(stream) as package:
                    entries = package.infolist()
                    names = [entry.filename for entry in entries]
                    if len(entries) > 10000 or len({n.casefold() for n in names}) != len(names):
                        fail('OFFICE_STRUCTURE_INVALID')
                    for entry in entries:
                        n = entry.filename.rstrip('/')
                        if (not n or PureWindowsPath(n).drive or n.startswith('/') or '\\' in n
                                or any(p in ('', '.', '..') for p in n.split('/'))
                                or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16)):
                            fail('OFFICE_STRUCTURE_INVALID')
                    main = 'word/document.xml' if kind == 'docx' else 'ppt/presentation.xml'
                    other = 'ppt/presentation.xml' if kind == 'docx' else 'word/document.xml'
                    if not {'[Content_Types].xml', '_rels/.rels', main}.issubset(names) or other in names:
                        fail('SIGNATURE_MISMATCH')
                    roots = []
                    for name in ('[Content_Types].xml', '_rels/.rels'):
                        if package.getinfo(name).file_size > 1024 * 1024:
                            fail('OFFICE_METADATA_TOO_LARGE')
                        data = package.read(name)
                        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                            fail('OFFICE_XML_UNSAFE')
                        roots.append(ET.fromstring(data))
                    mime = ('application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
                            if kind == 'docx' else 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml')
                    ns = '{http://schemas.openxmlformats.org/package/2006/content-types}'
                    relns = '{http://schemas.openxmlformats.org/package/2006/relationships}'
                    if roots[0].tag != ns + 'Types' or roots[1].tag != relns + 'Relationships':
                        fail('OFFICE_STRUCTURE_INVALID')
                    if not any(e.get('PartName') == '/' + main and e.get('ContentType') == mime for e in roots[0].findall(ns + 'Override')):
                        fail('SIGNATURE_MISMATCH')
                    relationship_types = {
                        'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument',
                        'http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument',
                    }
                    if not any(e.get('Target', '').lstrip('/') == main and e.get('Type') in relationship_types
                               and e.get('TargetMode', 'Internal') == 'Internal' for e in roots[1].findall(relns + 'Relationship')):
                        fail('OFFICE_STRUCTURE_INVALID')
            except (zipfile.BadZipFile, ET.ParseError, KeyError, RuntimeError, NotImplementedError):
                fail('OFFICE_CONTAINER_INVALID')
        return kind

    def validate_manifest(self, value, filename):
        if set(value) != MANIFEST_FIELDS or type(value['schema_version']) is not int or value['schema_version'] != 1:
            fail('MANIFEST_SCHEMA_INVALID')
        sid, digest = value['source_id'], value['sha256']
        if (not isinstance(sid, str) or not SID.fullmatch(sid) or filename != sid + '.json'
                or not isinstance(digest, str) or not HEX.fullmatch(digest) or not digest.startswith(sid[4:])):
            fail('MANIFEST_ID_INVALID')
        classify(value['course'], value['subject'], value['source_type'], complete=True)
        name = value['original_filename']
        if not isinstance(name, str) or not name or '/' in name or '\\' in name or ':' in name:
            fail('MANIFEST_FILENAME_INVALID')
        stored = f"sources-original/{value['course']}/{value['subject']}/{sid}/{sanitized_filename(name)}"
        if value['stored_relative_path'] != stored:
            fail('MANIFEST_PATH_INVALID')
        self.path(stored, 'sources-original')
        if not isinstance(value['file_type'], str) or value['file_type'] not in FORMATS or Path(name).suffix.lower() != '.' + value['file_type']:
            fail('MANIFEST_TYPE_INVALID')
        if type(value['size_bytes']) is not int or value['size_bytes'] <= 0:
            fail('MANIFEST_SIZE_INVALID')
        if (value['classification_status'] != 'confirmed' or value['import_status'] != 'imported'
                or value['parser_status'] not in {'not_started', 'parsed'}
                or not iso_time(value['imported_at']) or not isinstance(value['notes'], str)):
            fail('MANIFEST_STATUS_INVALID')
        parser_fields = ('parser_name', 'parser_version', 'page_count', 'parsed_at',
                         'parsed_output_relative_path', 'parse_review_status')
        if value['parser_status'] == 'not_started':
            if any(value[k] is not None for k in parser_fields):
                fail('MANIFEST_STATUS_INVALID')
        else:
            output = f"vault/90-Parsed-Sources/{sid}"
            if (not isinstance(value['parser_name'], str) or not value['parser_name']
                    or not isinstance(value['parser_version'], str) or not value['parser_version']
                    or type(value['page_count']) is not int or value['page_count'] < 1
                    or not iso_time(value['parsed_at'])
                    or value['parsed_output_relative_path'] != output
                    or value['parse_review_status'] != 'review_required'):
                fail('MANIFEST_STATUS_INVALID')
            self.path(output, 'vault/90-Parsed-Sources')

    def manifests(self):
        records, issues = {}, []
        for relative in self.walk(MANIFESTS):
            if relative == MANIFESTS + '/.gitkeep':
                continue
            try:
                if Path(relative).parent.as_posix() != MANIFESTS or not relative.endswith('.json'):
                    fail('MANIFEST_UNEXPECTED_FILE')
                value = self.load_json(relative)
                self.validate_manifest(value, Path(relative).name)
                records[value['source_id']] = value
            except (SourceError, OSError) as exc:
                issues.append({'path': relative, 'error': str(exc) if isinstance(exc, SourceError) else 'IO_ERROR'})
        return records, issues

    @staticmethod
    def anchor(record):
        return {k: record[k] for k in ('sha256', 'stored_relative_path', 'size_bytes')}

    def verify(self):
        records, issues = self.manifests()
        hashes, paths = {}, set()
        for sid, record in records.items():
            path, digest = record['stored_relative_path'], record['sha256']
            if digest in hashes:
                issues.append({'path': MANIFESTS + '/' + sid + '.json', 'error': 'HASH_CONFLICT'})
            hashes[digest] = sid
            if path in paths:
                issues.append({'path': path, 'error': 'PATH_CONFLICT'})
            paths.add(path)
            try:
                kind, actual, size = self.inspect(path)
                if actual != digest:
                    fail('HASH_MISMATCH')
                if size != record['size_bytes']:
                    fail('SIZE_MISMATCH')
                if kind != record['file_type']:
                    fail('SIGNATURE_MISMATCH')
            except (SourceError, OSError) as exc:
                issues.append({'path': path, 'error': str(exc) if isinstance(exc, SourceError) else 'ORIGINAL_MISSING_OR_UNREADABLE'})
            output = f'vault/90-Parsed-Sources/{sid}'
            output_path = self.path(output, 'vault/90-Parsed-Sources')
            if record['parser_status'] == 'not_started':
                if output_path.exists():
                    issues.append({'path': output, 'error': 'PARSE_STATE_CONFLICT'})
            else:
                try:
                    if record['parsed_output_relative_path'] != output or not output_path.is_dir():
                        fail('PARSED_OUTPUT_MISSING')
                    report = self.load_json(output + '/parse-report.json', 32 * 1024 * 1024)
                    if (report.get('source_id') != sid or report.get('source_sha256') != digest
                            or report.get('parser_name') != record['parser_name']
                            or report.get('parser_version') != record['parser_version']
                            or report.get('parsed_at') != record['parsed_at']
                            or report.get('declared_page_count') != record['page_count']
                            or report.get('output_page_count') != record['page_count']
                            or report.get('review_status') != record['parse_review_status']
                            or report.get('derived') is not True):
                        fail('PARSE_MANIFEST_REPORT_CONFLICT')
                except (SourceError, OSError) as exc:
                    issues.append({'path': output, 'error': str(exc) if isinstance(exc, SourceError) else 'PARSED_OUTPUT_MISSING_OR_UNREADABLE'})
        originals = self.walk('sources-original')
        for path in originals:
            rel = path.removeprefix('sources-original/')
            if rel in PLACEHOLDERS and self.path(path).stat().st_size == 0:
                continue
            if path not in paths:
                issues.append({'path': path, 'error': 'UNREGISTERED_ORIGINAL'})
        baseline = self.load_json(BASELINE)
        if (set(baseline) != {'schema_version', 'algorithm', 'sources'} or type(baseline.get('schema_version')) is not int
                or baseline.get('schema_version') != 2 or baseline.get('algorithm') != 'sha256'
                or not isinstance(baseline.get('sources'), dict)):
            fail('BASELINE_SCHEMA_INVALID')
        for sid, anchor in baseline['sources'].items():
            if sid not in records:
                issues.append({'path': BASELINE, 'error': 'BASELINE_SOURCE_MISSING'})
            elif anchor != self.anchor(records[sid]):
                issues.append({'path': BASELINE, 'error': 'BASELINE_CONFLICT'})
        return {'ok': not issues, 'issues': issues, 'registered_count': len(records),
                'baseline_pending': sorted(set(records) - set(baseline['sources']))}

    def require_clean(self):
        report = self.verify()
        if not report['ok']:
            fail('INTEGRITY_ERRORS_BLOCK_OPERATION')
        return report

    def scan(self):
        self.require_clean()
        records, _ = self.manifests()
        known = {r['sha256']: sid for sid, r in records.items()}
        seen, output = {}, []
        for relative in self.walk('import-inbox'):
            if relative == 'import-inbox/.gitkeep':
                continue
            item = {'relative_path': relative}
            try:
                kind, digest, size = self.inspect(relative)
                item.update(file_type=kind, sha256=digest, size_bytes=size)
                if digest in known or digest in seen:
                    item.update(status='duplicate', duplicate_of=known.get(digest, seen.get(digest)))
                else:
                    item.update(status='needs_review', classification_status='suggested',
                                suggested={'course': None, 'subject': None, 'source_type': None})
                seen[digest] = relative
            except (SourceError, OSError) as exc:
                error = str(exc) if isinstance(exc, SourceError) else 'IO_ERROR'
                item.update(status='unsupported' if error == 'UNSUPPORTED' else 'invalid', error=error)
            output.append(item)
        return output

    def _mkdir(self, relative, exclusive=False):
        path = self.path(relative)
        path.mkdir(exist_ok=not exclusive)
        self.path(relative)
        return path

    @contextmanager
    def lock(self):
        relative = 'config/.source-manager.lock'
        path = self.path(relative)
        try:
            stream = path.open('xb')
        except FileExistsError:
            fail('MANAGER_LOCKED')
        identity = os.fstat(stream.fileno())
        try:
            with stream:
                stream.write(b'Phase 2A operation lock\n')
                stream.flush()
                os.fsync(stream.fileno())
            yield
        finally:
            self._remove_owned(path, identity)

    def _remove_owned(self, path, identity):
        """Only exact temporary inodes created by this invocation may be removed."""
        try:
            current = self._metadata(self.path(self.relative(path)))
            if (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino):
                fail('TEMP_IDENTITY_CHANGED')
            path.unlink()
        except FileNotFoundError:
            pass

    def _publish(self, temporary, destination):
        self.path(self.relative(temporary))
        self.path(self.relative(destination))
        if os.name == 'nt':
            # Windows rename fails if destination exists; no replace flag.
            os.rename(temporary, destination)
        else:
            # Atomic no-clobber publication for a same-directory regular file.
            os.link(temporary, destination)
            temporary.unlink()

    def write_json(self, relative, value, replace_baseline=False):
        destination = self.path(relative)
        if replace_baseline and relative != BASELINE:
            fail('REPLACE_FORBIDDEN')
        if not replace_baseline and destination.exists():
            fail('TARGET_EXISTS')
        temporary = self.path(self.relative(destination.parent / ('.' + uuid.uuid4().hex + '.tmp')))
        with temporary.open('xb') as stream:
            identity = os.fstat(stream.fileno())
            try:
                stream.write(json_bytes(value))
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                stream.close()
                self._remove_owned(temporary, identity)
                raise
        try:
            if replace_baseline:
                self.path(relative)
                os.replace(temporary, destination)
            else:
                self._publish(temporary, destination)
        finally:
            self._remove_owned(temporary, identity)

    def mark_parsed(self, original, parser_name, parser_version, page_count, parsed_at, output_relative_path):
        """Atomically change only reserved parser fields after output publication."""
        sid = original.get('source_id') if isinstance(original, dict) else None
        if not isinstance(sid, str) or not SID.fullmatch(sid):
            fail('MANIFEST_ID_INVALID')
        relative = MANIFESTS + '/' + sid + '.json'
        destination = self.path(relative, MANIFESTS)
        current = self.load_json(relative)
        self.validate_manifest(current, destination.name)
        if current != original or current['parser_status'] != 'not_started':
            fail('MANIFEST_CHANGED_OR_ALREADY_PARSED')
        updated = dict(current)
        updated.update(parser_status='parsed', parser_name=parser_name, parser_version=parser_version,
                       page_count=page_count, parsed_at=parsed_at,
                       parsed_output_relative_path=output_relative_path,
                       parse_review_status='review_required')
        self.validate_manifest(updated, destination.name)
        before = self._metadata(destination)
        temporary = self.path(self.relative(destination.parent / ('.' + uuid.uuid4().hex + '.tmp')))
        with temporary.open('xb') as stream:
            identity = os.fstat(stream.fileno())
            try:
                stream.write(json_bytes(updated))
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                stream.close()
                self._remove_owned(temporary, identity)
                raise
        try:
            after = self._metadata(destination)
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    or self.load_json(relative) != current):
                fail('MANIFEST_CHANGED_DURING_UPDATE')
            os.replace(temporary, destination)
        finally:
            self._remove_owned(temporary, identity)
        return updated

    def plan(self, relative, course=None, subject=None, source_type=None, save=False):
        self.require_clean()
        path = self.path(relative, 'import-inbox')
        relative = self.relative(path)
        classification = classify(course, subject, source_type)
        kind, digest, size = self.inspect(relative)
        records, _ = self.manifests()
        occupied = {sid: r['sha256'] for sid, r in records.items()}
        if digest in occupied.values():
            fail('DUPLICATE_SOURCE')
        sid = source_id(digest, occupied)
        complete = all(v is not None for v in classification.values())
        target = f'sources-original/{course}/{subject}/{sid}/{sanitized_filename(path.name)}' if complete else None
        if target:
            self.path(target)
        plan = {
            'schema_version': 1, 'plan_id': 'plan-' + uuid.uuid4().hex,
            'input_relative_path': relative, 'sha256': digest, 'size_bytes': size,
            'file_type': kind, 'source_id': sid, 'classification': classification,
            'suggested': {k: {'value': None, 'status': 'suggested', 'basis': 'not_inferred'} for k in classification},
            'confirmed_fields': sorted(k for k, v in classification.items() if v is not None),
            'target_relative_path': target, 'warnings': [] if complete else ['CLASSIFICATION_REQUIRED'],
            'created_at': utc_now(), 'status': 'ready' if complete else 'needs_review',
        }
        if save:
            with self.lock():
                self.require_clean()
                self.write_json(PLANS + '/' + plan['plan_id'] + '.json', plan)
        return {'dry_run': not save, 'plan_path': PLANS + '/' + plan['plan_id'] + '.json' if save else None, 'plan': plan}

    def checked_plan(self, relative):
        plan_path = self.path(relative, PLANS)
        plan = self.load_json(self.relative(plan_path))
        required = {'schema_version', 'plan_id', 'input_relative_path', 'sha256', 'size_bytes', 'file_type',
                    'source_id', 'classification', 'suggested', 'confirmed_fields', 'target_relative_path', 'warnings', 'created_at', 'status'}
        if (set(plan) != required or plan.get('schema_version') != 1 or not isinstance(plan.get('plan_id'), str)
                or not re.fullmatch(r'plan-[0-9a-f]{32}', plan['plan_id']) or plan_path.name != plan['plan_id'] + '.json'
                or plan['status'] != 'ready' or not iso_time(plan['created_at'])):
            fail('PLAN_INVALID_OR_NEEDS_REVIEW')
        c = plan['classification']
        if not isinstance(c, dict) or set(c) != {'course', 'subject', 'source_type'}:
            fail('CLASSIFICATION_REQUIRED')
        classify(**c, complete=True)
        if plan['confirmed_fields'] != sorted(c):
            fail('CLASSIFICATION_NOT_CONFIRMED')
        path = self.path(plan['input_relative_path'], 'import-inbox')
        kind, digest, size = self.inspect(self.relative(path))
        if digest != plan['sha256'] or size != plan['size_bytes'] or kind != plan['file_type']:
            fail('INBOX_CHANGED')
        records, _ = self.manifests()
        occupied = {sid: r['sha256'] for sid, r in records.items()}
        if digest in occupied.values():
            fail('DUPLICATE_SOURCE')
        sid = source_id(digest, occupied)
        if sid != plan['source_id']:
            fail('PLAN_ID_STALE')
        target = f"sources-original/{c['course']}/{c['subject']}/{sid}/{sanitized_filename(path.name)}"
        if plan['target_relative_path'] != target:
            fail('PLAN_TARGET_INVALID')
        destination = self.path(target, 'sources-original')
        if destination.parent.exists() or self.path(MANIFESTS + '/' + sid + '.json').exists():
            fail('TARGET_EXISTS')
        return plan, path, destination

    def _copy(self, relative, stream):
        with self.reader(relative) as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                stream.write(block)

    def apply(self, relative, execute=False):
        self.require_clean()
        plan, source, destination = self.checked_plan(relative)
        if not execute:
            return {'dry_run': True, 'source_id': plan['source_id'], 'target_relative_path': plan['target_relative_path']}
        with self.lock():
            self.require_clean()
            plan, source, destination = self.checked_plan(relative)
            created_dirs = []
            temporary = None
            try:
                subject_dir = destination.parent.parent
                if not subject_dir.exists():
                    created = self._mkdir(self.relative(subject_dir), exclusive=True)
                    created_dirs.append((created, self._metadata(created)))
                created = self._mkdir(self.relative(destination.parent), exclusive=True)
                created_dirs.append((created, self._metadata(created)))
                temporary = self.path(self.relative(destination.parent / ('.' + uuid.uuid4().hex + '.tmp')))
                with temporary.open('xb') as stream:
                    identity = os.fstat(stream.fileno())
                    self._copy(self.relative(source), stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                actual, size = self.digest(self.relative(temporary))
                if actual != plan['sha256'] or size != plan['size_bytes']:
                    fail('COPY_HASH_MISMATCH')
                # Check inbox again after copying; it must remain the planned file.
                if self.digest(self.relative(source)) != (actual, size):
                    fail('INBOX_CHANGED')
                self._publish(temporary, destination)
                c = plan['classification']
                manifest = dict(schema_version=1, source_id=plan['source_id'], sha256=actual,
                                original_filename=source.name, stored_relative_path=self.relative(destination),
                                file_type=plan['file_type'], size_bytes=size, **c,
                                classification_status='confirmed', import_status='imported', imported_at=utc_now(),
                                parser_status='not_started', parser_name=None, parser_version=None, page_count=None, notes='')
                manifest.update(parsed_at=None, parsed_output_relative_path=None, parse_review_status=None)
                self.validate_manifest(manifest, plan['source_id'] + '.json')
                self.write_json(MANIFESTS + '/' + plan['source_id'] + '.json', manifest)
                return {'dry_run': False, 'source_id': plan['source_id'], 'import_status': 'imported', 'baseline_status': 'pending_explicit_update'}
            finally:
                if temporary is not None and 'identity' in locals():
                    self._remove_owned(temporary, identity)
                # Only empty directories created by this invocation; never originals.
                for directory, identity in reversed(created_dirs):
                    current = self._metadata(self.path(self.relative(directory)))
                    if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
                        fail('DIRECTORY_IDENTITY_CHANGED')
                    try:
                        directory.rmdir()
                    except OSError:
                        pass

    def update_baseline(self, execute=False):
        self.require_clean()
        records, _ = self.manifests()
        result = {'schema_version': 2, 'algorithm': 'sha256', 'sources': {sid: self.anchor(r) for sid, r in records.items()}}
        if execute:
            with self.lock():
                self.require_clean()
                records, _ = self.manifests()
                result['sources'] = {sid: self.anchor(r) for sid, r in records.items()}
                self.write_json(BASELINE, result, replace_baseline=True)
        return {'dry_run': not execute, 'source_count': len(result['sources'])}

    def list_sources(self):
        records, issues = self.manifests()
        if issues:
            fail('MANIFEST_ERRORS')
        return [{k: r[k] for k in ('source_id', 'stored_relative_path', 'file_type', 'course', 'subject', 'source_type', 'parser_status')}
                for _, r in sorted(records.items())]

    def status(self):
        report = self.verify()
        records, _ = self.manifests()
        completed = {r['sha256'] for r in records.values()}
        pending, invalid = 0, 0
        for path in self.walk(PLANS):
            if path == PLANS + '/.gitkeep':
                continue
            try:
                plan = self.load_json(path)
                if (not isinstance(plan.get('sha256'), str) or not HEX.fullmatch(plan['sha256'])
                        or not isinstance(plan.get('plan_id'), str)
                        or Path(path).name != plan['plan_id'] + '.json'
                        or plan.get('status') not in ('ready', 'needs_review')):
                    fail('PLAN_INVALID')
                if plan.get('sha256') not in completed:
                    pending += 1
            except (SourceError, OSError):
                invalid += 1
        inbox = [p for p in self.walk('import-inbox') if p != 'import-inbox/.gitkeep']
        inbox_pending = 0
        for path in inbox:
            try:
                _, digest, _ = self.inspect(path)
                inbox_pending += digest not in completed
            except (SourceError, OSError):
                inbox_pending += 1  # Invalid/unsupported files still need user attention.
        return {'inbox_file_count': len(inbox), 'inbox_pending_count': inbox_pending,
                'pending_plans': pending, 'invalid_plans': invalid,
                'imported_count': len(records), 'integrity_issues': report['issues'],
                'baseline_pending': report['baseline_pending'],
                'awaiting_parse': sum(r['parser_status'] == 'not_started' for r in records.values()),
                'parsed_count': sum(r['parser_status'] == 'parsed' for r in records.values())}


def cli(argv=None):
    parser = argparse.ArgumentParser(description='Phase 2A: local copy-only source management. Default is dry-run.')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('scan', 'verify', 'list', 'status'):
        sub.add_parser(name, help='Read-only ' + name)
    plan = sub.add_parser('plan', help='Preview one file; --save writes only a review plan')
    plan.add_argument('file', help='Project-relative import-inbox path; quote paths with spaces')
    plan.add_argument('--course')
    plan.add_argument('--subject')
    plan.add_argument('--source-type')
    plan.add_argument('--save', action='store_true', help='Explicitly save a plan, never copy originals')
    apply = sub.add_parser('apply', help='Preview a saved plan; --apply explicitly executes the copy')
    apply.add_argument('--plan', required=True, help='Exact project-relative saved plan path')
    apply.add_argument('--apply', action='store_true', help='Explicit copy/registration authorization')
    baseline = sub.add_parser('baseline-update', help='Verify then append valid source anchors; errors block update')
    baseline.add_argument('--apply', action='store_true', help='Explicitly update baseline after verification')
    args = parser.parse_args(argv)
    try:
        manager = SourceManager()
        if args.command == 'plan':
            result = manager.plan(args.file, args.course, args.subject, args.source_type, save=args.save)
        elif args.command == 'apply':
            result = manager.apply(args.plan, execute=args.apply)
        elif args.command == 'baseline-update':
            result = manager.update_baseline(execute=args.apply)
        elif args.command == 'list':
            result = manager.list_sources()
        else:
            result = getattr(manager, args.command)()
        print(json_bytes(result).decode('utf-8'), end='')
        if args.command == 'verify' and not result['ok']:
            return 1
        if args.command == 'status' and result['integrity_issues']:
            return 1
        return 0
    except SourceError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print(json.dumps({'ok': False, 'error': 'IO_OR_INPUT_ERROR'}))
    return 1


if __name__ == '__main__':
    sys.exit(cli())
