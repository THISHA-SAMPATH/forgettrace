"""
Walks the DataHub lineage graph downstream from every dataset that directly
contains a subject's data, collecting every derived copy — tables, dashboards,
ML features — so nothing gets missed when an erasure request comes in.

This is the part that's easy to get wrong: naive lineage walks loop forever on
cyclic graphs, double-count diamond-shaped dependency paths, and silently
trust broken/renamed lineage edges. This module handles all three.
"""

import datetime
from dataclasses import dataclass, field

from forgettrace.datahub_client import DataHubMCPClient

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


async def find_direct_matches(client: DataHubMCPClient, subject_column: str, subject_value: str) -> list[str]:
    """Find every dataset/table that directly contains the subject's identifier."""
    results = await client.search(query=f'"{subject_column}"', entity_types=["dataset"])
    entities = results.get("entities", results.get("results", []))
    return [e["urn"] for e in entities if "urn" in e]


async def walk_downstream(
    client: DataHubMCPClient,
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

    frontier: list[tuple[str, int, list[str]]] = [(urn, 0, [urn]) for urn in root_urns]

    for urn in root_urns:
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
        current_urn, current_hops, current_path = frontier.pop(0)
        if current_hops >= max_hops:
            issues.append(
                FlaggedIssue(
                    urn=current_urn,
                    issue=f"lineage traversal hit max_hops={max_hops} without terminating",
                    action_needed="manual review — graph may be deeper than configured limit",
                )
            )
            continue

        lineage = await client.get_lineage(current_urn, direction="downstream", max_hops=1)
        edges = lineage.get("edges", lineage.get("downstream", []))

        for edge in edges:
            child_urn = edge.get("urn") or edge.get("destination_urn")
            if not child_urn:
                continue

            last_observed = edge.get("last_observed") or edge.get("updated_at")
            edge_is_stale = _is_stale(last_observed)
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
                    stale=edge_is_stale,
                    confidence_score=_score(new_hops, edge_is_stale),
                )
            )
            frontier.append((child_urn, new_hops, new_path))

    return nodes, issues


def _is_stale(last_observed: str | None) -> bool:
    if not last_observed:
        return True  # no timestamp at all is itself worth flagging
    try:
        observed_dt = datetime.datetime.fromisoformat(last_observed.replace("Z", "+00:00"))
    except ValueError:
        return True
    age_days = (datetime.datetime.now(datetime.timezone.utc) - observed_dt).days
    return age_days > STALE_EDGE_DAYS
