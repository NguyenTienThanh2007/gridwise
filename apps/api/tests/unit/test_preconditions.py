import pytest

from gridwise_api.api.preconditions import (
    InvalidIfMatchError,
    PreconditionRequiredError,
    etag,
    expected_version,
)


@pytest.mark.parametrize("version", [1, 2, 99, 9_999_999_999])
def test_an_etag_is_read_back_as_its_version(version: int) -> None:
    assert expected_version(etag(version)) == version


def test_surrounding_whitespace_is_tolerated() -> None:
    assert expected_version('  "3" ') == 3


@pytest.mark.parametrize("value", [None, "", "   "])
def test_a_missing_header_is_a_missing_precondition(value: str | None) -> None:
    with pytest.raises(PreconditionRequiredError):
        expected_version(value)


@pytest.mark.parametrize(
    "value",
    ["*", 'W/"3"', '"3", "4"', "3", '"three"', '""', '"0"', '"-1"', '"03"', '"3', "'3'"],
)
def test_anything_but_one_strong_version_tag_is_invalid(value: str) -> None:
    with pytest.raises(InvalidIfMatchError):
        expected_version(value)
