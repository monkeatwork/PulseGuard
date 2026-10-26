from __future__ import annotations

import json

import pandas as pd

from benchmark.release.build_release import build, verify


def _corpus(tmp_path):
    corpus = tmp_path / "generated"
    corpus.mkdir()
    ts = pd.date_range("2020-02-03", periods=6, freq="min", tz="UTC")
    df = pd.DataFrame({
        "event_id": [f"e{i}" for i in range(6)],
        "user_id": ["u1", "u1", "u1", "u2", "u2", "u2"],
        "ts": ts,
        "event_type": ["login_attempt", "mfa_prompt", "mfa_decision"] * 2,
        "decision": [None, None, "deny", None, None, "approve"],
        "label_attack": [False, True, True, False, False, False],
        "attack_profile": [None, "high_volume_burst", "high_volume_burst", None, None, None],
        "burst_id": [None, "b1", "b1", None, "b2", "b2"],
    })
    df.to_parquet(corpus / "events.parquet")
    (corpus / "manifest.json").write_text(json.dumps({
        "seed": 42, "requested_scale": 2, "actual_users": 2, "rows_scanned": 2,
        "profile_counts": {"plain_benign": 1, "high_volume_burst": 1}, "total_events": 6,
    }))
    return corpus


def test_bundle_verifies_and_carries_every_file(tmp_path):
    bundle = build(_corpus(tmp_path), tmp_path / "release")
    assert verify(bundle) == []
    names = {p.name for p in bundle.iterdir()}
    assert {"events.parquet", "splits.csv", "manifest.json", "DATASHEET.md", "LICENSE-DATA.md",
            "README.md", "CITATION.cff", ".zenodo.json", "SHA256SUMS"} <= names
    assert (bundle.parent / f"{bundle.name}.tar.gz").exists()
    sheet = (bundle / "DATASHEET.md").read_text()
    assert "{" not in sheet.replace("{{", "")  # every placeholder filled
    assert set(pd.read_csv(bundle / "splits.csv")["split"]) <= {"train", "val", "test"}


def test_verify_catches_tampering(tmp_path):
    bundle = build(_corpus(tmp_path), tmp_path / "release")
    (bundle / "README.md").write_text("changed")
    df = pd.read_parquet(bundle / "events.parquet")
    df.loc[2, "decision"] = "approve"
    df.to_parquet(bundle / "events.parquet")
    problems = verify(bundle)
    assert "checksum mismatch: README.md" in problems
    assert any(p.startswith("content_sha256 mismatch") for p in problems)
