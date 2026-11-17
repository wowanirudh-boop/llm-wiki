#!/usr/bin/env python3
"""Group scanner evidence for humans; never replaces scanners' exit status.

Deno currently has no documented JSON audit output. Keep its original log and
extract the advisory links, while preserving unreadable/incomplete report warnings.
"""
import argparse
import html
import json
import os
from pathlib import Path
import re

IDS = re.compile(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}|CVE-\d{4}-\d{4,}", re.I)
EXPECTED = {"osv.sarif", "npm-web.json", "npm-extension.json", "deno-web.log", *[f"pip-{p}.json" for p in ("api", "mcp", "converter", "tests")]}


def identifiers(value):
    return {item.upper() if item.upper().startswith("CVE-") else "GHSA-" + item[5:].lower()
            for item in IDS.findall(json.dumps(value))}


def findings(path):
    """Return (alias identifiers, packages, source) tuples; reject unknown formats."""
    source = path.name
    if source == "deno-web.log":
        text = re.sub(r"\x1b\[[0-9;]*m", "", path.read_text())
        rows = []
        for block in text.split("╭")[1:]:
            ids = identifiers(block)
            package = re.search(r"Package:\s+(\S+)", block)
            if ids:
                rows.append((ids, {package[1]} if package else set(), source))
        if not rows and not re.search(r"(?:No (?:known )?vulnerabilities|Found 0 vulnerabilities|0 vulnerabilities)", text, re.I):
            raise ValueError("Deno report has no recognizable findings or clean result")
        return rows
    data = json.loads(path.read_text())
    if source.startswith("npm-"):
        if "error" in data or not isinstance(data.get("vulnerabilities"), dict):
            raise ValueError("npm report is an error or unsupported format")
        rows = []
        for name, package in data["vulnerabilities"].items():
            for advisory in package.get("via", []):
                if isinstance(advisory, dict):
                    ids = identifiers(advisory.get("url", ""))
                    if not ids:
                        raise ValueError("npm finding has no advisory identifier")
                    rows.append((ids, {advisory.get("name", name)}, source))
        if data["vulnerabilities"] and not rows:
            raise ValueError("npm vulnerabilities present without readable advisory details")
        return rows
    if source.startswith("pip-"):
        if not isinstance(data.get("dependencies"), list):
            raise ValueError("unsupported pip-audit format")
        rows = []
        for dep in data["dependencies"]:
            if "skip_reason" in dep:
                raise ValueError("pip-audit skipped a dependency")
            for advisory in dep.get("vulns", []):
                ids = identifiers([advisory.get("id"), advisory.get("aliases", [])])
                if not ids:
                    raise ValueError("pip finding has no recognized advisory identifier")
                rows.append((ids, {dep["name"]}, source))
        return rows
    if source == "osv.sarif":
        if not isinstance(data.get("runs"), list):
            raise ValueError("unsupported SARIF format")
        rows = []
        for run in data["runs"]:
            rules = {r["id"]: r for r in run.get("tool", {}).get("driver", {}).get("rules", [])}
            for result in run.get("results", []):
                rule = rules.get(result.get("ruleId"), {})
                # Rule metadata carries aliases. Do not mine unrelated findings.
                ids = identifiers([result.get("ruleId"), result.get("message"), rule])
                if not ids:
                    raise ValueError("OSV result has no recognized advisory identifier")
                rows.append((ids, set(), source))
        return rows
    raise ValueError("unknown report")


def group_findings(rows):
    groups = []
    for ids, packages, source in rows:
        merged = {"ids": set(ids), "packages": set(packages), "sources": {source}}
        # Alias bridges can join more than one previously separate group.
        rest = []
        for group in groups:
            if merged["ids"] & group["ids"]:
                for key in merged:
                    merged[key].update(group[key])
            else:
                rest.append(group)
        groups = rest + [merged]
    return sorted(({k: sorted(v) for k, v in g.items()} for g in groups), key=lambda g: g["ids"])


def summarize(directory, jobs):
    reports = {p.name: p for p in directory.rglob("*") if p.is_file() and p.name in EXPECTED}
    warnings = [f"Missing report: {name}" for name in sorted(EXPECTED - reports.keys())]
    rows = []
    for name, path in sorted(reports.items()):
        try:
            rows.extend(findings(path))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            warnings.append(f"Unreadable report {name}: {exc}")
    failed = [name for name, value in jobs.items() if value.get("result") not in ("success", "skipped")]
    return {"groups": group_findings(rows), "warnings": warnings, "unsuccessful_jobs": failed, "reports_received": sorted(reports)}


def markdown(report):
    lines = ["## Consolidated security findings", "", "Duplicate scanner observations are grouped by advisory aliases. Original scan checks remain authoritative; this does not suppress findings or notifications.", ""]
    if report["warnings"] or report["unsuccessful_jobs"]:
        lines += ["**Scan/reporting incomplete or unsuccessful. Do not interpret an empty list as clean.**", ""]
    lines += [f"Unique advisory groups in readable reports: **{len(report['groups'])}**", ""]
    for group in report["groups"]:
        clean = lambda values: html.escape(", ".join(values)).replace("\n", " ")
        lines += [f"- **{clean(group['ids'])}**; packages: {clean(group['packages']) or 'see scanner report'}; seen in: {clean(group['sources'])}"]
    if report["unsuccessful_jobs"]:
        lines += ["", "Unsuccessful scanner jobs: " + ", ".join(report["unsuccessful_jobs"])]
    lines += ["", *["- " + html.escape(w) for w in report["warnings"]]]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", type=Path)
    parser.add_argument("--json-output", type=Path, default=Path("security-summary.json"))
    args = parser.parse_args()
    report = summarize(args.reports, json.loads(os.environ.get("SCAN_JOBS", "{}")))
    args.json_output.write_text(json.dumps(report, indent=2) + "\n")
    output = markdown(report)
    print(output)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(output)
    return int(bool(report["warnings"] or report["unsuccessful_jobs"]))


if __name__ == "__main__":
    raise SystemExit(main())
