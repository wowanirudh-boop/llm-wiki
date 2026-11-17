#!/usr/bin/env python3
"""Cheap offline direct-dependency parity checks; installs/audits remain authoritative."""
import json
import re
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def check(root):
    errors = []
    for directory in ('web', 'extension'):
        manifest = json.loads((root / directory / 'package.json').read_text())
        locked = json.loads((root / directory / 'package-lock.json').read_text())['packages']['']
        for section in ('dependencies', 'devDependencies', 'optionalDependencies'):
            if manifest.get(section, {}) != locked.get(section, {}):
                errors.append(f'{directory}: npm {section} differ from package.json')
        if directory == 'web':
            deno = json.loads((root / directory / 'deno.lock').read_text())
            expected = {f'npm:{name}@{version}' for section in ('dependencies', 'devDependencies') for name, version in manifest.get(section, {}).items()}
            actual = set(deno['workspace']['packageJson']['dependencies'])
            if expected != actual:
                errors.append(f'web: Deno manifest snapshot differs (missing={sorted(expected-actual)}, extra={sorted(actual-expected)})')
            for spec in expected:
                if spec not in deno['specifiers']:
                    errors.append(f'web: Deno has no resolution for {spec}')
    for directory in ('api', 'mcp', 'converter', 'tests'):
        pins = {}
        for line in (root / directory / 'requirements.lock').read_text().splitlines():
            match = re.match(r'^([\w.-]+)==([^\s;\\]+)', line)
            if match:
                pins.setdefault(canonicalize_name(match[1]), set()).add(match[2])
        for line in (root / directory / 'requirements.txt').read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            requirement = Requirement(line)
            versions = pins.get(canonicalize_name(requirement.name), set())
            # Check all locked alternatives, rather than silently ignoring another platform.
            if not versions or any(not requirement.specifier.contains(v, prereleases=True) for v in versions):
                errors.append(f'{directory}: {requirement} is not satisfied by locked versions {sorted(versions)}')
    return errors


if __name__ == '__main__':
    failures = check(Path(__file__).resolve().parents[1])
    print('\n'.join(failures) if failures else 'Direct manifest/lock parity passed (npm, Deno and Python).')
    sys.exit(bool(failures))
