"""Rebuildable local page index with accepted-only search by default."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import sys
from urllib.parse import quote
import uuid


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).absolute().parent / (name.split('_for_search')[0] + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


try:
    from source_manager import SourceManager, SourceError, SID, json_bytes
except ModuleNotFoundError:
    source_module = load_script('source_manager_for_search')
    SourceManager, SourceError, SID, json_bytes = (
        source_module.SourceManager, source_module.SourceError,
        source_module.SID, source_module.json_bytes)

try:
    from enhanced_parser import EnhancedParser, EnhancedError
except ModuleNotFoundError:
    enhanced_module = load_script('enhanced_parser_for_search')
    EnhancedParser, EnhancedError = enhanced_module.EnhancedParser, enhanced_module.EnhancedError

PROJECT_ROOT = Path(__file__).absolute().parent.parent
INDEX_RELATIVE = 'indexes/local-search.sqlite3'
SCHEMA_VERSION = 1
PAGE_NAME = re.compile(r'page-(\d{4})\.md')
ENHANCED_PAGE_NAME = re.compile(r'page-(\d{4})')


class SearchError(Exception):
    pass


def fail(code):
    raise SearchError(code)


def digest_text(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def safe_relative(value, prefix=None):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ('', '.', '..') for part in path.parts):
        return False
    return prefix is None or value == prefix or value.startswith(prefix.rstrip('/') + '/')


def frontmatter(text):
    lines = text.lstrip('\ufeff').splitlines()
    if not lines or lines[0].strip() != '---':
        fail('ACCEPTED_FRONTMATTER_INVALID')
    try:
        end = lines.index('---', 1)
    except ValueError:
        fail('ACCEPTED_FRONTMATTER_INVALID')
    values = {}
    for line in lines[1:end]:
        if ': ' not in line:
            fail('ACCEPTED_FRONTMATTER_INVALID')
        key, raw = line.split(': ', 1)
        if key in values:
            fail('ACCEPTED_FRONTMATTER_INVALID')
        try:
            values[key] = json.loads(raw)
        except json.JSONDecodeError:
            fail('ACCEPTED_FRONTMATTER_INVALID')
    return values, '\n'.join(lines[end + 1:]).strip()


def basic_text(text):
    match = re.search(r'^```text\s*\n(.*?)\n```\s*$', text, re.MULTILINE | re.DOTALL)
    if not match:
        fail('BASIC_PAGE_TEXT_INVALID')
    return match.group(1)


def snippet(content, query, size=180):
    compact = re.sub(r'\s+', ' ', content).strip()
    position = compact.casefold().find(query.casefold())
    if position < 0:
        position = 0
    start = max(0, position - size // 3)
    end = min(len(compact), start + size)
    return compact[start:end]


class LocalSearch:
    def __init__(self, root=PROJECT_ROOT):
        self.root = Path(root).absolute()
        self.manager = SourceManager(self.root)

    def _records(self):
        integrity = self.manager.verify()
        if not integrity.get('ok'):
            fail('SOURCE_INTEGRITY_FAILED')
        records, issues = self.manager.manifests()
        if issues:
            fail('SOURCE_MANIFEST_INVALID')
        return records

    def _entry(self, record, page, version, parser_id, parser_version,
               review_status, relative, content):
        if (type(page) is not int or page < 1 or version not in {'accepted', 'basic', 'enhanced'}
                or review_status not in {'accepted', 'review_required'}
                or not safe_relative(relative, f'vault/90-Parsed-Sources/{record["source_id"]}')):
            fail('INDEX_ENTRY_INVALID')
        return {
            'source_id': record['source_id'], 'source_sha256': record['sha256'],
            'page_number': page, 'version_kind': version, 'parser_id': parser_id,
            'parser_version': parser_version, 'review_status': review_status,
            'relative_path': relative, 'source_pdf_relative_path': record['stored_relative_path'],
            'content_sha256': digest_text(content), 'content': content,
        }

    def _accepted(self, record):
        folder = self.manager.path(
            f'vault/90-Parsed-Sources/{record["source_id"]}/accepted/pages',
            f'vault/90-Parsed-Sources/{record["source_id"]}')
        if not folder.is_dir():
            return []
        entries = []
        for path in sorted(folder.glob('page-*.md')):
            match = PAGE_NAME.fullmatch(path.name)
            if not match:
                fail('ACCEPTED_FILENAME_INVALID')
            metadata, content = frontmatter(path.read_text(encoding='utf-8'))
            page = int(match.group(1))
            required = {'source_id', 'source_sha256', 'source_page', 'derived',
                        'review_status', 'parser_id', 'parser_version'}
            if (set(metadata) != required or metadata['source_id'] != record['source_id']
                    or metadata['source_sha256'] != record['sha256']
                    or metadata['source_page'] != page or metadata['derived'] is not True
                    or metadata['review_status'] != 'accepted'
                    or not isinstance(metadata['parser_id'], str)
                    or not isinstance(metadata['parser_version'], str) or not content):
                fail('ACCEPTED_METADATA_INVALID')
            relative = path.relative_to(self.root).as_posix()
            entries.append(self._entry(record, page, 'accepted', metadata['parser_id'],
                                       metadata['parser_version'], 'accepted', relative, content))
        return entries

    def _basic(self, record):
        folder = self.manager.path(
            f'vault/90-Parsed-Sources/{record["source_id"]}/pages',
            f'vault/90-Parsed-Sources/{record["source_id"]}')
        if not folder.is_dir() or record.get('parser_status') != 'parsed':
            return []
        entries = []
        for path in sorted(folder.glob('page-*.md')):
            match = PAGE_NAME.fullmatch(path.name)
            if not match:
                fail('BASIC_PAGE_FILENAME_INVALID')
            page = int(match.group(1)); raw = path.read_text(encoding='utf-8')
            metadata, _ = frontmatter(raw)
            if (metadata.get('source_id') != record['source_id']
                    or metadata.get('source_page') != page
                    or metadata.get('derived') is not True
                    or metadata.get('review_status') != 'review_required'):
                fail('BASIC_PAGE_METADATA_INVALID')
            content = basic_text(raw)
            entries.append(self._entry(
                record, page, 'basic', record['parser_name'], record['parser_version'],
                'review_required', path.relative_to(self.root).as_posix(), content))
        return entries

    def _enhanced(self, record):
        folder = self.manager.path(
            f'vault/90-Parsed-Sources/{record["source_id"]}/enhanced/mineru',
            f'vault/90-Parsed-Sources/{record["source_id"]}')
        if not folder.is_dir():
            return []
        verifier = EnhancedParser(self.root)
        entries = []
        for candidate in sorted(folder.iterdir()):
            match = ENHANCED_PAGE_NAME.fullmatch(candidate.name)
            if not match:
                if candidate.name.startswith('.tmp-page-'):
                    continue
                fail('ENHANCED_DIRECTORY_INVALID')
            page = int(match.group(1))
            verifier.verify_output(record['source_id'], page)
            metadata = json.loads((candidate / 'candidate-manifest.json').read_text('utf-8'))
            content_path = candidate / 'mineru.md'; content = content_path.read_text('utf-8')
            entries.append(self._entry(
                record, page, 'enhanced', metadata['parser_id'], metadata['parser_version'],
                'review_required', content_path.relative_to(self.root).as_posix(), content))
        return entries

    def collect(self, include_review_candidates=False):
        entries = []
        for record in self._records().values():
            entries.extend(self._accepted(record))
            if include_review_candidates:
                entries.extend(self._basic(record)); entries.extend(self._enhanced(record))
        return sorted(entries, key=lambda item: (
            item['source_id'], item['page_number'], item['version_kind'], item['parser_id']))

    def build(self, include_review_candidates=False, rebuild=False):
        target = self.manager.path(INDEX_RELATIVE, 'indexes')
        if target.exists() and not rebuild:
            fail('INDEX_EXISTS_USE_REBUILD')
        target.parent.mkdir(parents=True, exist_ok=True)
        entries = self.collect(include_review_candidates)
        temporary = target.parent / f'.tmp-local-search-{uuid.uuid4().hex}.sqlite3'
        connection = None
        try:
            connection = sqlite3.connect(temporary)
            connection.executescript('''
                PRAGMA journal_mode=DELETE;
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
                CREATE TABLE documents (
                    id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                    page_number INTEGER NOT NULL, version_kind TEXT NOT NULL,
                    parser_id TEXT NOT NULL, parser_version TEXT NOT NULL,
                    review_status TEXT NOT NULL, relative_path TEXT NOT NULL,
                    source_pdf_relative_path TEXT NOT NULL, content_sha256 TEXT NOT NULL,
                    content TEXT NOT NULL,
                    UNIQUE(source_id,page_number,version_kind,parser_id,relative_path)
                ) STRICT;
                CREATE VIRTUAL TABLE documents_fts USING fts5(content, tokenize='trigram');
            ''')
            metadata = {'schema_version': SCHEMA_VERSION, 'created_at': now_iso(),
                        'includes_review_candidates': bool(include_review_candidates)}
            connection.executemany('INSERT INTO meta(key,value) VALUES (?,?)',
                                   [(key, json.dumps(value)) for key, value in metadata.items()])
            for entry in entries:
                values = tuple(entry[key] for key in (
                    'source_id', 'source_sha256', 'page_number', 'version_kind', 'parser_id',
                    'parser_version', 'review_status', 'relative_path',
                    'source_pdf_relative_path', 'content_sha256', 'content'))
                cursor = connection.execute(
                    'INSERT INTO documents(source_id,source_sha256,page_number,version_kind,'
                    'parser_id,parser_version,review_status,relative_path,source_pdf_relative_path,'
                    'content_sha256,content) VALUES (?,?,?,?,?,?,?,?,?,?,?)', values)
                connection.execute('INSERT INTO documents_fts(rowid,content) VALUES (?,?)',
                                   (cursor.lastrowid, entry['content']))
            connection.commit(); connection.close(); connection = None
            with temporary.open('rb+') as stream:
                os.fsync(stream.fileno())
            if target.exists():
                temporary.replace(target)
            else:
                temporary.rename(target)
            return {'ok': True, 'index_relative_path': INDEX_RELATIVE,
                    'document_count': len(entries),
                    'accepted_count': sum(e['review_status'] == 'accepted' for e in entries),
                    'review_candidate_count': sum(e['review_status'] != 'accepted' for e in entries),
                    'includes_review_candidates': bool(include_review_candidates)}
        except SearchError:
            raise
        except (OSError, sqlite3.Error):
            fail('INDEX_BUILD_FAILED')
        finally:
            if connection is not None:
                connection.close()

    def _connect(self):
        path = self.manager.path(INDEX_RELATIVE, 'indexes')
        if not path.is_file():
            fail('INDEX_MISSING')
        return sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)

    def search(self, query, source_id=None, page_number=None,
               include_review_candidates=False, limit=10):
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            fail('QUERY_INVALID')
        query = query.strip()
        if source_id is not None and (not isinstance(source_id, str) or not SID.fullmatch(source_id)):
            fail('SOURCE_ID_INVALID')
        if page_number is not None and (type(page_number) is not int or page_number < 1):
            fail('PAGE_NUMBER_INVALID')
        if type(limit) is not int or not 1 <= limit <= 50:
            fail('LIMIT_INVALID')
        connection = self._connect()
        try:
            accepted_total = connection.execute(
                "SELECT count(*) FROM documents WHERE review_status='accepted'").fetchone()[0]
            conditions, parameters = [], []
            if len(query) >= 3:
                conditions.append('d.id IN (SELECT rowid FROM documents_fts WHERE documents_fts MATCH ?)')
                parameters.append('"' + query.replace('"', '""') + '"')
            else:
                conditions.append('instr(lower(d.content), lower(?)) > 0'); parameters.append(query)
            if not include_review_candidates:
                conditions.append("d.review_status = 'accepted'")
            if source_id:
                conditions.append('d.source_id = ?'); parameters.append(source_id)
            if page_number is not None:
                conditions.append('d.page_number = ?'); parameters.append(page_number)
            parameters.append(limit)
            rows = connection.execute(
                'SELECT d.source_id,d.source_sha256,d.page_number,d.version_kind,d.parser_id,'
                'd.parser_version,d.review_status,d.relative_path,d.source_pdf_relative_path,d.content '
                'FROM documents d WHERE ' + ' AND '.join(conditions)
                + ' ORDER BY d.source_id,d.page_number,d.version_kind LIMIT ?', parameters).fetchall()
        finally:
            connection.close()
        results = []
        for row in rows:
            relative = row[7]
            vault_relative = relative.removeprefix('vault/').removesuffix('.md')
            results.append({
                'source_id': row[0], 'source_sha256': row[1], 'page_number': row[2],
                'version_kind': row[3], 'parser_id': row[4], 'parser_version': row[5],
                'review_status': row[6], 'risk': None if row[6] == 'accepted' else 'UNREVIEWED_CANDIDATE',
                'snippet': snippet(row[9], query), 'relative_path': relative,
                'source_pdf_relative_path': row[8],
                'obsidian_wikilink': f'[[{vault_relative}|{row[0]} 第 {row[2]} 页 ({row[3]})]]',
                'obsidian_uri': 'obsidian://open?vault=vault&file=' + quote(vault_relative, safe=''),
            })
        if not results and not include_review_candidates and accepted_total == 0:
            return {'ok': True, 'status': 'no_approved_content',
                    'message': '暂无已审核资料', 'query': query, 'results': []}
        return {'ok': True, 'status': 'matches' if results else 'no_matches',
                'query': query, 'includes_review_candidates': bool(include_review_candidates),
                'results': results}

    def status(self):
        connection = self._connect()
        try:
            total = connection.execute('SELECT count(*) FROM documents').fetchone()[0]
            accepted = connection.execute(
                "SELECT count(*) FROM documents WHERE review_status='accepted'").fetchone()[0]
            sources = connection.execute('SELECT count(DISTINCT source_id) FROM documents').fetchone()[0]
        finally:
            connection.close()
        return {'ok': True, 'index_relative_path': INDEX_RELATIVE, 'document_count': total,
                'accepted_count': accepted, 'review_candidate_count': total - accepted,
                'source_count': sources}

    def verify(self):
        records = self._records()
        connection = self._connect()
        try:
            meta = {key: json.loads(value) for key, value in connection.execute('SELECT key,value FROM meta')}
            if set(meta) != {'schema_version', 'created_at', 'includes_review_candidates'} \
                    or meta['schema_version'] != SCHEMA_VERSION:
                fail('INDEX_METADATA_INVALID')
            try:
                created = datetime.fromisoformat(meta['created_at'])
            except (TypeError, ValueError):
                fail('INDEX_METADATA_INVALID')
            if created.tzinfo is None or type(meta['includes_review_candidates']) is not bool:
                fail('INDEX_METADATA_INVALID')
            rows = connection.execute(
                'SELECT source_id,source_sha256,relative_path,content_sha256,review_status,'
                'source_pdf_relative_path,content,version_kind,page_number,parser_id,parser_version '
                'FROM documents'
            ).fetchall()
            fts_count = connection.execute('SELECT count(*) FROM documents_fts').fetchone()[0]
            fts_mismatch = connection.execute(
                'SELECT count(*) FROM documents d JOIN documents_fts f ON f.rowid=d.id '
                'WHERE f.content != d.content').fetchone()[0]
        finally:
            connection.close()
        if fts_count != len(rows) or fts_mismatch:
            fail('INDEX_FTS_MISMATCH')
        for (source_id, source_hash, relative, content_hash, review_status, source_relative,
             stored_content, version, page, parser_id, parser_version) in rows:
            if source_id not in records or records[source_id]['sha256'] != source_hash:
                fail('INDEX_SOURCE_MISMATCH')
            if (source_relative != records[source_id]['stored_relative_path']
                    or review_status not in {'accepted', 'review_required'}
                    or version not in {'accepted', 'basic', 'enhanced'}
                    or (review_status == 'accepted') != (version == 'accepted')
                    or type(page) is not int or page < 1
                    or not parser_id or not parser_version
                    or digest_text(stored_content) != content_hash):
                fail('INDEX_ENTRY_INVALID')
            if not safe_relative(relative, f'vault/90-Parsed-Sources/{source_id}'):
                fail('INDEX_PATH_INVALID')
            path = self.manager.path(relative, f'vault/90-Parsed-Sources/{source_id}')
            if not path.is_file():
                fail('INDEX_DOCUMENT_MISSING')
            raw = path.read_text('utf-8')
            if review_status == 'accepted':
                _, content = frontmatter(raw)
            elif '/pages/' in relative:
                content = basic_text(raw)
            else:
                content = raw
            if digest_text(content) != content_hash:
                fail('INDEX_CONTENT_CHANGED_REBUILD_REQUIRED')
        return {'ok': True, 'document_count': len(rows), 'source_count': len({r[0] for r in rows})}


def cli(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Local page search; accepted content only by default.')
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build'); build.add_argument('--include-review-candidates', action='store_true')
    build.add_argument('--rebuild', action='store_true')
    search = sub.add_parser('search'); search.add_argument('query')
    search.add_argument('--source-id'); search.add_argument('--page', type=int)
    search.add_argument('--include-review-candidates', action='store_true'); search.add_argument('--limit', type=int, default=10)
    sub.add_parser('status'); sub.add_parser('verify')
    args = parser.parse_args(argv)
    try:
        engine = LocalSearch()
        if args.command == 'build':
            result = engine.build(args.include_review_candidates, args.rebuild)
        elif args.command == 'search':
            result = engine.search(args.query, args.source_id, args.page,
                                   args.include_review_candidates, args.limit)
        elif args.command == 'status': result = engine.status()
        else: result = engine.verify()
        print(json_bytes(result).decode('utf-8'), end=''); return 0
    except SearchError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)})); return 1
    except (SourceError, EnhancedError):
        print(json.dumps({'ok': False, 'error': 'DEPENDENCY_VALIDATION_FAILED'})); return 1
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, sqlite3.Error):
        print(json.dumps({'ok': False, 'error': 'IO_OR_INDEX_ERROR'})); return 1


if __name__ == '__main__':
    sys.exit(cli())
