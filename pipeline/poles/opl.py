"""osmium's OPL text format, enough to read relations: tags in the T field, members in the M field.
Special characters are written as %<hex codepoint>% (space is %20%, comma %2c%, equals %3d%)."""
from __future__ import annotations

import re

_ESC = re.compile(r"%([0-9a-fA-F]+)%")


def decode(s: str) -> str:
    return _ESC.sub(lambda m: chr(int(m.group(1), 16)), s)


def parse_tags(field: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    if not field:
        return tags
    for item in field.split(","):
        key, _, value = item.partition("=")
        tags[decode(key)] = decode(value)
    return tags


def parse_members(field: str) -> list[tuple[str, int, str]]:
    members = []
    if not field:
        return members
    for item in field.split(","):
        ref, _, role = item.partition("@")
        members.append((ref[0], int(ref[1:]), decode(role)))
    return members
