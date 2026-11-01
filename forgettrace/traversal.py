"""
Walks the DataHub lineage graph downstream from every dataset that directly
contains a subject's data, collecting every derived copy — tables, dashboards,
ML features — so nothing gets missed when an erasure request comes in.

This is the part that's easy to get wrong: naive lineage walks loop forever on
cyclic graphs, double-count diamond-shaped dependency paths, and silently
trust broken/renamed lineage edges. This module handles all three.
"""

import datetime
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol

STALE_EDGE_DAYS = 180  # lineage edges not observed/updated in this many days get flagged


@dataclass
class LineageNode:
    urn: str
    platform: str
    owner: str | None
    hops: int
    confidence: str  # "direct_match" | "downstream_derived"
    path: list[str] = field(default_factory=list)
    stale: bool = False
    confidence_score: float = 1.0  # 1.0 = certain, decays with hops + staleness


def _score(hops: int, stale: bool) -> float:
    """
    Direct matches are certain (1.0). Each hop downstream introduces a bit more
    uncertainty (metadata can lag reality), and a stale/unconfirmed edge along
    the path is a stronger signal that the path may no longer be accurate.
    Floor at 0.1 rather than 0 — a low score still means "found," just "verify."
    """
    base = 1.0 if hops == 0 else max(0.3, 1.0 - 0.15 * hops)
    if stale:
        base *= 0.5
    return round(max(base, 0.1), 2)


@dataclass
class FlaggedIssue:
    urn: str
    issue: str
    action_needed: str


class SubjectDataChecker(Protocol):
    """A connector that can check a subject value inside an authorised dataset."""

    async def contains_subject(self, urn: str, column: str, value: str) -> bool:
        ...


async def find_direct_matches(
    client,
    subject_column: str,
    subject_value: str,
    subject_checker: SubjectDataChecker | None = None,
) -> list[str]:
    """Return datasets proven to contain this subject's value.

    DataHub metadata search only discovers candidate datasets; it cannot prove
    that a particular row/value exists. A data connector must verify each
    candidate. This fail-closed requirement prevents metadata matches from
    being incorrectly reported as confirmed subject matches.
    """
    if subject_checker is None:
        raise RuntimeError(
            "Subject-level verification is not configured. DataHub metadata "
            "search can identify candidate datasets, but an authorised data "
            "connector is required to confirm the subject value."
        )

    results = await client.search(query=f'"{subject_column}"', entity_types=["dataset"])
    entities = results.get("entities", results.get("results", []))
    candidate_urns = list(dict.fromkeys(
        entity["urn"] for entity in entities
        if isinstance(entity, dict) and entity.get("urn")
    ))

    confirmed: list[str] = []
    for urn in candidate_urns:
        if await subject_checker.contains_subject(urn, subject_column, subject_value):
            confirmed.append(urn)
    return confirmed


async def walk_downstream(
    client,
    root_urns: list[str],
    max_hops: int = 6,
) -> tuple[list[LineageNode], list[FlaggedIssue]]:
    """
    BFS downstream from each root URN. Tracks visited URNs so diamond-shaped
    dependency graphs (A -> B -> D and A -> C -> D) don't get double-counted
    or cause infinite loops on cycles.
    """
    visited: set[str] = set()
    nodes: list[LineageNode] = []
    issues: list[FlaggedIssue] = []

    unique_roots = list(dict.fromkeys(root_urns))
    frontier = deque((urn, 0, [urn], False) for urn in unique_roots)

    for urn in unique_roots:
        visited.add(urn)
        entity = (await client.get_entities([urn])).get(urn, {})
        nodes.append(
            LineageNode(
                urn=urn,
                platform=entity.get("platform", "unknown"),
                owner=entity.get("owner"),
                hops=0,
                confidence="direct_match",
                path=[urn],
            )
        )

    while frontier:
        current_urn, current_hops, current_path, path_is_stale = frontier.popleft()
        lineage = await client.get_lineage(current_urn, direction="downstream", max_hops=1)
        edges = lineage.get("edges", lineage.get("downstream", []))

        # Only flag the depth boundary when there is actually another edge to
        # traverse. A leaf exactly at max_hops is a complete traversal, not an
        # incomplete one.
        if current_hops >= max_hops:
            if edges:
                issues.append(
                    FlaggedIssue(
                        urn=current_urn,
                        issue=f"lineage traversal reached max_hops={max_hops} with further descendants",
                        action_needed="manual review — increase the traversal limit or inspect remaining lineage",
                    )
                )
            continue

        for edge in edges:
            child_urn = edge.get("urn") or edge.get("destination_urn")
            if not child_urn:
                continue

            last_observed = edge.get("last_observed") or edge.get("updated_at")
            edge_is_stale = _is_stale(last_observed)
            new_path_is_stale = path_is_stale or edge_is_stale
            if edge_is_stale:
                issues.append(
                    FlaggedIssue(
                        urn=child_urn,
                        issue=f"lineage edge from {current_urn} not confirmed in over {STALE_EDGE_DAYS} days",
                        action_needed="manual verification before erasure — edge may no longer be accurate",
                    )
                )

            if child_urn in visited:
                continue  # already counted via another path — avoids double-count + cycles
            visited.add(child_urn)

            entity = (await client.get_entities([child_urn])).get(child_urn, {})
            new_path = current_path + [child_urn]
            new_hops = current_hops + 1
            nodes.append(
                LineageNode(
                    urn=child_urn,
                    platform=entity.get("platform", "unknown"),
                    owner=entity.get("owner"),
                    hops=new_hops,
                    confidence="downstream_derived",
                    path=new_path,
                    stale=new_path_is_stale,
                    confidence_score=_score(new_hops, new_path_is_stale),
                )
            )
            frontier.append((child_urn, new_hops, new_path, new_path_is_stale))

    return nodes, issues


def _is_stale(last_observed: str | None) -> bool:
    if not last_observed:
        return True  # no timestamp at all is itself worth flagging
    try:
        observed_dt = datetime.datetime.fromisoformat(last_observed.replace("Z", "+00:00"))
        if observed_dt.tzinfo is None:
            observed_dt = observed_dt.replace(tzinfo=datetime.timezone.utc)
        age_days = (datetime.datetime.now(datetime.timezone.utc) - observed_dt).days
    except (TypeError, ValueError):
        return True
    return age_days > STALE_EDGE_DAYS
