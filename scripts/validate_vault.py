"""Read-only Phase 1 validation. Requires the already installed PyYAML.

No API, environment secrets, original-file contents, writes, or deletions.
"""
from datetime import date
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys

try:
    import yaml
except ImportError:
    yaml = None

TYPES = {'knowledge', 'mistake', 'past-paper', 'source-note', 'stage-test',
         'study-record', 'weakness'}
SUBJECTS = {
    'math1': {'Calculus', 'Linear-Algebra', 'Probability'},
    '408': {'Data-Structure', 'Computer-Organization', 'Operating-System', 'Computer-Network'},
}
REQUIRED = ('id', 'type', 'course', 'subject', 'chapter', 'knowledge_points',
            'source_type', 'source_name', 'source_page', 'difficulty', 'mastery',
            'status', 'created', 'updated', 'review_dates', 'tags')
ERROR_TYPES = {'concept', 'calculation', 'method', 'reading', 'memory', 'careless', 'unknown'}
TEMPLATES = {
    'Knowledge-Note.md': 'knowledge', 'Mistake.md': 'mistake',
    'Source-Note.md': 'source-note', 'Past-Paper.md': 'past-paper',
    'Stage-Test.md': 'stage-test', 'Study-Record.md': 'study-record', 'Weakness.md': 'weakness',
}
SYSTEM_NOTES = {
    '00-System/Home.md', '00-System/Metadata-Schema.md', '00-System/Linking-Rules.md',
    '00-System/Validation-Guide.md', '00-System/Review-Queue.md',
    '00-System/Source-Import-Guide.md',
    '00-System/PDF-Parsing-Guide.md',
    '00-System/Enhanced-Parsing-Guide.md',
    '00-System/Local-Retrieval-Guide.md',
    '00-System/Scalable-Parsing-Architecture.md',
    '00-System/Batch-Parsing-Guide.md',
    '01-Math1/Math1-MOC.md', '02-408/408-MOC.md',
    '03-Knowledge-Notes/Knowledge-MOC.md', '04-Mistakes/Mistakes-MOC.md',
    '05-Past-Papers/Past-Papers-MOC.md', '06-Stage-Tests/Stage-Tests-MOC.md',
    '07-Weakness-Analysis/Weakness-MOC.md', '08-Study-Records/Study-Records-MOC.md',
    '80-Attachments/Attachments-MOC.md', '90-Parsed-Sources/Parsed-Sources-MOC.md',
    '99-Templates/Templates-MOC.md',
    *{f'01-Math1/{s}/{s}-MOC.md' for s in SUBJECTS['math1']},
    *{f'02-408/{s}/{s}-MOC.md' for s in SUBJECTS['408']},
}
PLACEHOLDER = re.compile(r'\{\{[A-Za-z][A-Za-z0-9_]*\}\}')
WIKI = re.compile(r'!?\[\[([^\[\]\n]+)\]\]')


class InvalidYaml(ValueError):
    pass


if yaml:
    class UniqueLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            result = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str) or key in result:
                    raise InvalidYaml('duplicate or non-string YAML key')
                result[key] = self.construct_object(value_node, deep=deep)
            return result


def frontmatter(text):
    lines = text.lstrip('\ufeff').splitlines()
    if not lines or lines[0].strip() != '---':
        return None, text
    end = next((n for n in range(1, len(lines)) if lines[n].strip() == '---'), None)
    if end is None:
        raise InvalidYaml('unclosed frontmatter')
    try:
        data = yaml.load('\n'.join(lines[1:end]), Loader=UniqueLoader)
    except (yaml.YAMLError, ValueError, TypeError, RecursionError):
        raise InvalidYaml('invalid YAML') from None
    if not isinstance(data, dict):
        raise InvalidYaml('frontmatter must be a mapping')
    return data, '\n'.join(lines[end + 1:])


def placeholder(value):
    return isinstance(value, str) and PLACEHOLDER.fullmatch(value) is not None


def parsed_output_document(path):
    parts = PurePosixPath(path).parts
    return (len(parts) >= 3 and parts[0] == '90-Parsed-Sources'
            and re.fullmatch(r'src-[0-9a-f]{12,64}', parts[1]) is not None
            and parts[-1].lower().endswith('.md'))


