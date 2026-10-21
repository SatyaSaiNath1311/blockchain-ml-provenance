"""Tests for GET /datasets and POST /versions/{version_id}/tamper-demo.

All tests use isolated temporary storage so they never touch real storage.
"""

import hashlib
import io
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Route all storage to a fresh tmp directory; never touch real storage."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    yield tmp_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload_csv(content: bytes = b"a,b,label\n1,2,0\n3,4,1\n5,6,0\n7,8,1\n") -> dict:
    resp = client.post(
        "/datasets",
        files={"file": ("sample.csv", io.BytesIO(content), "text/csv")},
        data={"chunk_rows": "2"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# GET /datasets – list datasets
# ---------------------------------------------------------------------------

def test_list_datasets_empty(isolated_storage):
    resp = client.get("/datasets")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_datasets_after_upload(isolated_storage):
    upload = _upload_csv()
    ds_id = upload["metadata"]["dataset_id"]

    resp = client.get("/datasets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    ds = data[0]
    assert ds["dataset_id"] == ds_id
    assert ds["filename"] == "sample.csv"
    assert ds["version_count"] == 1
    assert "size_bytes" in ds
    assert "created_at" in ds


def test_list_datasets_aggregates_versions(isolated_storage):
    upload = _upload_csv()
    meta = upload["metadata"]
    ds_id = meta["dataset_id"]
    v_id = meta["version_id"]

    csv2 = b"a,b,label\n1,2,0\n3,4,1\n"
    resp2 = client.post(
        f"/datasets/{ds_id}/versions",
        files={"file": ("sample_v2.csv", io.BytesIO(csv2), "text/csv")},
        data={
            "parent_version_id": v_id,
            "operation_type": "preprocess",
            "chunk_rows": "2",
        },
    )
    assert resp2.status_code == 201, resp2.text

    resp = client.get("/datasets")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["version_count"] == 2


# ---------------------------------------------------------------------------
# POST /versions/{version_id}/tamper-demo
# ---------------------------------------------------------------------------

def test_tamper_demo_unknown_version_returns_404(isolated_storage):
    fake_id = str(uuid.uuid4())
    resp = client.post(
        f"/versions/{fake_id}/tamper-demo",
        json={"attack": "modify_cells", "fraction": 0.01, "seed": 42},
    )
    assert resp.status_code == 404


def test_tamper_demo_invalid_attack_returns_400(isolated_storage):
    upload = _upload_csv()
    v_id = upload["metadata"]["version_id"]
    resp = client.post(
        f"/versions/{v_id}/tamper-demo",
        json={"attack": "nuke_everything", "fraction": 0.01, "seed": 42},
    )
    assert resp.status_code == 400
    assert "nuke_everything" in resp.json()["detail"]


def test_tamper_demo_invalid_fraction_returns_400(isolated_storage):
    upload = _upload_csv()
    v_id = upload["metadata"]["version_id"]
    resp = client.post(
        f"/versions/{v_id}/tamper-demo",
        json={"attack": "modify_cells", "fraction": 0.5, "seed": 42},
    )
    assert resp.status_code == 400
    assert "fraction" in resp.json()["detail"].lower()


def test_tamper_demo_fraction_required_for_cell_attack(isolated_storage):
    upload = _upload_csv()
    v_id = upload["metadata"]["version_id"]
    resp = client.post(
        f"/versions/{v_id}/tamper-demo",
        json={"attack": "modify_cells", "seed": 42},
    )
    assert resp.status_code == 400
    assert "fraction" in resp.json()["detail"].lower()


def test_tamper_demo_preserves_original_file(isolated_storage):
    """Original file SHA-256 must be identical before and after a tamper-demo call."""
    upload = _upload_csv()
    meta = upload["metadata"]
    v_id = meta["version_id"]
    ds_id = meta["dataset_id"]

    upload_dir = isolated_storage / "uploads" / ds_id / v_id
    originals = list(upload_dir.iterdir())
    assert len(originals) == 1
    original_file = originals[0]

    sha_before = _sha256(original_file)

    resp = client.post(
        f"/versions/{v_id}/tamper-demo",
        json={"attack": "modify_cells", "fraction": 0.01, "seed": 42},
    )
    # May return 200 / 503 depending on chain availability; what matters is original untouched
    assert resp.status_code in (200, 409, 503), resp.text

    sha_after = _sha256(original_file)
    assert sha_before == sha_after, (
        f"Original file was modified by tamper-demo! Before={sha_before}, After={sha_after}"
    )


def test_tamper_demo_returns_tampering_detected(isolated_storage):
    upload = _upload_csv()
    v_id = upload["metadata"]["version_id"]

    resp = client.post(
        f"/versions/{v_id}/tamper-demo",
        json={"attack": "modify_cells", "fraction": 0.01, "seed": 42},
    )
    if resp.status_code == 503:
        pytest.skip("Blockchain unavailable in isolated test environment")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "verify_result" in body
    assert "attack_details" in body
    assert body["original_file_preserved"] is True
    assert body["verify_result"]["status"] == "TAMPERING_DETECTED"


def test_tamper_demo_swap_columns_no_fraction(isolated_storage):
    upload = _upload_csv()
    v_id = upload["metadata"]["version_id"]

    resp = client.post(
        f"/versions/{v_id}/tamper-demo",
        json={"attack": "swap_columns", "seed": 7},
    )
    if resp.status_code == 503:
        pytest.skip("Blockchain unavailable in isolated test environment")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attack_details"]["attack"] == "swap_columns"
