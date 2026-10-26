"""Benchmark release bundle (Zenodo-ready).

Packages a generated corpus (`make generate` output) into a self-describing
directory and a .tar.gz next to it:

  events.parquet     the corpus, unchanged
  splits.csv         user_id -> train/val/test (the by-user split every
                     reported number uses)
  manifest.json      generator manifest + content hash + code revision
  DATASHEET.md       Gebru et al. datasheet, with this corpus's numbers
  LICENSE-DATA.md    CC BY 4.0 and base-dataset attribution
  README.md          schema, loading, verification
  CITATION.cff, .zenodo.json
  SHA256SUMS         every file above

`content_sha256` hashes the rows (pandas.util.hash_pandas_object), so it
survives a different parquet writer; SHA256SUMS covers the exact bytes.

Usage:
    python -m benchmark.release.build_release --corpus data/generated --out data/release
    python -m benchmark.release.build_release --verify data/release/pulseguard-mfa-fatigue-v1.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pandas as pd

from eval.harness.split import assign_split

HERE = Path(__file__).parent
NAME = "pulseguard-mfa-fatigue"
VERSION = "1.0"
BASE_DOI = "10.5281/zenodo.6782156"
CHECKSUMS = "SHA256SUMS"
# Filled in by the authors before upload; build refuses nothing, verify ignores them.
AUTHORS_PLACEHOLDER = [{"name": "TODO: author list", "affiliation": "VIT University, SCOPE"}]


def content_sha256(df: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _git_revision() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def stats_section(df: pd.DataFrame, manifest: dict) -> str:
    dec = df[df["event_type"] == "mfa_decision"]
    episodes = df[df["burst_id"].notna()].groupby("burst_id").agg(
        attack=("label_attack", "first"), profile=("attack_profile", "first")
    )
    lines = [
        "**Size.**",
        "",
        "| | Count |",
        "|---|---|",
        f"| Users | {df['user_id'].nunique():,} |",
        f"| Events | {len(df):,} |",
        f"| Labelled episodes | {len(episodes):,} ({int(episodes['attack'].sum()):,} attack, "
        f"{int((~episodes['attack'].astype(bool)).sum()):,} benign) |",
        f"| MFA decisions | {len(dec):,} ({int((dec['decision'] == 'deny').sum()):,} deny) |",
        f"| Time span | {df['ts'].min():%Y-%m-%d} to {df['ts'].max():%Y-%m-%d} |",
        "",
        "**Users per generator profile** (from the manifest):",
        "",
        "| Profile | Users |",
        "|---|---|",
        *(f"| `{k}` | {v:,} |" for k, v in manifest.get("profile_counts", {}).items()),
    ]
    return "\n".join(lines)


def readme(manifest: dict) -> str:
    return f"""# {NAME} v{VERSION}

Labelled MFA-fatigue (push-bombing) benchmark: {manifest['actual_users']:,} users,
{manifest['total_events']:,} events, seed {manifest['seed']}. See `DATASHEET.md`
for what is real and what is generated.

## Schema (`events.parquet`, one row per event)

| Column | Type | Meaning |
|---|---|---|
| `event_id` | str | Event identifier |
| `user_id` | str | User (from the base dataset) |
| `ts` | timestamp (UTC) | Event time |
| `event_type` | str | `login_attempt`, `mfa_prompt` or `mfa_decision` |
| `decision` | str | `approve` / `deny` on `mfa_decision`, else empty |
| `decision_latency_ms` | float | Prompt-to-decision time on `mfa_decision` |
| `src_ip`, `geo_country`, `device_id`, `user_agent` | str | Login context |
| `session_id` | str | Generator session |
| `ingest_ts` | timestamp (UTC) | Ingestion time (equal to `ts` here) |
| `label_attack` | bool | Event belongs to an attack episode |
| `attack_profile` | str | Attack type, empty if benign |
| `burst_id` | str | Episode identifier, empty for plain base-dataset logins |

## Evaluate the way the reported numbers do

Join `splits.csv` on `user_id`, train on `train`, tune on `val`, report on
`test`. Score per episode (`burst_id`): an episode counts as detected if the
detector fires at any of its decisions.

```python
import pandas as pd
events = pd.read_parquet("events.parquet")
splits = pd.read_csv("splits.csv", dtype={{"user_id": str}})
events = events.merge(splits, on="user_id")
```

## Verify

```
sha256sum -c SHA256SUMS
python -m benchmark.release.build_release --verify .   # also checks content_sha256
```

Regenerate from the code (revision `{manifest.get('code_revision') or 'unknown'}`) with
`make generate SEED={manifest['seed']}`; the content hash must match.

## License

CC BY 4.0, see `LICENSE-DATA.md`. Cite this corpus and the base dataset
(doi:{BASE_DOI}); see `CITATION.cff`.
"""


def citation() -> str:
    authors = "\n".join(f'  - name: "{a["name"]}"' for a in AUTHORS_PLACEHOLDER)
    return f"""cff-version: 1.2.0
