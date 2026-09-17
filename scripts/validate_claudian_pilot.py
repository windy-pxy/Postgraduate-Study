"""Read-only checks for the guarded Claudian study pilot."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).absolute().parent.parent
POLICY_RELATIVE = 'vault/AGENTS.md'
PILOT_SOURCE = 'src-e1df768ce191'
PILOT_PAGE = 2


def load_local_search():
    spec = importlib.util.spec_from_file_location(
        'local_search_for_claudian', ROOT / 'scripts/local_search.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REQUIRED_POLICY_TEXT = (
    'study_readonly_pilot', 'read-only', '暂无已审核资料', 'review_required',
    'source_id', 'parser_version', '90-Parsed-Sources/', 'sources-original/',
    'import-inbox/', 'config/source-manifests/', 'config/sources-original.baseline.json',
    'review-queue/', '生成草稿', '03-知识笔记/', '04-错题本/',
    '只读文件操作', '不得执行项目脚本', '写入型命令',
    '有效接受事件', '严格资料查询', '模型补充',
    '不得自行把候选内容标为 accepted/approved',
)


def check_policy(root=ROOT):
    path = Path(root) / POLICY_RELATIVE
    if not path.is_file():
        return {'ok': False, 'error': 'POLICY_MISSING'}
    text = path.read_text(encoding='utf-8')
    missing = [token for token in REQUIRED_POLICY_TEXT if token not in text]
    return {'ok': not missing, 'policy_relative_path': POLICY_RELATIVE,
            'missing_requirement_count': len(missing),
            'error': 'POLICY_INCOMPLETE' if missing else None}


def run_pilot(root=ROOT, source_id=PILOT_SOURCE, page=PILOT_PAGE):
    policy = check_policy(root)
    if not policy['ok']:
        return policy
    module = load_local_search()
    engine = module.LocalSearch(root)
    formal = engine.search('补码', source_id=source_id, page_number=page)
    preview = engine.search('补码', source_id=source_id, page_number=page,
                            include_review_candidates=True)
    results = preview.get('results', [])
    versions = {item.get('version_kind') for item in results}
    required_fields = ('source_id', 'page_number', 'parser_id', 'parser_version',
                       'review_status', 'obsidian_wikilink', 'relative_path')
    valid_preview = bool(results) and all(
        all(item.get(field) not in (None, '') for field in required_fields)
        and item['source_id'] == source_id
        and item['page_number'] == page
        and item['review_status'] == 'review_required'
        and item.get('risk') == 'UNREVIEWED_CANDIDATE'
        and (Path(root) / item['relative_path']).is_file()
        for item in results)
    ok = (formal.get('status') == 'no_approved_content'
          and formal.get('message') == '暂无已审核资料'
          and not formal.get('results')
          and {'basic', 'enhanced'}.issubset(versions)
          and valid_preview)
    safe_results = [{key: item[key] for key in required_fields} for item in results]
    return {
        'ok': ok,
        'formal_status': formal.get('status'),
        'formal_message': formal.get('message'),
        'preview_result_count': len(results),
        'preview_versions': sorted(versions),
        'preview_results': safe_results,
        'error': None if ok else 'PILOT_CONTRACT_FAILED',
    }


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Validate the read-only Claudian study pilot.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check-policy')
    sub.add_parser('run-pilot')
    args = parser.parse_args(argv)
    try:
        result = check_policy() if args.command == 'check-policy' else run_pilot()
    except Exception:
        result = {'ok': False, 'error': 'PILOT_VALIDATION_FAILED'}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main())
