# Dependency security maintenance

Security scans check the *installed dependency graph*, not just application code. A previously passing commit can fail when an advisory is added. OSV, npm and Deno overlap; a shared Python dependency can appear in four jobs. Do not add job totals together as a count of distinct defects, or treat a scanner finding as proof of exploitation.

## Update workflow

1. Read the failing step. An install/resolution error (including manifest/lock disagreement) is a maintenance failure, not a new vulnerability finding.
2. Review advisory conditions and affected versions. Update direct pins or targeted transitive overrides; do not use `npm audit fix --force` indiscriminately or suppress security checks merely to get green CI.
3. Run `tools/update-dependency-locks.sh` from a machine with Node 22+, npm, Deno and uv. Review and commit all changed manifests and locks together. Deno's separate web lock must be regenerated too; its plain install can retain old transitive pins, so the helper resolves it in a fresh temporary directory. Python MCP resolution is constrained to the API lock because CI installs both environments together.
4. Run the Security and Tests workflow equivalents, including clean hash-verified installs, web/extension builds, extension type checks/tests, API/MCP unit and integration tests. Major SDK updates require compatibility checks beyond an audit pass.
5. Merge only after review and successful checks; rebuild/redeploy affected services separately. Updating this repository does not update an already deployed image.

Dependabot groups routine minor/patch updates to reduce repeated PR runs. Its Python manifest PRs still need the lock regeneration above before merging. Major upgrades stay separate for explicit review. Weekly scans remain enabled so newly published advisories are not missed.

## October 26 update

This patch updates the affected Next.js/Sentry/Zod and sanitization/parser dependencies, extension test/build tooling, and Python certificate/telemetry dependencies. Logfire 4.41 restricts the OpenTelemetry SDK below 1.45; resolving the OpenTelemetry API fix therefore requires the coordinated Logfire 5.4/SDK update, not an isolated API override. Review the generated locks and test results as a unit.
