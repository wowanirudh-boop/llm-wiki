import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LockUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for d in ('tools', 'bin', 'api', 'mcp', 'web', 'extension', 'converter', 'tests'):
            (self.root / d).mkdir()
        shutil.copyfile(ROOT / 'tools/update-dependency-locks.sh', self.root / 'tools/update-dependency-locks.sh')
        (self.root / 'web/package.json').write_text('{}')
        self.env = dict(os.environ, PATH=str(self.root / 'bin') + ':' + os.environ['PATH'], CALLS=str(self.root / 'calls'))
        for tool in ('npm', 'deno', 'uv'):
            p = self.root / 'bin' / tool
            p.write_text('#!/bin/sh\nprintf "%s %s\\n" "$(basename "$0")" "$*" >> "$CALLS"\n[ "$(basename "$0")" != deno ] || echo "{}" > deno.lock\n')
            p.chmod(0o755)

    def run_update(self, *args):
        result = subprocess.run(['bash', str(self.root / 'tools/update-dependency-locks.sh'), *args], env=self.env, capture_output=True, text=True)
        return result, (self.root / 'calls').read_text() if (self.root / 'calls').exists() else ''

    def test_api_mcp_are_paired(self):
        result, calls = self.run_update('mcp')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('api/requirements.txt', calls)
        self.assertIn('--constraint api/requirements.lock', calls)
        self.assertNotIn('npm ', calls)
        self.assertNotIn('converter/', calls)

    def test_web_updates_both_locks(self):
        result, calls = self.run_update('web')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('npm install --package-lock-only --ignore-scripts', calls)
        self.assertIn('deno install --lockfile-only', calls)
        self.assertNotIn('uv ', calls)

    def test_unknown_service_rejected(self):
        result, calls = self.run_update('bad-service')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, '')


if __name__ == '__main__':
    unittest.main()
