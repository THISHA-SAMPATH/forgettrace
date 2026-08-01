"""
Thin wrapper around the official DataHub MCP server (acryldata/mcp-server-datahub).

This spawns `mcp-server-datahub` as a subprocess over stdio (the standard MCP
transport) and exposes the handful of tool calls ForgetTrace needs:

  - search(query)                 -> find datasets/columns matching a keyword
  - get_entities(urns)             -> batch metadata fetch for specific URNs
  - get_lineage(urn, direction)    -> upstream/downstream lineage for an entity

Requires DATAHUB_GMS_URL and DATAHUB_GMS_TOKEN to be set in the environment,
pointing at a running DataHub instance (see README for Quickstart setup).
"""

import json
import os
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class DataHubMCPClient:
    def __init__(self, gms_url: str | None = None, gms_token: str | None = None):
        self.gms_url = gms_url or os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
        self.gms_token = gms_token or os.environ.get("DATAHUB_GMS_TOKEN", "")
        self._session: ClientSession | None = None
        self._stdio_ctx = None

    @asynccontextmanager
    async def connect(self):
        server_params = StdioServerParameters(
            command="uvx",
            args=["mcp-server-datahub"],
            env={
                "DATAHUB_GMS_URL": self.gms_url,
                "DATAHUB_GMS_TOKEN": self.gms_token,
            },
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self._session = session
                try:
                    yield self
                finally:
                    self._session = None

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> dict:
        if self._session is None:
            raise RuntimeError("DataHubMCPClient used outside of `async with client.connect()`")
        result = await self._session.call_tool(tool_name, arguments=arguments)
        # MCP tool results come back as a list of content blocks; the DataHub
        # server returns structured JSON as text content.
        for block in result.content:
            if getattr(block, "type", None) == "text":
                try:
                    return json.loads(block.text)
                except json.JSONDecodeError:
                    return {"raw": block.text}
        return {}

    async def search(self, query: str, entity_types: list[str] | None = None, limit: int = 20) -> dict:
        """Keyword search across DataHub, e.g. to find every dataset with a
        column matching a subject identifier (patient_id, customer_id, etc.)"""
        args: dict[str, Any] = {"query": query, "limit": limit}
        if entity_types:
            args["entity_types"] = entity_types
        return await self._call("search", args)

    async def get_entities(self, urns: list[str]) -> dict:
        """Batch metadata fetch — schema, ownership, tags — for a list of URNs."""
        return await self._call("get_entities", {"urns": urns})

    async def get_lineage(self, urn: str, direction: str = "downstream", max_hops: int = 5) -> dict:
        """Lineage traversal for a single entity. direction: 'upstream' | 'downstream'."""
        return await self._call(
            "get_lineage",
            {"urn": urn, "direction": direction, "max_hops": max_hops},
        )
