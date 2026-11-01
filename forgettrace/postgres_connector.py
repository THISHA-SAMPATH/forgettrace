"""Read-only PostgreSQL subject verification for explicitly mapped datasets.

The connector never discovers arbitrary tables. A dataset URN must be mapped by
an operator to a schema/table, and the requested subject column must be in that
mapping's allow-list. Subject values are passed separately as query parameters.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Mapping


class PostgresConnectorError(RuntimeError):
    """A safe, non-sensitive error raised by the PostgreSQL connector."""


@dataclass(frozen=True)
class PostgresDataset:
    """Allow-listed PostgreSQL location for one DataHub dataset URN."""

    schema: str
    table: str
    subject_columns: frozenset[str]

    def __post_init__(self) -> None:
        for label, value in (("schema", self.schema), ("table", self.table)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label} must be a non-empty string")
        if not self.subject_columns:
            raise ValueError("subject_columns must contain at least one allowed column")
        if any(not isinstance(column, str) or not column.strip() for column in self.subject_columns):
            raise ValueError("subject column names must be non-empty strings")


class PostgresSubjectChecker:
    """Check subject values in mapped PostgreSQL tables using read-only queries.

    Args:
        dsn: PostgreSQL connection string. Prefer loading it from an environment
            variable rather than placing credentials in source code.
        datasets: Mapping of DataHub dataset URNs to explicit table allow-lists.
        connect_factory: Optional connection factory, primarily for testing.

    The database role used by this connector should have SELECT permission only
    on the mapped tables. This class does not perform deletion or modification.
    """

    def __init__(
        self,
        dsn: str,
        datasets: Mapping[str, PostgresDataset],
        connect_factory: Callable[[str], Any] | None = None,
    ) -> None:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("A PostgreSQL DSN is required")
        self._dsn = dsn
        self._datasets = dict(datasets)
        self._connect_factory = connect_factory

    async def contains_subject(self, urn: str, column: str, value: str) -> bool:
        """Return whether the exact value exists in an allow-listed table."""
        # Run the blocking database driver away from the event loop.
        return await asyncio.to_thread(self._contains_subject_sync, urn, column, value)

    def _contains_subject_sync(self, urn: str, column: str, value: str) -> bool:
        dataset = self._datasets.get(urn)
        if dataset is None:
            raise PostgresConnectorError(
                "Dataset is not configured in the PostgreSQL connector allow-list."
            )
        if column not in dataset.subject_columns:
            raise PostgresConnectorError(
                "Subject column is not allowed for this configured dataset."
            )
        if not isinstance(value, str) or not value:
            raise ValueError("Subject value must be a non-empty string")

        # Identifiers cannot be passed as SQL parameters. Quote each allow-listed
        # identifier safely; the subject value remains a separate bound parameter.
        table_name = (
            f"{_quote_identifier(dataset.schema)}."
            f"{_quote_identifier(dataset.table)}"
        )
        column_name = _quote_identifier(column)
        query = (
            f"SELECT EXISTS (SELECT 1 FROM {table_name} "
            f"WHERE {column_name} = %s LIMIT 1)"
        )

        try:
            connection = self._connect()
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(query, (value,))
                    result = cursor.fetchone()
            return bool(result and result[0])
        except PostgresConnectorError:
            raise
        except Exception as exc:
            # Do not include driver exception text: it may contain connection
            # details or query context. The original exception remains chained
            # for controlled debugging, but callers get a safe public message.
            raise PostgresConnectorError(
                "PostgreSQL subject verification failed. Check connector access and database availability."
            ) from exc

    def _connect(self) -> Any:
        if self._connect_factory is not None:
            return self._connect_factory(self._dsn)
        try:
            import psycopg
        except ImportError as exc:
            raise PostgresConnectorError(
                "PostgreSQL support is optional. Install ForgetTrace with: pip install -e .[postgres]"
            ) from exc
        return psycopg.connect(self._dsn, connect_timeout=5)


def _quote_identifier(identifier: str) -> str:
    """Quote one PostgreSQL identifier, escaping embedded double quotes."""
    return '"' + identifier.replace('"', '""') + '"'
