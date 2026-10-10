"""Fetch and load the Wiefling RBA dataset from Zenodo.

See DECISIONS.md, "RBA dataset source: Zenodo, not Kaggle" and "Confirmed
Zenodo record contents": record 10.5281/zenodo.6782156 hosts exactly one
file, `rba-dataset.zip` (~1.09GB, MD5 cc1b1078b3929650e6c08678caffcc57), no
authentication required.

Hard requirement: on any failure (network, missing/renamed file, checksum
mismatch) this module raises and the pipeline halts. There is no
synthetic-benign fallback — see DECISIONS.md for why.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pandas as pd
import requests

logger = logging.getLogger("pulseguard.rba_loader")

ZENODO_API_BASE = "https://zenodo.org/api/records"
DEFAULT_RECORD_ID = "6782156"
EXPECTED_FILENAME = "rba-dataset.zip"
EXPECTED_MD5 = "cc1b1078b3929650e6c08678caffcc57"
DOWNLOAD_CHUNK_BYTES = 1024 * 1024  # 1 MiB streamed chunks, never load-to-memory

RBA_CSV_COLUMNS = [
    "index",
    "Login Timestamp",
    "User ID",
    "Round-Trip Time [ms]",
    "IP Address",
    "Country",
    "Region",
    "City",
    "ASN",
    "User Agent String",
    "Browser Name and Version",
    "OS Name and Version",
    "Device Type",
    "Login Successful",
    "Is Attack IP",
    "Is Account Takeover",
]


class RbaFetchError(RuntimeError):
    """Raised when the Zenodo fetch or checksum verification fails. This is
    intentionally NOT caught anywhere to trigger a fallback — the generator
    must halt (see DECISIONS.md)."""


@dataclass(frozen=True)
class RbaFileManifest:
    record_id: str
    filename: str
    url: str
    expected_md5: str
    actual_md5: str
    size_bytes: int
    downloaded_at: str


def _query_zenodo_file_list(record_id: str) -> dict:
    resp = requests.get(f"{ZENODO_API_BASE}/{record_id}", timeout=30)
    if resp.status_code != 200:
        raise RbaFetchError(
            f"Zenodo API returned {resp.status_code} for record {record_id}: {resp.text[:500]}"
        )
    data = resp.json()
    files = data.get("files", [])
    if not files:
        raise RbaFetchError(f"Zenodo record {record_id} has no files listed")
    return data


def _find_expected_file(record_data: dict) -> dict:
    for f in record_data["files"]:
        if f.get("key") == EXPECTED_FILENAME:
            return f
    available = [f.get("key") for f in record_data["files"]]
    raise RbaFetchError(
        f"Expected file '{EXPECTED_FILENAME}' not found in Zenodo record; "
        f"available files: {available}. The record layout may have changed — "
        "this must be investigated, not silently worked around."
    )


def _md5_of_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_rba_dataset(out_dir: Path, record_id: str = DEFAULT_RECORD_ID) -> RbaFileManifest:
    """Idempotent: if a file already exists at the destination with a
    matching checksum, skips re-downloading. Streams to disk — never loads
    the full file into memory."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / EXPECTED_FILENAME

    record_data = _query_zenodo_file_list(record_id)
    file_entry = _find_expected_file(record_data)
    checksum_field = file_entry.get("checksum", "")
    expected_md5 = checksum_field.split(":", 1)[1] if ":" in checksum_field else checksum_field
    if expected_md5 != EXPECTED_MD5:
        logger.warning(
            "Zenodo-reported checksum (%s) differs from the pinned constant (%s); "
            "using the live API value.",
            expected_md5,
            EXPECTED_MD5,
        )
    size_bytes = int(file_entry.get("size", 0))
    download_url = file_entry.get("links", {}).get("self") or file_entry.get("links", {}).get(
        "content"
    )
    if not download_url:
        raise RbaFetchError("Zenodo file entry has no download link")

    if dest.exists() and dest.stat().st_size == size_bytes:
        actual_md5 = _md5_of_file(dest)
        if actual_md5 == expected_md5:
            logger.info("RBA dataset already present and checksum-verified at %s", dest)
            return RbaFileManifest(
                record_id=record_id,
                filename=EXPECTED_FILENAME,
                url=download_url,
                expected_md5=expected_md5,
                actual_md5=actual_md5,
                size_bytes=size_bytes,
                downloaded_at=datetime.now(timezone.utc).isoformat(),
            )
        logger.warning("Existing file failed checksum verification; re-downloading.")

    logger.info("Downloading %s (%d bytes) from %s", EXPECTED_FILENAME, size_bytes, download_url)
    tmp_dest = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(download_url, stream=True, timeout=60) as resp:
            if resp.status_code != 200:
                raise RbaFetchError(f"Download failed with HTTP {resp.status_code}")
            with tmp_dest.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if chunk:
                        f.write(chunk)
    except requests.RequestException as exc:
        raise RbaFetchError(f"Network error while downloading RBA dataset: {exc}") from exc

    actual_md5 = _md5_of_file(tmp_dest)
    if actual_md5 != expected_md5:
        tmp_dest.unlink(missing_ok=True)
        raise RbaFetchError(
            f"Checksum mismatch after download: expected {expected_md5}, got {actual_md5}. "
            "The partial/corrupt file has been removed. No fallback will be used."
        )
    tmp_dest.replace(dest)
    logger.info("Download complete and checksum-verified: %s", dest)

    return RbaFileManifest(
        record_id=record_id,
        filename=EXPECTED_FILENAME,
        url=download_url,
        expected_md5=expected_md5,
        actual_md5=actual_md5,
        size_bytes=size_bytes,
        downloaded_at=datetime.now(timezone.utc).isoformat(),
    )


def write_manifest(manifest: RbaFileManifest, manifest_dir: Path) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / "rba_dataset_manifest.json"
    path.write_text(json.dumps(manifest.__dict__, indent=2), encoding="utf-8")
    return path


def _inner_csv_name(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise RbaFetchError(
                f"Expected exactly one CSV inside {zip_path.name}, found {csv_names}"
            )
        return csv_names[0]


def iter_rba_benign_rows(zip_path: Path, chunksize: int = 100_000) -> Iterator[pd.DataFrame]:
    """Chunked read of the RBA CSV, filtered to benign rows only (excludes
    rows flagged Is Attack IP / Is Account Takeover — see DECISIONS.md,
    "RBA dataset column mapping"). Never reads the full file into memory at
    once: this is a generator of DataFrame chunks.
    """
    inner_name = _inner_csv_name(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(inner_name) as f:
            for chunk in pd.read_csv(f, chunksize=chunksize, low_memory=False):
                benign = chunk[
                    (~chunk["Is Attack IP"].astype(bool))
                    & (~chunk["Is Account Takeover"].astype(bool))
                ]
                if not benign.empty:
                    yield benign


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-id", default=DEFAULT_RECORD_ID)
    parser.add_argument("--out", default="data/raw")
    parser.add_argument("--manifest-dir", default="data/manifests")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        manifest = fetch_rba_dataset(Path(args.out), record_id=args.record_id)
    except RbaFetchError as exc:
        logger.error("RBA_DATASET_FETCH_FAILED: %s", exc)
        return 1

    manifest_path = write_manifest(manifest, Path(args.manifest_dir))
    logger.info("Manifest written to %s", manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