def valid_date(value):
    if type(value) is date:
        return True
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def valid_page(value):
    if value is None or value == '':
        return True
    if type(value) is int:
        return value > 0
    if not isinstance(value, str):
        return False
    atom = r'(?:[1-9]\d*|[IVXLCDMivxlcdm]+|[A-Za-z]+[-.][1-9]\d*)'
    for segment in value.split(','):
        match = re.fullmatch(rf'\s*({atom})(?:\s*-\s*({atom}))?\s*', segment)
        if not match:
            return False
        a, b = match.groups()
        if b and a.isdecimal() and b.isdecimal() and int(a) > int(b):
            return False
    return True


def strings(value, ancestors=None):
    """Visit YAML strings; reject recursive aliases without infinite traversal."""
    ancestors = set() if ancestors is None else ancestors
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, dict)):
        if id(value) in ancestors:
            raise InvalidYaml('recursive YAML alias')
        ancestors = ancestors | {id(value)}
        for child in (value.values() if isinstance(value, dict) else value):
            yield from strings(child, ancestors)


def visible_markdown(body):
    body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    output, fence, length = [], None, 0
    for line in body.splitlines():
        found = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if found:
            token = found.group(1)
            if fence is None:
                fence, length = token[0], len(token)
            elif token[0] == fence and len(token) >= length:
                fence = None
            continue
        if fence is None:
            output.append(line)
    return re.sub(r'(`+).*?\1', '', '\n'.join(output))


def resolve_link(link, origin, assets):
    target = link.split('|', 1)[0].split('#', 1)[0].strip()
    if not target:
        return origin  # same-note heading/block link; anchor not checked
    p = PurePosixPath(target)
    if p.is_absolute() or '..' in p.parts or '\\' in target or ':' in target:
        return None
    names = [target] if p.suffix else [target + '.md', target]
    # Vault-relative links preferred. No guessing when basename is ambiguous.
    hits = {name for name in names if name in assets}
    if not hits:
        hits = {str(PurePosixPath(origin).parent / name) for name in names
                if str(PurePosixPath(origin).parent / name) in assets}
    if not hits and '/' not in target:
        hits = {name for name in assets if PurePosixPath(name).name in names}
    return next(iter(hits)) if len(hits) == 1 else None


