from forgettrace.remediation import generate_tasks
from forgettrace.traversal import FlaggedIssue, LineageNode, _score


def test_direct_match_has_full_confidence():
    assert _score(hops=0, stale=False) == 1.0


def test_confidence_decays_with_hops():
    assert _score(hops=1, stale=False) > _score(hops=3, stale=False)


def test_stale_edge_halves_confidence():
    assert _score(hops=2, stale=True) == round(_score(hops=2, stale=False) * 0.5, 2)


def test_confidence_never_drops_below_floor():
    assert _score(hops=50, stale=True) >= 0.1


def test_remediation_task_generated_for_each_issue():
    issues = [FlaggedIssue(urn="urn:a", issue="stale edge", action_needed="verify")]
    tasks = generate_tasks(nodes=[], issues=issues)
    assert len(tasks) == 1
    assert tasks[0]["priority"] == "high"
    assert tasks[0]["urn"] == "urn:a"


def test_low_confidence_node_without_issue_still_gets_task():
    nodes = [
        LineageNode(
            urn="urn:b",
            platform="spark",
            owner="team-x",
            hops=5,
            confidence="downstream_derived",
            path=["urn:root", "urn:b"],
            confidence_score=0.3,
        )
    ]
    tasks = generate_tasks(nodes=nodes, issues=[])
    assert len(tasks) == 1
    assert tasks[0]["priority"] == "medium"


def test_no_duplicate_task_when_issue_and_low_confidence_overlap():
    urn = "urn:c"
    nodes = [
        LineageNode(
            urn=urn, platform="postgres", owner="team-y", hops=4,
            confidence="downstream_derived", path=["urn:root", urn], confidence_score=0.4,
        )
    ]
    issues = [FlaggedIssue(urn=urn, issue="stale", action_needed="verify")]
    tasks = generate_tasks(nodes=nodes, issues=issues)
    assert len(tasks) == 1  # not double-counted
