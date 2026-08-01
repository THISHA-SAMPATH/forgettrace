"""
Turns raw findings (flagged issues, low-confidence nodes) into a concrete task
queue — "verify this edge before erasure", "notify this owner" — so the output
of a trace is something a team can act on directly, not just a report to read.
"""

from dataclasses import asdict, dataclass

from forgettrace.traversal import FlaggedIssue, LineageNode

LOW_CONFIDENCE_THRESHOLD = 0.6


@dataclass
class RemediationTask:
    task_id: str
    urn: str
    owner: str | None
    priority: str  # "high" | "medium"
    action: str
    reason: str


def generate_tasks(nodes: list[LineageNode], issues: list[FlaggedIssue]) -> list[dict]:
    tasks: list[RemediationTask] = []
    seen_urns: set[str] = set()

    # One task per flagged issue — these are the clearest, most specific cases.
    for i, issue in enumerate(issues):
        tasks.append(
            RemediationTask(
                task_id=f"rem-{i:03d}",
                urn=issue.urn,
                owner=_owner_for(issue.urn, nodes),
                priority="high",
                action=issue.action_needed,
                reason=issue.issue,
            )
        )
        seen_urns.add(issue.urn)

    # Additionally flag any node with a low confidence score that didn't
    # already get a task from the issues list above.
    for node in nodes:
        if node.urn in seen_urns:
            continue
        if node.confidence_score < LOW_CONFIDENCE_THRESHOLD:
            tasks.append(
                RemediationTask(
                    task_id=f"rem-{len(tasks):03d}",
                    urn=node.urn,
                    owner=node.owner,
                    priority="medium",
                    action="review lineage path before treating erasure as complete",
                    reason=f"confidence score {node.confidence_score} at {node.hops} hop(s) downstream",
                )
            )
            seen_urns.add(node.urn)

    return [asdict(t) for t in tasks]


def _owner_for(urn: str, nodes: list[LineageNode]) -> str | None:
    for node in nodes:
        if node.urn == urn:
            return node.owner
    return None
