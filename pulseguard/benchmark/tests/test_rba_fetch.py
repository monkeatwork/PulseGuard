"""RBA dataset fetch: checksum verification and hard-failure behaviour.

Per DECISIONS.md ("RBA dataset source: Zenodo, not Kaggle"), there is no
synthetic-benign fallback — any fetch failure must raise RbaFetchError and
halt, never substitute fabricated data. These tests prove that contract.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from benchmark.generator.rba_loader import (
    DEFAULT_RECORD_ID,
    EXPECTED_FILENAME,
    EXPECTED_MD5,
    RbaFetchError,
    _find_expected_file,
    _query_zenodo_file_list,
    fetch_rba_dataset,
)


def test_zenodo_record_contains_expected_file_live():
    """Live check against the real Zenodo API (network required). Confirms
    the record layout this project pinned in DECISIONS.md still holds."""
    try:
        record_data = _query_zenodo_file_list(DEFAULT_RECORD_ID)
    except (RbaFetchError, requests.RequestException) as exc:
        pytest.skip(f"Zenodo unreachable in this environment: {exc}")

    file_entry = _find_expected_file(record_data)
    assert file_entry["key"] == EXPECTED_FILENAME
    checksum = file_entry["checksum"]
    actual_md5 = checksum.split(":", 1)[1] if ":" in checksum else checksum
    assert actual_md5 == EXPECTED_MD5


def test_missing_expected_file_raises():
    record_data = {"files": [{"key": "some-other-file.zip", "checksum": "md5:deadbeef"}]}
    with pytest.raises(RbaFetchError):
        _find_expected_file(record_data)


def test_zenodo_api_non_200_raises(tmp_path: Path):
    with patch("benchmark.generator.rba_loader.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404, text="not found")
        with pytest.raises(RbaFetchError):
            fetch_rba_dataset(tmp_path, record_id="nonexistent")


def test_checksum_mismatch_after_download_raises_and_removes_partial_file(tmp_path: Path):
    record_response = MagicMock(status_code=200)
    record_response.json.return_value = {
        "files": [
            {
                "key": EXPECTED_FILENAME,
                "checksum": f"md5:{EXPECTED_MD5}",
                "size": 12,
                "links": {"self": "https://example.invalid/rba-dataset.zip"},
            }
        ]
    }

    download_response = MagicMock(status_code=200)
    download_response.iter_content.return_value = [b"not-the-real-data"]
    download_response.__enter__ = lambda self: download_response
    download_response.__exit__ = lambda self, *a: None

    with patch("benchmark.generator.rba_loader.requests.get") as mock_get:
        mock_get.side_effect = [record_response, download_response]
        with pytest.raises(RbaFetchError, match="Checksum mismatch"):
            fetch_rba_dataset(tmp_path)

    assert not (tmp_path / EXPECTED_FILENAME).exists()
    assert not (tmp_path / (EXPECTED_FILENAME + ".part")).exists()


def test_network_error_raises_rba_fetch_error(tmp_path: Path):
    record_response = MagicMock(status_code=200)
    record_response.json.return_value = {
        "files": [
            {
                "key": EXPECTED_FILENAME,
                "checksum": f"md5:{EXPECTED_MD5}",
                "size": 12,
                "links": {"self": "https://example.invalid/rba-dataset.zip"},
            }
        ]
    }

    with patch("benchmark.generator.rba_loader.requests.get") as mock_get:
        mock_get.side_effect = [record_response, requests.ConnectionError("boom")]
        with pytest.raises(RbaFetchError):
            fetch_rba_dataset(tmp_path)
