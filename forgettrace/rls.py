"""Transaction-scoped identity context for the ForgetTrace RLS database role."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from uuid import UUID


@asynccontextmanager
async def user_transaction(
    pool: Any, user_id: UUID, verified_claims: dict[str, Any]
) -> AsyncIterator[Any]:
    """Yield a transaction running as forgettrace_app with verified JWT claims.

    Call only after verify_supabase_access_token succeeds. Claims are set
    transaction-locally, so they are cleared automatically at transaction end.
    """
    if not isinstance(user_id, UUID):
        raise TypeError("user_id must be a UUID from a verified access token")
    if str(verified_claims.get("sub", "")) != str(user_id):
        raise ValueError("Verified claims subject does not match user_id")

    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("SET LOCAL ROLE forgettrace_app")
            claims_json = json.dumps(verified_claims, separators=(",", ":"))
            await connection.execute(
                "SELECT set_config('request.jwt.claim.sub', $1, true)",
                str(user_id),
            )
            await connection.execute(
                "SELECT set_config('request.jwt.claims', $1, true)",
                claims_json,
            )
            yield connection
