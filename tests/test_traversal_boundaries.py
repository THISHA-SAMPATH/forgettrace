from datetime import datetime, timezone

import pytest

from forgettrace.traversal import _is_stale, walk_downstream


class FakeLineageClient:
    def __init__(self, graph):
        self.graph = graph

    async def get_entities(self, urns):
        return {urn: {"platform": "test", "owner": "team"} for urn in urns}

    async def get_lineage(self, urn, direction="downstream", max_hops=1):
        return {"edges": self.graph.get(urn, [])}


@pytest.mark.asyncio
async def test_leaf_at_max_hops_is_not_flagged_as_incomplete():
    client = FakeLineageClient({
        "root": [{"urn": "child", "last_observed": datetime.now(timezone.utc).isoformat()}],
        "child": [],
    })
    nodes, issues = await walk_downstream(client, ["root"], max_hops=1)
    assert [node.urn for node in nodes] == ["root", "child"]
    assert issues == []


@pytest.mark.asyncio
async def test_descendants_beyond_max_hops_are_flagged():
    client = FakeLineageClient({
        "root": [{"urn": "child", "last_observed": datetime.now(timezone.utc).isoformat()}],
        "child": [{"urn": "grandchild", "last_observed": datetime.now(timezone.utc).isoformat()}],
    })
    nodes, issues = await walk_downstream(client, ["root"], max_hops=1)
    assert [node.urn for node in nodes] == ["root", "child"]
    assert len(issues) == 1
    assert issues[0].urn == "child"


def test_naive_iso_timestamp_is_treated_as_utc():
    recent_naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    assert _is_stale(recent_naive) is False


@pytest.mark.asyncio
async def test_duplicate_roots_are_only_added_once_async():
    client = FakeLineageClient({"root": []})
    nodes, issues = await walk_downstream(client, ["root", "root"], max_hops=2)
    assert len(nodes) == 1
    assert issues == []
