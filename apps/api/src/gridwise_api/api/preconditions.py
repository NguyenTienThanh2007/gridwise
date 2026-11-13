"""ETag and If-Match: optimistic concurrency over HTTP (decision 0007, D5).

The ETag of a grid, its topology and each of its assets is the grid's version, as a strong
entity tag: ``"7"``. Every write must send ``If-Match`` with the version it read.

Accepted: exactly one strong tag holding a positive integer. Refused, with ``400``: a weak
tag (``W/"7"``, which never matches under the strong comparison writes need), a list, ``*``
(it would match any version and switch the check off), or anything else. A missing header
is ``428 Precondition Required``.
"""

import re

_STRONG_VERSION_TAG = re.compile(r'^"([1-9][0-9]{0,9})"$')


class PreconditionRequiredError(Exception):
    pass


class InvalidIfMatchError(Exception):
    pass


def etag(version: int) -> str:
    return f'"{version}"'


def expected_version(if_match: str | None) -> int:
    """The version the client expects to change, from its If-Match header."""
    if if_match is None or not if_match.strip():
        raise PreconditionRequiredError
    match = _STRONG_VERSION_TAG.match(if_match.strip())
    if match is None:
        raise InvalidIfMatchError
    return int(match.group(1))
