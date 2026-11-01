from uuid import UUID

import pytest

from forgettrace.auth import AuthenticationError, AuthenticatedUser
from forgettrace.rls import user_transaction


@pytest.mark.asyncio
async def test_rejects_missing_token():
    from forgettrace.auth import verify_supabase_access_token

    with pytest.raises(AuthenticationError):
        await verify_supabase_access_token("", "https://example.supabase.co")


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeConnection:
    def __init__(self):
        self.statements = []

    def transaction(self):
        return FakeTransaction()

    async def execute(self, query, *args):
        self.statements.append((query, args))


class FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *args):
        return False


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return FakeAcquire(self.connection)


@pytest.mark.asyncio
async def test_user_transaction_sets_role_and_transaction_local_claims():
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    claims = {"sub": str(user_id), "aud": "authenticated"}
    connection = FakeConnection()

    async with user_transaction(FakePool(connection), user_id, claims):
        pass

    assert connection.statements[0][0] == "SET LOCAL ROLE forgettrace_app"
    assert "request.jwt.claim.sub" in connection.statements[1][0]
    assert connection.statements[1][1] == (str(user_id),)
    assert "request.jwt.claims" in connection.statements[2][0]


@pytest.mark.asyncio
async def test_user_transaction_rejects_subject_mismatch():
    user_id = UUID("12345678-1234-5678-1234-567812345678")
    with pytest.raises(ValueError):
        async with user_transaction(FakePool(FakeConnection()), user_id, {"sub": "other"}):
            pass