message: "If you use this benchmark, cite it and the base dataset."
title: "PulseGuard MFA-fatigue benchmark"
version: "{VERSION}"
license: CC-BY-4.0
type: dataset
authors:
{authors}
references:
  - type: dataset
    title: "Login Data Set for Risk-Based Authentication"
    doi: "{BASE_DOI}"
    authors:
      - family-names: Wiefling
        given-names: Stephan
      - family-names: Jørgensen
        given-names: Paul René
      - family-names: Thunem
        given-names: Sigurd
      - family-names: Lo Iacono
        given-names: Luigi
    year: 2022
"""


def zenodo_metadata() -> dict:
    return {
        "title": f"PulseGuard MFA-fatigue benchmark v{VERSION}",
        "upload_type": "dataset",
        "version": VERSION,
        "license": "cc-by-4.0",
        "creators": AUTHORS_PLACEHOLDER,
        "description": (
            "Labelled benchmark for detecting MFA fatigue (push-bombing, MITRE ATT&CK T1621): benign "
            "login behaviour from the Wiefling RBA dataset with generated MFA prompt/decision streams, "
            "three attack profiles and benign hard negatives. Includes a by-user train/val/test split "
            "and a datasheet. Decisions and latencies are synthetic; see DATASHEET.md."
        ),
        "keywords": ["MFA fatigue", "push bombing", "T1621", "authentication", "intrusion detection", "benchmark"],
        "related_identifiers": [{"identifier": BASE_DOI, "relation": "isDerivedFrom", "scheme": "doi"}],
    }


def build(corpus_dir: Path, out_root: Path) -> Path:
    manifest = json.loads((corpus_dir / "manifest.json").read_text())
    df = pd.read_parquet(corpus_dir / "events.parquet")
    out = out_root / f"{NAME}-v{VERSION}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    shutil.copyfile(corpus_dir / "events.parquet", out / "events.parquet")
    seed = int(manifest["seed"])
    users = sorted(df["user_id"].unique())
    pd.DataFrame({"user_id": users, "split": [assign_split(seed, u) for u in users]}).to_csv(out / "splits.csv", index=False)

    manifest = {
        **manifest,
        "name": NAME,
        "version": VERSION,
        "content_sha256": content_sha256(df),
        "code_revision": _git_revision(),
        "split_rule": "by user: MD5(seed, user_id), 70/15/15 train/val/test (eval/harness/split.py)",
        "base_dataset_doi": BASE_DOI,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    fatigue = manifest.get("fatigue") or {}
    (out / "DATASHEET.md").write_text(
        (HERE / "DATASHEET.md").read_text()
        .replace("{version}", VERSION)
        .replace("{stats}", stats_section(df, manifest))
        .replace("{users}", f"{manifest['actual_users']:,}")
        .replace("{rows_scanned}", f"{manifest['rows_scanned']:,}")
        .replace("{seed}", str(seed))
        .replace("{benign_source}", fatigue.get("benign_source", "legacy"))
    )
    shutil.copyfile(HERE / "LICENSE-DATA.md", out / "LICENSE-DATA.md")
    (out / "README.md").write_text(readme(manifest))
    (out / "CITATION.cff").write_text(citation())
    (out / ".zenodo.json").write_text(json.dumps(zenodo_metadata(), indent=2, ensure_ascii=False))

    files = sorted(p for p in out.iterdir() if p.name != CHECKSUMS)
    (out / CHECKSUMS).write_text("".join(f"{file_sha256(p)}  {p.name}\n" for p in files))

    archive = out_root / f"{out.name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(out, arcname=out.name)
    return out


def verify(bundle: Path) -> list[str]:
    """Problems found in a bundle; empty if it checks out."""
    problems = []
    for line in (bundle / CHECKSUMS).read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        path = bundle / name
        if not path.exists():
            problems.append(f"missing: {name}")
        elif file_sha256(path) != digest:
            problems.append(f"checksum mismatch: {name}")
    manifest = json.loads((bundle / "manifest.json").read_text())
    if content_sha256(pd.read_parquet(bundle / "events.parquet")) != manifest["content_sha256"]:
        problems.append("content_sha256 mismatch: events.parquet rows differ from the manifest")
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", default="data/generated")
    parser.add_argument("--out", default="data/release")
    parser.add_argument("--verify", metavar="BUNDLE_DIR")
    args = parser.parse_args(argv)
    if args.verify:
        problems = verify(Path(args.verify))
        print("\n".join(problems) or "OK")
        return 1 if problems else 0
    out = build(Path(args.corpus), Path(args.out))
    print(f"{out}\n{out}.tar.gz")
    return 0


if __name__ == "__main__":
    sys.exit(main())
