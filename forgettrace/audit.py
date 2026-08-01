"""
Turns a lineage walk into a signed, structured audit report — the artifact a
compliance/legal team could actually hand to a regulator as evidence of an
erasure request being handled, not just a debug dump of URNs.

The report is hashed (SHA-256) over its own canonical JSON so any downstream
edit is detectable — a cheap way to make the output "provable" rather than
just "printed."
"""

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from forgettrace.traversal import FlaggedIssue, LineageNode


def build_report(
    subject_column: str,
    subject_value: str,
    nodes: list[LineageNode],
    issues: list[FlaggedIssue],
    remediation_tasks: list[dict] | None = None,
) -> dict:
    report = {
        "request_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subject_column": subject_column,
        "subject_value": subject_value,
        "datasets_found": [asdict(n) for n in nodes],
        "flagged_issues": [asdict(i) for i in issues],
        "remediation_tasks": remediation_tasks or [],
        "summary": {
            "total_datasets_affected": len(nodes),
            "direct_matches": sum(1 for n in nodes if n.confidence == "direct_match"),
            "downstream_derived": sum(1 for n in nodes if n.confidence == "downstream_derived"),
            "issues_requiring_manual_review": len(issues),
            "open_remediation_tasks": len(remediation_tasks or []),
        },
    }
    report["signature"] = _sign(report)
    return report


def _sign(report: dict) -> str:
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_report(report: dict) -> bool:
    """Check whether a previously generated report has been tampered with."""
    stored_signature = report.get("signature")
    unsigned = {k: v for k, v in report.items() if k != "signature"}
    return _sign(unsigned) == stored_signature
