"""Validates format_cef's output against the ArcSight CEF spec structure:
`CEF:Version|Vendor|Product|Version|Signature ID|Name|Severity|Extension`,
using a small reference parser that respects backslash-escaped pipes in
header fields (per spec, `|` and `\\` must be escaped as `\\|`/`\\\\`
within a header field, but not the delimiter pipes themselves) -- exactly
the Phase 7 plan gate: "1000 sampled CEF lines parse cleanly."
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from pulseguard_common.cef import format_cef

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def parse_cef_header(line: str) -> list[str]:
    """Splits on unescaped `|` only -- a minimal reference CEF header
    parser, independent of format_cef's own escaping implementation."""
    fields = []
    current = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            current.append(line[i : i + 2])
            i += 2
            continue
        if ch == "|":
            fields.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    fields.append("".join(current))
    return fields


def test_format_cef_produces_8_pipe_delimited_header_fields_plus_extension():
    line = format_cef("T1621-01", "MFA fatigue detected", 8, "user1", "step_up_required", 0.93, T0)
    # header has 7 fields (CEF:Version, Vendor, Product, Version, Sig ID, Name, Severity),
    # the 8th split segment is the extension
    fields = parse_cef_header(line)
    assert len(fields) == 8
    assert fields[0] == "CEF:0"
    assert fields[1] == "PulseGuard"
    assert fields[6] == "8"


def test_format_cef_extension_is_well_formed_key_value_pairs():
    line = format_cef("T1621-01", "MFA fatigue detected", 8, "user1", "step_up_required", 0.93, T0)
    extension = parse_cef_header(line)[7]
    pairs = re.findall(r"(\w+)=([^\s]+(?:\s(?!\w+=)[^\s]+)*)", extension)
    keys = {k for k, _ in pairs}
    assert {"suser", "act", "cs1Label", "cs1", "rt"} <= keys


def test_format_cef_escapes_pipes_and_backslashes_in_header_fields():
    line = format_cef("Sig|With|Pipes", "Name\\With\\Backslash", 5, "user1", "step_up_required", 0.5, T0)
    fields = parse_cef_header(line)
    # the escaped pipes must NOT have split the field
    assert len(fields) == 8
    assert fields[4] == "Sig\\|With\\|Pipes"
    assert fields[5] == "Name\\\\With\\\\Backslash"


def test_format_cef_rejects_out_of_range_severity():
    with pytest.raises(ValueError):
        format_cef("T1621-01", "x", 11, "user1", "step_up_required", 0.5, T0)
    with pytest.raises(ValueError):
        format_cef("T1621-01", "x", -1, "user1", "step_up_required", 0.5, T0)


def test_1000_sampled_lines_all_parse_cleanly():
    """Phase 7 plan gate: 1000 sampled CEF lines parse with zero malformed
    entries."""
    lines = [
        format_cef(
            f"T1621-{i % 5}",
            f"MFA fatigue action {i}",
            severity=i % 11,
            user_id=f"user{i}",
            action="step_up_required" if i % 2 == 0 else "alt_factor_required",
            fused_score=(i % 100) / 100.0,
            timestamp=T0,
        )
        for i in range(1000)
    ]
    malformed = 0
    for line in lines:
        fields = parse_cef_header(line)
        if len(fields) != 8 or not fields[0].startswith("CEF:"):
            malformed += 1
    assert malformed == 0
