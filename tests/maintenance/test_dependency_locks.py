import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('locks', ROOT / 'tools/check-dependency-locks.py')
locks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(locks)


class LockParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ('web', 'extension', 'api', 'mcp', 'converter', 'tests'):
            (self.root / directory).mkdir()
            for name in ('package.json', 'package-lock.json', 'deno.lock', 'requirements.txt', 'requirements.lock'):
                source = ROOT / directory / name
                if source.exists():
                    shutil.copyfile(source, self.root / directory / name)

    def test_current_tree_matches(self):
        self.assertEqual(locks.check(self.root), [])

    def test_npm_and_deno_drift(self):
        p = self.root / 'web/package.json'
        manifest = json.loads(p.read_text())
        manifest['dependencies']['next'] = '99.0.0'
        p.write_text(json.dumps(manifest))
        errors = locks.check(self.root)
        self.assertTrue(any('npm dependencies' in e for e in errors))
        self.assertTrue(any('Deno manifest' in e for e in errors))

    def test_python_drift(self):
        with (self.root / 'api/requirements.txt').open('a') as f:
            f.write('\nopentelemetry-api>=99\n')
        self.assertTrue(any('opentelemetry-api>=99' in e for e in locks.check(self.root)))

    def test_missing_deno_resolution(self):
        p = self.root / 'web/deno.lock'
        manifest = json.loads(p.read_text())
        manifest['specifiers'].pop(next(k for k in manifest['specifiers'] if k.startswith('npm:next@')))
        p.write_text(json.dumps(manifest))
        self.assertTrue(any('no resolution' in e for e in locks.check(self.root)))


if __name__ == '__main__':
    unittest.main()
