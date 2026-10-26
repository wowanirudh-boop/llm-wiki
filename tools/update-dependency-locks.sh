#!/usr/bin/env bash
# Run from any directory after changing a dependency manifest.
# Requires Node >=22, npm, Deno, and uv. Never uses audit --force.
set -euo pipefail
cd "$(dirname "$0")/.."
for package_dir in web extension; do
  (cd "$package_dir" && npm install --package-lock-only --ignore-scripts --no-audit)
done
# Resolve Deno independently: install alone can retain vulnerable transitive pins
# from an old Deno lock, even after npm overrides change.
deno_tmp=$(mktemp -d)
trap 'rm -rf "$deno_tmp"' EXIT
cp web/package.json "$deno_tmp/package.json"
(cd "$deno_tmp" && deno install --lockfile-only)
cp "$deno_tmp/deno.lock" web/deno.lock
uv pip compile api/requirements.txt --python-version 3.11 --universal --output-file api/requirements.lock --generate-hashes
# CI installs API and MCP together: keep their shared packages compatible.
uv pip compile mcp/requirements.txt --python-version 3.11 --universal --constraint api/requirements.lock --output-file mcp/requirements.lock --generate-hashes
for package_dir in converter tests; do
  uv pip compile "$package_dir/requirements.txt" --python-version 3.11 --universal --output-file "$package_dir/requirements.lock" --generate-hashes
done
printf '\nReview and commit manifests AND generated locks together; run Security and Tests before merge.\n'
