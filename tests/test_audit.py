from forgettrace.audit import build_report, verify_report
from forgettrace.traversal import FlaggedIssue, LineageNode


def _sample_nodes():
    return [
        LineageNode(
            urn="urn:li:dataset:(urn:li:dataPlatform:postgres,healthcare.patients,PROD)",
            platform="postgres",
            owner="data-eng-team",
            hops=0,
            confidence="direct_match",
            path=["urn:li:dataset:(urn:li:dataPlatform:postgres,healthcare.patients,PROD)"],
        )
    ]


def test_report_is_valid_when_untouched():
    report = build_report("patient_id", "P10432", _sample_nodes(), [])
    assert verify_report(report) is True


def test_report_is_invalid_after_tampering():
    report = build_report("patient_id", "P10432", _sample_nodes(), [])
    report["subject_value"] = "SOMEONE_ELSE"
    assert verify_report(report) is False


def test_summary_counts_are_correct():
    nodes = _sample_nodes() + [
        LineageNode(
            urn="urn:li:dataset:(urn:li:dataPlatform:spark,healthcare.enriched,PROD)",
            platform="spark",
            owner="analytics-team",
            hops=1,
            confidence="downstream_derived",
            path=["a", "b"],
        )
    ]
    issues = [FlaggedIssue(urn="x", issue="stale edge", action_needed="review")]
    report = build_report("patient_id", "P10432", nodes, issues)
    assert report["summary"]["total_datasets_affected"] == 2
    assert report["summary"]["direct_matches"] == 1
    assert report["summary"]["downstream_derived"] == 1
    assert report["summary"]["issues_requiring_manual_review"] == 1
