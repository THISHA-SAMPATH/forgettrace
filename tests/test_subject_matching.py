import pytest

from forgettrace.traversal import find_direct_matches


class FakeMetadataClient:
    async def search(self, query, entity_types=None):
        assert query == '"customer_id"'
        assert entity_types == ["dataset"]
        return {"entities": [
            {"urn": "urn:dataset:one"},
            {"urn": "urn:dataset:two"},
            {"urn": "urn:dataset:one"},
            {"name": "missing-urn"},
        ]}


class FakeSubjectChecker:
    async def contains_subject(self, urn, column, value):
        assert column == "customer_id"
        assert value == "C-100"
        return urn == "urn:dataset:two"


@pytest.mark.asyncio
async def test_only_subject_verified_candidates_are_returned():
    matches = await find_direct_matches(
        FakeMetadataClient(), "customer_id", "C-100", FakeSubjectChecker()
    )
    assert matches == ["urn:dataset:two"]


@pytest.mark.asyncio
async def test_subject_matching_fails_closed_without_data_connector():
    with pytest.raises(RuntimeError, match="authorised data connector"):
        await find_direct_matches(FakeMetadataClient(), "customer_id", "C-100")