def validate_documents(documents, assets=None):
    """Pure validation core: tests pass synthetic notes without writing fixtures."""
    issues, ids = [], {}
    assets = set(documents) if assets is None else set(assets)
    for path, content in sorted(documents.items()):
        def fail(code, field=''):
            issues.append((path, code, field))

        is_template = path in {'99-Templates/' + name for name in TEMPLATES}
        infrastructure = path in SYSTEM_NOTES or parsed_output_document(path)
        try:
            meta, body = frontmatter(content)
            values = list(strings(meta)) if meta is not None else []
        except (InvalidYaml, RecursionError):
            fail('YAML_INVALID')
            continue
        if meta is None:
            if not infrastructure:
                fail('FRONTMATTER_REQUIRED')
        elif not infrastructure:
            for field in REQUIRED:
                if field not in meta:
                    fail('FIELD_REQUIRED', field)
            for field in REQUIRED:
                value = meta.get(field)
                if is_template and placeholder(value) and field != 'type':
                    continue
                if field == 'id':
                    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{7,127}', value):
                        fail('ID_INVALID', field)
                    elif not is_template:
                        if value in ids:
                            fail('ID_DUPLICATE', 'id (also in ' + ids[value] + ')')
                        else:
                            ids[value] = path
                elif field == 'type' and (not isinstance(value, str) or value not in TYPES):
                    fail('TYPE_INVALID', field)
                elif field == 'course' and (not isinstance(value, str) or value not in SUBJECTS):
                    fail('COURSE_INVALID', field)
                elif field == 'subject':
                    course = meta.get('course')
                    if isinstance(course, str) and course in SUBJECTS and (not isinstance(value, str) or value not in SUBJECTS[course]):
                        fail('SUBJECT_INVALID', field)
                elif field == 'mastery' and (type(value) is not int or not 0 <= value <= 5):
                    fail('MASTERY_INVALID', field)
                elif field == 'difficulty' and value is not None and (type(value) is not int or not 1 <= value <= 5):
                    fail('DIFFICULTY_INVALID', field)
                elif field in ('created', 'updated') and not valid_date(value):
                    fail('DATE_INVALID', field)
                elif field == 'review_dates':
                    if not isinstance(value, list) or any(not valid_date(v) and not (is_template and placeholder(v)) for v in value):
                        fail('DATE_LIST_INVALID', field)
                elif field == 'source_page' and not valid_page(value):
                    fail('PAGE_INVALID', field)
                elif field == 'knowledge_points':
                    if not isinstance(value, list) or any(not isinstance(v, str) or not re.fullmatch(r'\[\[[^\[\]\n]+\]\]', v) for v in value):
                        fail('KNOWLEDGE_LINKS_INVALID', field)
                elif field == 'tags':
                    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
                        fail('TAGS_INVALID', field)
                elif field == 'status' and (not isinstance(value, str) or value not in {'draft', 'active', 'reviewed', 'archived'}):
                    fail('STATUS_INVALID', field)
                elif field in ('chapter', 'source_type', 'source_name') and value is not None and not isinstance(value, str):
                    fail('TEXT_INVALID', field)
            if is_template:
                if meta.get('type') != TEMPLATES[PurePosixPath(path).name]:
                    fail('TEMPLATE_TYPE_INVALID')
                if not placeholder(meta.get('id')):
                    fail('TEMPLATE_ID_PLACEHOLDER_REQUIRED')
            else:
                if any(PLACEHOLDER.search(v) for v in values) or PLACEHOLDER.search(body):
                    fail('UNRESOLVED_PLACEHOLDER')
                if valid_date(meta.get('created')) and valid_date(meta.get('updated')):
                    if str(meta['updated']) < str(meta['created']):
                        fail('DATE_ORDER_INVALID')
            if meta.get('type') == 'mistake':
                value = meta.get('error_type')
                if not (is_template and placeholder(value)) and (not isinstance(value, str) or value not in ERROR_TYPES):
                    fail('ERROR_TYPE_INVALID', 'error_type')
            if meta.get('type') == 'source-note':
                value = meta.get('source_file')
                if not (is_template and placeholder(value)):
                    p = PurePosixPath(value) if isinstance(value, str) else None
                    if (p is None or len(p.parts) < 3 or p.parts[0] != 'sources-original'
                            or p.parts[1] not in {'math1', '408'} or '..' in p.parts
                            or '\\' in value or ':' in value):
                        fail('SOURCE_FILE_INVALID', 'source_file')
                if not is_template and (not meta.get('source_name') or meta.get('source_page') in (None, '')):
                    fail('SOURCE_CITATION_REQUIRED')
        link_text = '\n'.join(values) + '\n' + visible_markdown(body)
        for match in WIKI.finditer(link_text):
            link = match.group(1)
            if is_template and PLACEHOLDER.search(link):
                continue
            if resolve_link(link, path, assets) is None:
                fail('LINK_MISSING_OR_AMBIGUOUS')
    return issues


class UnsafePath(ValueError):
    pass


