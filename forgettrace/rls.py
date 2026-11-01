
"""Transaction-scoped identity context for ForgetTrace RLS."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from uuid import UUID


@asynccontextmanager
async def user_transaction(
    pool: Any,
    user_id: UUID,
    verified_claims: dict[str, Any],
) -> AsyncIterator[Any]:
    """
    Yield a database connection running as forgettrace_app.

    IMPORTANT:
    verified_claims must come directly from a successfully verified
    Supabase access token. Never accept claims supplied by the frontend.
    """

    if not isinstance(user_id, UUID):
        raise TypeError(
            "user_id must be a UUID from a verified access token"
        )

    if not isinstance(verified_claims, dict):
        raise TypeError("verified_claims must be a dictionary")

    if str(verified_claims.get("sub", "")) != str(user_id):
        raise ValueError(
            "Verified claims subject does not match user_id"
        )

    async with pool.acquire() as connection:
        async with connection.transaction():

            # Switch to the restricted application role.
            await connection.execute(
                "SET LOCAL ROLE forgettrace_app"
            )

            # Store verified identity claims transaction-locally.
            claims_json = json.dumps(
                verified_claims,
                separators=(",", ":"),
            )

            await connection.execute(
                "SELECT set_config("
                "'request.jwt.claim.sub', $1, true)",
                str(user_id),
            )

            await connection.execute(
                "SELECT set_config("
                "'request.jwt.claims', $1, true)",
                claims_json,
            )

            yield connection
