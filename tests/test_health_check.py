"""In-memory tests: no temporary files, material reads, or deletions."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).absolute().parent.parent
SPEC = importlib.util.spec_from_file_location('health_check', ROOT / 'scripts/health_check.py')
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)


class HealthTests(unittest.TestCase):
    def simulated(self, tracked=b'', missing=None):
        def git(root, *args):
            return {'rev-parse': str(ROOT).encode(), 'ls-files': tracked,
                    'status': b'?? README.md\0'}[args[0]]
        with patch.object(health, 'safe_kind', side_effect=lambda r, p, directory=False: p != missing), \
                patch.object(health, 'git_read', side_effect=git):
            return health.check(ROOT)

    def test_valid_skeleton(self):
        self.assertTrue(all(ok for _, ok in self.simulated()))

    def test_missing_directory_and_file(self):
        for name in ('sources-original', 'vault/04-错题本', 'AGENTS.md',
                     'config/providers.example.yaml', '.git'):
            with self.subTest(name=name):
                self.assertFalse(all(ok for _, ok in self.simulated(missing=name)))

    def test_tracked_secrets_and_originals_rejected(self):
        for name in ('.env', 'config/.env.production', 'private.key',
                     'credentials.json', 'sources-original/math1/book.PDF',
                     'sources-original/408/notes.md',
                     'config/sources-original.baseline.json',
                     'config/source-manifests/src-aaaaaaaaaaaa.json',
                     'import-inbox/book.pdf',
                     'review-queue/import-plans/plan.json',
                     'review-queue/parsing-routing/src-aaaaaaaaaaaa.json',
                     'review-queue/parsing-jobs/job.json',
                     'review-queue/parsing-checkpoints/page.json',
                     'vault/90-Parsed-Sources/src-aaaaaaaaaaaa/index.md',
                     'logs/run.log', 'archive/old.md', 'models/cache/model.bin'):
            with self.subTest(name=name):
                self.assertFalse(all(ok for _, ok in self.simulated(name.encode() + b'\0')))

    def test_examples_notes_placeholders_allowed(self):
        for name in ('.env.example', 'config/providers.example.yaml',
                     'config/sources-original.baseline.example.json',
                     'vault/03-知识笔记/笔记.md', 'sources-original/math1/.gitkeep'):
            self.assertFalse(health.forbidden_tracked(name))
        for name in ('config/source-manifests/.gitkeep', 'import-inbox/.gitkeep',
                     'review-queue/import-plans/.gitkeep',
                     'review-queue/parsing-routing/.gitkeep',
                     'review-queue/parsing-jobs/.gitkeep',
                     'review-queue/parsing-checkpoints/.gitkeep',
                     'vault/90-Parsed-Sources/.gitkeep',
                     'vault/90-Parsed-Sources/Parsed-Sources-MOC.md'):
            self.assertFalse(health.forbidden_tracked(name))

    def test_git_failure_reported(self):
        with patch.object(health, 'safe_kind', return_value=True), \
                patch.object(health, 'git_read', side_effect=FileNotFoundError):
            self.assertFalse(all(ok for _, ok in health.check(ROOT)))

    def test_external_git_root_rejected(self):
        with patch.object(health, 'safe_kind', return_value=True), \
                patch.object(health, 'git_read', return_value=b'Z:/external'):
            self.assertFalse(all(ok for _, ok in health.check(ROOT)))

    def test_junction_and_symlink_rejected_before_descent(self):
        for method in ('is_junction', 'is_symlink'):
            with patch.object(Path, method, return_value=True), \
                    patch.object(Path, 'is_file') as read:
                self.assertFalse(health.safe_kind(ROOT, 'sources-original/book.pdf'))
                read.assert_not_called()

    def test_parent_traversal_rejected(self):
        self.assertFalse(health.safe_kind(ROOT, '../outside'))

    def test_git_subprocess_read_only_flags(self):
        with patch.object(subprocess, 'run') as run:
            health.git_read(ROOT, 'status', '--porcelain=v1', '-z')
            args = run.call_args.args[0]
            self.assertIn('--no-optional-locks', args)
            self.assertIn('core.fsmonitor=false', args)
            self.assertTrue(run.call_args.kwargs['capture_output'])

    def test_integrity_helper_link_refused_before_import(self):
        with patch.object(health, 'safe_kind', return_value=False), \
                patch.object(health.importlib.util, 'spec_from_file_location') as loader:
            self.assertFalse(health.source_integrity(ROOT))
            loader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