def path_metadata(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise UnsafePath('link or reparse point refused')
    return info


def scan_tree(root, directory, skip_hidden=False):
    """Read metadata only, reject links before descent; paths stay inside root."""
    root = root.absolute()
    path_metadata(root)
    relative = directory.absolute().relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        path_metadata(current)
    found = {}

    def visit(folder):
        for child in sorted(folder.iterdir()):
            info = path_metadata(child)
            if skip_hidden and child.name.startswith('.'):
                continue
            name = child.relative_to(directory).as_posix()
            is_dir = stat.S_ISDIR(info.st_mode)
            if not is_dir and not stat.S_ISREG(info.st_mode):
                raise UnsafePath('nonregular file refused')
            found[name] = {'kind': 'directory' if is_dir else 'file',
                           'size': None if is_dir else info.st_size,
                           'mtime_ns': None if is_dir else info.st_mtime_ns}
            if is_dir:
                visit(child)
    visit(directory)
    return found


def compare_originals(current, baseline):
    return [(f'sources-original/{name}', 'ORIGINAL_INVENTORY_CHANGED', '')
            for name in sorted(current.keys() | baseline.keys())
            if current.get(name) != baseline.get(name)]


def validate_project(root):
    root = root.absolute()
    try:
        inventory = scan_tree(root, root / 'vault', skip_hidden=True)
        original_inventory = scan_tree(root, root / 'sources-original')
        path_metadata(root / 'scripts')
        path_metadata(root / 'scripts/source_manager.py')
        spec = importlib.util.spec_from_file_location('source_manager_vault', root / 'scripts/source_manager.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            report = module.SourceManager(root).verify()
            issues = [(item['path'], item['error'], '') for item in report['issues']]
        except module.SourceError:
            issues = [('sources-original', 'SOURCE_INTEGRITY_CHECK_FAILED', '')]
        path_metadata(root / 'scripts/pdf_parser.py')
        parser_spec = importlib.util.spec_from_file_location('pdf_parser_vault', root / 'scripts/pdf_parser.py')
        parser_module = importlib.util.module_from_spec(parser_spec)
        parser_spec.loader.exec_module(parser_module)
        parser = parser_module.PDFParser(root)
        path_metadata(root / 'scripts/enhanced_parser.py')
        enhanced_spec = importlib.util.spec_from_file_location(
            'enhanced_parser_vault', root / 'scripts/enhanced_parser.py')
        enhanced_module = importlib.util.module_from_spec(enhanced_spec)
        enhanced_spec.loader.exec_module(enhanced_module)
        enhanced_parser = enhanced_module.EnhancedParser(root)
        parsed_ids = []
        for name, entry in inventory.items():
            parts = PurePosixPath(name).parts
            if not parts or parts[0] != '90-Parsed-Sources':
                continue
            if len(parts) == 2:
                if entry['kind'] == 'directory' and re.fullmatch(r'src-[0-9a-f]{12,64}', parts[1]):
                    parsed_ids.append(parts[1])
                elif parts[1] not in {'.gitkeep', 'Parsed-Sources-MOC.md'}:
                    issues.append((name, 'UNREGISTERED_PARSED_OUTPUT', ''))
        for source_id in sorted(parsed_ids):
            try:
                parser.verify_output(source_id)
            except (parser_module.ParserError, parser_module.SourceError, OSError, ValueError, TypeError, KeyError):
                issues.append((f'90-Parsed-Sources/{source_id}', 'PARSED_OUTPUT_INVALID', ''))
            candidate_root = root / 'vault/90-Parsed-Sources' / source_id / 'enhanced/mineru'
            if candidate_root.is_dir():
                for candidate in sorted(candidate_root.iterdir()):
                    match = re.fullmatch(r'page-(\d{4})', candidate.name)
                    if not match or not candidate.is_dir():
                        if not candidate.name.startswith('.tmp-page-'):
                            issues.append((
                                f'90-Parsed-Sources/{source_id}/enhanced/mineru/{candidate.name}',
                                'ENHANCED_OUTPUT_INVALID', ''))
                        continue
                    try:
                        enhanced_parser.verify_output(source_id, int(match.group(1)))
                    except (enhanced_module.EnhancedError, enhanced_module.SourceError,
                            OSError, ValueError, TypeError, KeyError):
                        issues.append((
                            f'90-Parsed-Sources/{source_id}/enhanced/mineru/{candidate.name}',
                            'ENHANCED_OUTPUT_INVALID', ''))
        assets = {name for name, entry in inventory.items() if entry['kind'] == 'file'}
        documents = {}
        for name in sorted(assets):
            if name.lower().endswith('.md'):
                try:
                    documents[name] = (root / 'vault' / name).read_text(encoding='utf-8-sig')
                except UnicodeError:
                    issues.append((name, 'UTF8_REQUIRED', ''))
        for name in SYSTEM_NOTES | {'99-Templates/' + n for n in TEMPLATES}:
            if name not in documents:
                issues.append((name, 'STRUCTURE_FILE_REQUIRED', ''))
        issues.extend(validate_documents(documents, assets))
        for name, content in documents.items():
            if name in SYSTEM_NOTES or name.startswith('99-Templates/'):
                continue
            try:
                meta, _ = frontmatter(content)
            except InvalidYaml:
                continue
            if meta and meta.get('type') == 'source-note':
                source = meta.get('source_file')
                if isinstance(source, str) and source.startswith('sources-original/'):
                    entry = original_inventory.get(source.removeprefix('sources-original/'))
                    if not entry or entry['kind'] != 'file':
                        issues.append((name, 'SOURCE_FILE_MISSING', 'source_file'))
        return issues, len(documents)
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        # Do not echo file contents or raw exceptions (could include secrets).
        return [('project', 'UNSAFE_PATH_OR_UNREADABLE_INPUT', '')], 0


def main():
    if yaml is None:
        print('FAIL: PyYAML unavailable; no installation attempted.')
        return 2
    issues, count = validate_project(Path(__file__).absolute().parent.parent)
    for path, code, field in issues:
        print(f'FAIL: {path}: {code}' + (f' [{field}]' if field else ''))
    print(f'{"FAIL" if issues else "PASS"}: {count} Markdown files; {len(issues)} issues; read-only validation.')
    return 1 if issues else 0


if __name__ == '__main__':
    sys.exit(main())
