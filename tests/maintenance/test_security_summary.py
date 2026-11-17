import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("security_summary", Path(__file__).resolve().parents[2] / "tools/security-summary.py")
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)
GHSA = "GHSA-mfr8-8qww-v76h"
CVE = "CVE-2026-119790"


class SecuritySummaryTests(unittest.TestCase):
    def test_same_advisory_across_scanners_and_alias_bridge(self):
        rows = [({GHSA}, {"next"}, "npm-web.json"), ({CVE}, set(), "osv.sarif"), ({GHSA, CVE}, {"next"}, "pip-api.json")]
        groups = summary.group_findings(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["ids"], sorted([GHSA, CVE]))
        self.assertEqual(len(groups[0]["sources"]), 3)

    def test_identifiers_are_case_normalized(self):
        self.assertEqual(summary.identifiers([GHSA.upper(), CVE.lower()]), {GHSA, CVE})

    def test_cancelled_scan_does_not_look_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            report = summary.summarize(Path(directory), {"osv-scan": {"result": "cancelled"}})
            self.assertEqual(report["unsuccessful_jobs"], ["osv-scan"])

    def test_distinct_advisories_not_grouped_just_for_same_package(self):
        self.assertEqual(len(summary.group_findings([({GHSA}, {"next"}, "npm"), ({"CVE-2026-99999"}, {"next"}, "deno")])), 2)

    def test_three_formats_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "npm-web.json").write_text(json.dumps({"vulnerabilities": {"next": {"via": [{"name": "next", "url": "https://github.com/advisories/" + GHSA}]}}}))
            (root / "osv.sarif").write_text(json.dumps({"runs": [{"results": [{"ruleId": GHSA, "message": {"text": CVE}}]}]}))
            (root / "deno-web.log").write_text(f"╭ Information disclosure\n│ Package: next\n╰ Info: https://github.com/advisories/{GHSA}\nFound 1 vulnerabilities")
            report = summary.summarize(root, {})
            self.assertEqual(len(report["groups"]), 1)
            self.assertEqual(len(report["groups"][0]["sources"]), 3)
            self.assertTrue(report["warnings"])  # missing other reports cannot look clean

    def test_missing_malformed_and_failed_scans_not_clean(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "npm-web.json").write_text("not json")
            (root / "deno-web.log").write_text("error: registry unavailable")
            report = summary.summarize(root, {"npm-audit": {"result": "failure"}})
            self.assertGreater(len(report["warnings"]), 2)
            self.assertEqual(report["unsuccessful_jobs"], ["npm-audit"])
            self.assertIn("Do not interpret an empty list as clean", summary.markdown(report))

    def test_clean_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in summary.EXPECTED:
                if name.startswith("npm-"):
                    value = '{"vulnerabilities": {}}'
                elif name.startswith("pip-"):
                    value = '{"dependencies": []}'
                elif name.endswith("sarif"):
                    value = '{"runs": [{"results": []}]}'
                else:
                    value = 'No vulnerabilities found'
                (root / name).write_text(value)
            report = summary.summarize(root, {"pip-audit": {"result": "success"}})
            self.assertEqual(report["warnings"], [])
            self.assertEqual(report["groups"], [])

    def test_unknown_pip_ids_and_skipped_dependencies_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pip-api.json"
            for dep in [{"name": "x", "skip_reason": "unsupported"}, {"name": "x", "vulns": [{"id": "NEW-123"}]}]:
                path.write_text(json.dumps({"dependencies": [dep]}))
                with self.assertRaises(ValueError):
                    summary.findings(path)


if __name__ == "__main__":
    unittest.main()
