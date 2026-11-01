import pytest

from forgettrace.postgres_connector import (
    PostgresConnectorError,
    PostgresDataset,
    PostgresSubjectChecker,
)


class FakeCursor:
    def __init__(self, result=True):
        self.result = result
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchone(self):
        return (self.result,)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self._cursor


@pytest.mark.asyncio
async def test_subject_value_is_parameterised_and_match_is_confirmed():
    cursor = FakeCursor(result=True)
    checker = PostgresSubjectChecker(
        "postgresql://test",
        {
            "urn:dataset:customers": PostgresDataset(
                schema="public", table="customers", subject_columns=frozenset({"customer_id"})
            )
        },
        connect_factory=lambda dsn: FakeConnection(cursor),
    )

    found = await checker.contains_subject(
        "urn:dataset:customers", "customer_id", "C-100'")

    assert found is True
    assert 'FROM "public"."customers"' in cursor.query
    assert 'WHERE "customer_id" = %s' in cursor.query
    assert cursor.params == ("C-100'",)
    assert "C-100" not in cursor.query


@pytest.mark.asyncio
async def test_unmapped_dataset_fails_closed_without_connecting():
    checker = PostgresSubjectChecker("postgresql://test", {}, connect_factory=lambda _: None)
    with pytest.raises(PostgresConnectorError, match="not configured"):
        await checker.contains_subject("urn:unknown", "customer_id", "C-100")


@pytest.mark.asyncio
async def test_unapproved_subject_column_fails_closed():
    checker = PostgresSubjectChecker(
        "postgresql://test",
        {"urn:dataset:customers": PostgresDataset("public", "customers", frozenset({"customer_id"}))},
        connect_factory=lambda _: None,
    )
    with pytest.raises(PostgresConnectorError, match="not allowed"):
        await checker.contains_subject("urn:dataset:customers", "email", "a@example.test")


def test_dataset_mapping_requires_an_allow_list():
    with pytest.raises(ValueError, match="at least one"):
        PostgresDataset("public", "customers", frozenset())
