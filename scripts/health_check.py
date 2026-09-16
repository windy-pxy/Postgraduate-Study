"""Read-only health checks; Phase 2A adds binary integrity hashing, no text parsing."""
import importlib.util
from pathlib import Path, PurePosixPath
import subprocess

DIRECTORIES = (
    'vault', 'vault/00-System', 'vault/01-Math1',
    'vault/01-Math1/Calculus', 'vault/01-Math1/Linear-Algebra',
    'vault/01-Math1/Probability', 'vault/02-408',
    'vault/02-408/Data-Structure', 'vault/02-408/Computer-Organization',
    'vault/02-408/Operating-System', 'vault/02-408/Computer-Network',
    'vault/03-Knowledge-Notes', 'vault/04-Mistakes', 'vault/05-Past-Papers',
    'vault/06-Stage-Tests', 'vault/07-Weakness-Analysis',
    'vault/08-Study-Records', 'vault/80-Attachments',
    'vault/90-Parsed-Sources', 'vault/99-Templates',
    'sources-original', 'sources-original/math1', 'sources-original/408',
    'import-inbox', 'review-queue', 'archive', 'scripts', 'config',
    'prompts', 'tests', 'logs', 'config/source-manifests', 'review-queue/import-plans',
)
FILES = ('AGENTS.md', 'README.md', '.gitignore', '.env.example',
         'config/providers.example.yaml', 'scripts/health_check.py',
         'tests/test_health_check.py', 'scripts/source_manager.py',
         'config/sources-original.baseline.json')


def source_integrity(root):
    if not safe_kind(root, 'scripts', True) or not safe_kind(root, 'scripts/source_manager.py'):
        return False
    spec = importlib.util.spec_from_file_location('source_manager_health', root / 'scripts/source_manager.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.SourceManager(root).verify()['ok']
    except (module.SourceError, OSError, ValueError, TypeError, KeyError):
        return False


def safe_kind(root, relative, directory=False):
    """Inspect each path component before descending; never follow links."""
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or '..' in parts:
        return False
    current = root
    for part in (None, *parts):
        if part is not None:
            current = current / part
        if current.is_symlink() or current.is_junction():
            return False
    return current.is_dir() if directory else current.is_file()


def forbidden_tracked(name):
    path = PurePosixPath(name.lower())
    if path.parts and path.parts[0] == 'sources-original':
        return path.name != '.gitkeep'
    return (path.name == '.env'
            or (path.name.startswith('.env.') and path.name != '.env.example')
            or path.suffix in {'.pem', '.key'}
            or path.name in {'credentials.json', 'secrets.yaml'})


def git_read(root, *args):
    # Disable optional index refresh writes and filesystem monitor hooks.
    return subprocess.run(
        ['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
         '-c', 'core.untrackedCache=false', '-C', str(root), *args],
        capture_output=True, check=True, timeout=20,
    ).stdout


def check(root):
    results = []
    dirs_ok = all(safe_kind(root, p, True) for p in DIRECTORIES)
    results.append(('Required directories', dirs_ok))
    results.append(('Original source directories identifiable (not ACL enforcement)',
                    all(safe_kind(root, p, True) for p in
                        ('sources-original', 'sources-original/math1', 'sources-original/408'))))
    results.append(('Required files', all(safe_kind(root, p) for p in FILES)))
    results.append(('Provider example', safe_kind(root, 'config/providers.example.yaml')))
    # Refuse external Git directories/worktrees; require an in-project .git directory.
    if not safe_kind(root, '.git', True):
        results.append(('Local Git repository', False))
        return results
    try:
        top = git_read(root, 'rev-parse', '--show-toplevel').decode().strip()
        if Path(top) != root:
            results.append(('Local Git repository', False))
            return results
        results.append(('Local Git repository', True))
        tracked = git_read(root, 'ls-files', '-z').decode('utf-8', 'replace').split('\0')
        results.append(('No tracked environment secrets or original materials',
                        not any(forbidden_tracked(p) for p in tracked if p)))
        status = git_read(root, 'status', '--porcelain=v1', '-z')
        # Never print filenames or Git stderr: they may contain sensitive text.
        results.append(('Git status readable (' + ('changes present' if status else 'clean') + ')', True))
    except (OSError, subprocess.SubprocessError, UnicodeError):
        results.append(('Git read operations', False))
    return results


def main():
    root = Path(__file__).absolute().parent.parent
    try:
        results = check(root)
        results.append(('SHA-256 source integrity and baseline consistency', source_integrity(root)))
    except OSError:
        print('FAIL: filesystem metadata unavailable (details withheld)')
        return 1
    for label, ok in results:
        print(('PASS: ' if ok else 'FAIL: ') + label)
    return 0 if all(ok for _, ok in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
