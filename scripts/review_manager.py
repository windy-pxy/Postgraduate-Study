"""Traceable human review, acceptance snapshots, and revocation events."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import uuid


def load_script(name):
    path = Path(__file__).absolute().parent / f'{name}.py'
    spec = importlib.util.spec_from_file_location(f'{name}_for_review', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from source_manager import SourceManager, SourceError, SID, iso_time, json_bytes
except ModuleNotFoundError:
    source_module = load_script('source_manager')
    SourceManager, SourceError, SID, iso_time, json_bytes = (
        source_module.SourceManager, source_module.SourceError, source_module.SID,
        source_module.iso_time, source_module.json_bytes)


PROJECT_ROOT = Path(__file__).absolute().parent.parent
EVENTS = 'review-queue/acceptance-events'
SCHEMA_VERSION = 1
EVENT_ID = re.compile(r'(?:acc|rev)-[0-9a-f]{32}')
PAGE_FILE = re.compile(r'page-(\d{4})\.md')
SNAPSHOT_FILE = re.compile(r'(acc-[0-9a-f]{32})\.md')
SHA256 = re.compile(r'[0-9a-f]{64}')
TEXT_LIMIT = 2000


class ReviewError(Exception):
    pass


def fail(code):
    raise ReviewError(code)


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def safe_relative(value, prefix=None):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ('', '.', '..') for part in path.parts):
        return False
    return prefix is None or value == prefix or value.startswith(prefix.rstrip('/') + '/')


def frontmatter(text, code='CANDIDATE_FRONTMATTER_INVALID'):
    lines = text.lstrip('\ufeff').splitlines()
    if not lines or lines[0].strip() != '---':
        fail(code)
    try:
        end = lines.index('---', 1)
    except ValueError:
        fail(code)
    values = {}
    for line in lines[1:end]:
        if ': ' not in line:
            fail(code)
        key, raw = line.split(': ', 1)
        if key in values:
            fail(code)
        try:
            values[key] = json.loads(raw)
        except json.JSONDecodeError:
            fail(code)
    return values, '\n'.join(lines[end + 1:]).strip()


def basic_text(text):
    match = re.search(r'^```text\s*\n(.*?)\n```\s*$', text, re.MULTILINE | re.DOTALL)
    if not match:
        fail('BASIC_PAGE_TEXT_INVALID')
    return match.group(1)


def valid_text(value, allow_empty=False):
    return (isinstance(value, str) and len(value) <= TEXT_LIMIT
            and (allow_empty or bool(value.strip())) and '\x00' not in value)


class ReviewManager:
    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root).absolute()
        self.manager = SourceManager(self.root)

    def _records(self):
        result = self.manager.verify()
        if not result.get('ok'):
            fail('SOURCE_INTEGRITY_FAILED')
        records, issues = self.manager.manifests()
        if issues:
            fail('SOURCE_MANIFEST_INVALID')
        return records

    def _read_bytes(self, relative, limit=32 * 1024 * 1024):
        with self.manager.reader(relative) as stream:
            value = stream.read(limit + 1)
        if len(value) > limit:
            fail('REVIEW_FILE_TOO_LARGE')
        return value

    def _json(self, relative):
        try:
            return json.loads(self._read_bytes(relative, 1024 * 1024).decode('utf-8'),
                              object_pairs_hook=self._strict_object)
        except (UnicodeDecodeError, json.JSONDecodeError):
            fail('REVIEW_JSON_INVALID')

    @staticmethod
    def _strict_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail('REVIEW_JSON_DUPLICATE_KEY')
            result[key] = value
        return result

    def _candidate(self, record, page, relative):
        sid = record['source_id']
        if not safe_relative(relative):
            fail('CANDIDATE_PATH_INVALID')
        raw = self._read_bytes(relative)
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            fail('CANDIDATE_ENCODING_INVALID')
        basic = f'vault/90-Parsed-Sources/{sid}/pages/page-{page:04d}.md'
        enhanced = (f'vault/90-Parsed-Sources/{sid}/enhanced/mineru/'
                    f'page-{page:04d}/mineru.md')
        if relative == basic:
            metadata, _ = frontmatter(text)
            if (metadata.get('source_id') != sid or metadata.get('source_page') != page
                    or metadata.get('derived') is not True
                    or metadata.get('review_status') != 'review_required'):
                fail('CANDIDATE_METADATA_INVALID')
            content = basic_text(text)
            parser_id, parser_version, kind = (
                record['parser_name'], record['parser_version'], 'basic')
        elif relative == enhanced:
            manifest_relative = str(PurePosixPath(relative).parent / 'candidate-manifest.json')
            manifest = self._json(manifest_relative)
            if (manifest.get('source_id') != sid or manifest.get('source_page') != page
                    or manifest.get('review_status') != 'review_required'
                    or manifest.get('candidate_only') is not True
                    or not isinstance(manifest.get('parser_id'), str)
                    or not isinstance(manifest.get('parser_version'), str)):
                fail('CANDIDATE_METADATA_INVALID')
            content = text.strip()
            parser_id, parser_version, kind = (
                manifest['parser_id'], manifest['parser_version'], 'enhanced')
        elif (PurePosixPath(relative).parent == PurePosixPath('review-queue')
              and relative.endswith('.md')):
            metadata, content = frontmatter(text)
            required = {'source_id', 'source_sha256', 'source_page', 'derived',
                        'review_status', 'parser_id', 'parser_version'}
            if (set(metadata) != required or metadata['source_id'] != sid
                    or metadata['source_sha256'] != record['sha256']
                    or metadata['source_page'] != page or metadata['derived'] is not True
                    or metadata['review_status'] != 'review_required'
                    or not isinstance(metadata['parser_id'], str) or not metadata['parser_id']
                    or not isinstance(metadata['parser_version'], str)
                    or not metadata['parser_version']):
                fail('CANDIDATE_METADATA_INVALID')
            parser_id, parser_version, kind = (
                metadata['parser_id'], metadata['parser_version'], 'manual')
        else:
            fail('CANDIDATE_PATH_NOT_ALLOWED')
        if not content:
            fail('CANDIDATE_CONTENT_EMPTY')
        return {
            'candidate_relative_path': relative,
            'candidate_sha256': sha256_bytes(raw),
            'content_sha256': sha256_bytes(content.encode('utf-8')),
            'candidate_kind': kind,
            'parser_id': parser_id,
            'parser_version': parser_version,
            'content': content,
        }

    def _candidate_paths(self, record, page):
        sid = record['source_id']
        paths = [
            f'vault/90-Parsed-Sources/{sid}/pages/page-{page:04d}.md',
            f'vault/90-Parsed-Sources/{sid}/enhanced/mineru/page-{page:04d}/mineru.md',
        ]
        review_root = self.manager.path('review-queue', 'review-queue')
        if review_root.is_dir():
            for path in sorted(review_root.glob('*.md')):
                relative = path.relative_to(self.root).as_posix()
                try:
                    raw = self._read_bytes(relative).decode('utf-8')
                    metadata, _ = frontmatter(raw)
                    if metadata.get('source_id') == record['source_id'] \
                            and metadata.get('source_page') == page:
                        paths.append(relative)
                except (OSError, UnicodeDecodeError, ReviewError):
                    continue
        return [path for path in paths if self.manager.path(path).is_file()]

    def _preview_relative(self, record, page):
        relative = f'vault/90-Parsed-Sources/{record["source_id"]}/assets/page-{page:04d}.png'
        return relative if self.manager.path(relative).is_file() else None

    def _event_files(self):
        root = self.manager.path(EVENTS, EVENTS)
        if not root.is_dir():
            return []
        files = []
        for path in sorted(root.iterdir()):
            if path.name == '.gitkeep':
                continue
            if not path.is_file() or not EVENT_ID.fullmatch(path.stem) or path.suffix != '.json':
                fail('REVIEW_EVENT_FILENAME_INVALID')
            files.append(path.relative_to(self.root).as_posix())
        return files

    def _validate_accept_event(self, event, filename, records):
        required = {'schema_version', 'event_id', 'event_type', 'source_id', 'source_sha256',
                    'source_page', 'candidate_relative_path', 'candidate_sha256',
                    'candidate_kind', 'parser_id', 'parser_version', 'snapshot_relative_path',
                    'snapshot_sha256', 'content_sha256', 'reviewer', 'review_notes', 'reviewed_at'}
        if (set(event) != required or event.get('schema_version') != SCHEMA_VERSION
                or event.get('event_type') != 'accept'
                or not isinstance(event.get('event_id'), str)
                or not event['event_id'].startswith('acc-')
                or filename != event['event_id'] + '.json'
                or event.get('source_id') not in records
                or event.get('source_sha256') != records[event['source_id']]['sha256']
                or type(event.get('source_page')) is not int or event['source_page'] < 1
                or event.get('candidate_kind') not in {'basic', 'enhanced', 'manual'}
                or not all(isinstance(event.get(k), str) and event[k]
                           for k in ('candidate_sha256', 'parser_id', 'parser_version',
                                     'snapshot_sha256', 'content_sha256'))
                or not all(SHA256.fullmatch(event[k])
                           for k in ('candidate_sha256', 'snapshot_sha256', 'content_sha256'))
                or not valid_text(event.get('reviewer'))
                or not valid_text(event.get('review_notes'))
                or not iso_time(event.get('reviewed_at'))):
            fail('ACCEPT_EVENT_INVALID')
        candidate = self._candidate(records[event['source_id']], event['source_page'],
                                    event['candidate_relative_path'])
        for key in ('candidate_sha256', 'content_sha256', 'candidate_kind',
                    'parser_id', 'parser_version'):
            if event[key] != candidate[key]:
                fail('ACCEPTED_CANDIDATE_CHANGED')
        expected_prefix = (f'vault/90-Parsed-Sources/{event["source_id"]}/accepted/pages/'
                           f'page-{event["source_page"]:04d}')
        if (not safe_relative(event['snapshot_relative_path'], expected_prefix)
                or PurePosixPath(event['snapshot_relative_path']).name
                != event['event_id'] + '.md'):
            fail('ACCEPTED_SNAPSHOT_PATH_INVALID')
        snapshot_raw = self._read_bytes(event['snapshot_relative_path'])
        if sha256_bytes(snapshot_raw) != event['snapshot_sha256']:
            fail('ACCEPTED_SNAPSHOT_CHANGED')
        try:
            metadata, content = frontmatter(snapshot_raw.decode('utf-8'),
                                            'ACCEPTED_SNAPSHOT_INVALID')
        except UnicodeDecodeError:
            fail('ACCEPTED_SNAPSHOT_INVALID')
        expected_meta = {
            'source_id': event['source_id'], 'source_sha256': event['source_sha256'],
            'source_page': event['source_page'], 'derived': True,
            'review_status': 'accepted', 'parser_id': event['parser_id'],
            'parser_version': event['parser_version'],
            'acceptance_event_id': event['event_id'],
            'candidate_relative_path': event['candidate_relative_path'],
            'candidate_sha256': event['candidate_sha256'], 'reviewer': event['reviewer'],
            'reviewed_at': event['reviewed_at'],
        }
        if metadata != expected_meta or sha256_bytes(content.encode('utf-8')) != event['content_sha256']:
            fail('ACCEPTED_SNAPSHOT_INVALID')
        return {**event, 'content': content, 'event_relative_path': f'{EVENTS}/{filename}'}

    def _validate_revoke_event(self, event, filename):
        required = {'schema_version', 'event_id', 'event_type', 'acceptance_event_id',
                    'source_id', 'source_page', 'reviewer', 'reason', 'revoked_at'}
        if (set(event) != required or event.get('schema_version') != SCHEMA_VERSION
                or event.get('event_type') != 'revoke'
                or not isinstance(event.get('event_id'), str)
                or not event['event_id'].startswith('rev-')
                or filename != event['event_id'] + '.json'
                or not isinstance(event.get('acceptance_event_id'), str)
                or not event['acceptance_event_id'].startswith('acc-')
                or not isinstance(event.get('source_id'), str) or not SID.fullmatch(event['source_id'])
                or type(event.get('source_page')) is not int or event['source_page'] < 1
                or not valid_text(event.get('reviewer')) or not valid_text(event.get('reason'))
                or not iso_time(event.get('revoked_at'))):
            fail('REVOKE_EVENT_INVALID')
        return event

    def _snapshot_files(self):
        root = self.manager.path('vault/90-Parsed-Sources', 'vault/90-Parsed-Sources')
        if not root.is_dir():
            return []
        return sorted(path for path in self.manager.walk('vault/90-Parsed-Sources')
                      if '/accepted/' in path and not path.endswith('/.gitkeep'))

    def _analyze(self):
        records = self._records()
        acceptances, revocations, raw_hashes = {}, [], {}
        for relative in self._event_files():
            raw = self._read_bytes(relative)
            raw_hashes[relative] = sha256_bytes(raw)
            event = self._json(relative)
            if event.get('event_type') == 'accept':
                validated = self._validate_accept_event(
                    event, PurePosixPath(relative).name, records)
                if validated['event_id'] in acceptances:
                    fail('REVIEW_EVENT_ID_DUPLICATE')
                acceptances[validated['event_id']] = validated
            elif event.get('event_type') == 'revoke':
                revocations.append(self._validate_revoke_event(
                    event, PurePosixPath(relative).name))
            else:
                fail('REVIEW_EVENT_TYPE_INVALID')
        timeline = sorted(
            list(acceptances.values()) + revocations,
            key=lambda event: (event.get('reviewed_at', event.get('revoked_at')), event['event_id']))
        active_by_page, revoked = {}, set()
        for event in timeline:
            key = (event['source_id'], event['source_page'])
            if event['event_type'] == 'accept':
                if key in active_by_page:
                    fail('MULTIPLE_ACTIVE_ACCEPTANCES')
                active_by_page[key] = event['event_id']
            else:
                target = acceptances.get(event['acceptance_event_id'])
                if (target is None or target['source_id'] != event['source_id']
                        or target['source_page'] != event['source_page']
                        or active_by_page.get(key) != target['event_id']):
                    fail('REVOKE_TARGET_INVALID')
                del active_by_page[key]
                revoked.add(target['event_id'])
        registered_snapshots = {event['snapshot_relative_path'] for event in acceptances.values()}
        if set(self._snapshot_files()) != registered_snapshots:
            fail('ACCEPTED_SNAPSHOT_INVENTORY_MISMATCH')
        active = [acceptances[event_id] for event_id in active_by_page.values()]
        digest_payload = [{'path': path, 'sha256': raw_hashes[path]}
                          for path in sorted(raw_hashes)]
        state_digest = sha256_bytes(json_bytes(digest_payload))
        return {
            'records': records, 'acceptances': acceptances, 'revocations': revocations,
            'active': sorted(active, key=lambda e: (e['source_id'], e['source_page'])),
            'revoked_ids': revoked, 'state_sha256': state_digest,
        }

    def verify(self):
        try:
            analysis = self._analyze()
            return {
                'ok': True, 'acceptance_count': len(analysis['acceptances']),
                'active_accepted_count': len(analysis['active']),
                'revoked_acceptance_count': len(analysis['revoked_ids']),
                'acceptance_state_sha256': analysis['state_sha256'], 'issues': [],
            }
        except (ReviewError, SourceError, OSError, KeyError, TypeError) as exc:
            code = str(exc) if isinstance(exc, (ReviewError, SourceError)) else 'REVIEW_IO_ERROR'
            return {'ok': False, 'issues': [{'error': code}]}

    def active_snapshots(self):
        try:
            return self._analyze()['active']
        except SourceError as exc:
            raise ReviewError(str(exc)) from exc

    def state_sha256(self):
        try:
            return self._analyze()['state_sha256']
        except SourceError as exc:
            raise ReviewError(str(exc)) from exc

    def inspect(self, source_id, page, candidate_relative=None):
        records = self._records()
        if not isinstance(source_id, str) or not SID.fullmatch(source_id) or source_id not in records:
            fail('SOURCE_ID_INVALID')
        page_count = records[source_id].get('page_count')
        if (type(page) is not int or page < 1 or type(page_count) is not int
                or page > page_count):
            fail('PAGE_NUMBER_INVALID')
        paths = [candidate_relative] if candidate_relative else self._candidate_paths(records[source_id], page)
        candidates = []
        for relative in paths:
            candidate = self._candidate(records[source_id], page, relative)
            candidates.append({key: candidate[key] for key in (
                'candidate_relative_path', 'candidate_sha256', 'content_sha256',
                'candidate_kind', 'parser_id', 'parser_version')})
        analysis = self._analyze()
        active = [event for event in analysis['active']
                  if event['source_id'] == source_id and event['source_page'] == page]
        return {
            'ok': True, 'source_id': source_id, 'source_sha256': records[source_id]['sha256'],
            'source_page': page, 'page_preview_relative_path': self._preview_relative(records[source_id], page),
            'candidate_count': len(candidates), 'candidates': candidates,
            'active_acceptance_event_id': active[0]['event_id'] if active else None,
        }

    def _snapshot_bytes(self, event, content):
        metadata = {
            'source_id': event['source_id'], 'source_sha256': event['source_sha256'],
            'source_page': event['source_page'], 'derived': True,
            'review_status': 'accepted', 'parser_id': event['parser_id'],
            'parser_version': event['parser_version'],
            'acceptance_event_id': event['event_id'],
            'candidate_relative_path': event['candidate_relative_path'],
            'candidate_sha256': event['candidate_sha256'], 'reviewer': event['reviewer'],
            'reviewed_at': event['reviewed_at'],
        }
        header = '\n'.join(f'{key}: {json.dumps(value, ensure_ascii=False)}'
                           for key, value in metadata.items())
        return f'---\n{header}\n---\n{content}\n'.encode('utf-8')

    def _write_new_bytes(self, relative, value):
        destination = self.manager.path(relative)
        if destination.exists():
            fail('TARGET_EXISTS')
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.manager.path(destination.parent.relative_to(self.root).as_posix())
        temporary = destination.parent / f'.{uuid.uuid4().hex}.tmp'
        with temporary.open('xb') as stream:
            identity = os.fstat(stream.fileno())
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
        try:
            self.manager._publish(temporary, destination)
        finally:
            self.manager._remove_owned(temporary, identity)

    def accept(self, source_id, page, candidate_relative, reviewer, notes, apply=False):
        if not valid_text(reviewer) or not valid_text(notes):
            fail('REVIEW_IDENTITY_OR_NOTES_INVALID')
        inspection = self.inspect(source_id, page, candidate_relative)
        if inspection['active_acceptance_event_id'] is not None:
            fail('PAGE_ALREADY_ACCEPTED')
        candidate = self._candidate(self._records()[source_id], page, candidate_relative)
        event_id = 'acc-' + uuid.uuid4().hex
        reviewed_at = now_iso()
        snapshot_relative = (f'vault/90-Parsed-Sources/{source_id}/accepted/pages/'
                             f'page-{page:04d}/{event_id}.md')
        event = {
            'schema_version': SCHEMA_VERSION, 'event_id': event_id, 'event_type': 'accept',
            'source_id': source_id, 'source_sha256': inspection['source_sha256'],
            'source_page': page, 'candidate_relative_path': candidate_relative,
            'candidate_sha256': candidate['candidate_sha256'],
            'candidate_kind': candidate['candidate_kind'], 'parser_id': candidate['parser_id'],
            'parser_version': candidate['parser_version'],
            'snapshot_relative_path': snapshot_relative, 'snapshot_sha256': '',
            'content_sha256': candidate['content_sha256'], 'reviewer': reviewer.strip(),
            'review_notes': notes.strip(), 'reviewed_at': reviewed_at,
        }
        snapshot = self._snapshot_bytes(event, candidate['content'])
        event['snapshot_sha256'] = sha256_bytes(snapshot)
        result = {key: event[key] for key in event if key != 'review_notes'}
        result.update(ok=True, apply=bool(apply), index_rebuild_required=bool(apply))
        if not apply:
            return result
        self._write_new_bytes(snapshot_relative, snapshot)
        self.manager.write_json(f'{EVENTS}/{event_id}.json', event)
        verified = self.verify()
        if not verified.get('ok'):
            fail('ACCEPT_POST_VERIFY_FAILED')
        return result

    def revoke(self, acceptance_event_id, reviewer, reason, apply=False):
        if (not isinstance(acceptance_event_id, str)
                or not re.fullmatch(r'acc-[0-9a-f]{32}', acceptance_event_id)):
            fail('ACCEPTANCE_ID_INVALID')
        if not valid_text(reviewer) or not valid_text(reason):
            fail('REVIEW_IDENTITY_OR_REASON_INVALID')
        analysis = self._analyze()
        target = analysis['acceptances'].get(acceptance_event_id)
        if target is None or acceptance_event_id not in {e['event_id'] for e in analysis['active']}:
            fail('ACCEPTANCE_NOT_ACTIVE')
        event_id = 'rev-' + uuid.uuid4().hex
        event = {
            'schema_version': SCHEMA_VERSION, 'event_id': event_id, 'event_type': 'revoke',
            'acceptance_event_id': acceptance_event_id, 'source_id': target['source_id'],
            'source_page': target['source_page'], 'reviewer': reviewer.strip(),
            'reason': reason.strip(), 'revoked_at': now_iso(),
        }
        result = {**event, 'ok': True, 'apply': bool(apply),
                  'snapshot_preserved': True, 'index_rebuild_required': bool(apply)}
        if not apply:
            return result
        self.manager.write_json(f'{EVENTS}/{event_id}.json', event)
        verified = self.verify()
        if not verified.get('ok'):
            fail('REVOKE_POST_VERIFY_FAILED')
        return result

    def status(self):
        verification = self.verify()
        candidate_count = 0
        try:
            records = self._records()
            for record in records.values():
                for page in range(1, record.get('page_count', 0) + 1):
                    candidate_count += len(self._candidate_paths(record, page))
        except (ReviewError, SourceError, OSError):
            if verification.get('ok'):
                verification = {'ok': False, 'issues': [{'error': 'STATUS_SCAN_FAILED'}]}
        return {
            'ok': verification.get('ok', False), 'pending_candidate_count': candidate_count,
            'active_accepted_count': verification.get('active_accepted_count', 0),
            'revoked_acceptance_count': verification.get('revoked_acceptance_count', 0),
            'integrity_issue_count': len(verification.get('issues', [])),
            'issues': verification.get('issues', []),
        }


def cli(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Human review and immutable acceptance snapshots.')
    sub = parser.add_subparsers(dest='command', required=True)
    inspect_cmd = sub.add_parser('inspect')
    inspect_cmd.add_argument('--source-id', required=True); inspect_cmd.add_argument('--page', type=int, required=True)
    inspect_cmd.add_argument('--candidate')
    accept_cmd = sub.add_parser('accept')
    accept_cmd.add_argument('--source-id', required=True); accept_cmd.add_argument('--page', type=int, required=True)
    accept_cmd.add_argument('--candidate', required=True); accept_cmd.add_argument('--reviewer', required=True)
    accept_cmd.add_argument('--notes', required=True); accept_cmd.add_argument('--apply', action='store_true')
    revoke_cmd = sub.add_parser('revoke')
    revoke_cmd.add_argument('--acceptance-id', required=True); revoke_cmd.add_argument('--reviewer', required=True)
    revoke_cmd.add_argument('--reason', required=True); revoke_cmd.add_argument('--apply', action='store_true')
    sub.add_parser('verify'); sub.add_parser('status')
    args = parser.parse_args(argv)
    try:
        manager = ReviewManager()
        if args.command == 'inspect':
            result = manager.inspect(args.source_id, args.page, args.candidate)
        elif args.command == 'accept':
            result = manager.accept(args.source_id, args.page, args.candidate,
                                    args.reviewer, args.notes, args.apply)
        elif args.command == 'revoke':
            result = manager.revoke(args.acceptance_id, args.reviewer, args.reason, args.apply)
        elif args.command == 'verify':
            result = manager.verify()
        else:
            result = manager.status()
        print(json_bytes(result).decode('utf-8'), end='')
        return 0 if result.get('ok') else 1
    except ReviewError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)})); return 1
    except SourceError:
        print(json.dumps({'ok': False, 'error': 'SOURCE_VALIDATION_FAILED'})); return 1
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        print(json.dumps({'ok': False, 'error': 'REVIEW_IO_ERROR'})); return 1


if __name__ == '__main__':
    sys.exit(cli())
