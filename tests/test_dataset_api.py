"""Integration tests for FastAPI dataset endpoints with isolated temporary storage."""

import io
import os
import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Ensure all tests write to a fresh isolated temporary storage directory, never real storage."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    yield tmp_path


def test_valid_csv_upload_and_retrieval(isolated_storage):
    """Test standard valid CSV upload flow and subsequent metadata retrieval."""
    csv_content = b"feature_1,feature_2,label\n1.2,3.4,0\n5.6,7.8,1\n9.0,1.2,0\n"

    # Upload with chunk_rows=1
    response = client.post(
        "/datasets",
        files={"file": ("training_sample.csv", io.BytesIO(csv_content), "text/csv")},
        data={"chunk_rows": "1"},
    )

    assert response.status_code == 201
    data = response.json()

    dataset_id = data["dataset_id"]
    assert data["filename"] == "training_sample.csv"
    assert data["size_bytes"] == len(csv_content)
    assert data["num_chunks"] == 4  # 1 header + 3 data rows
    assert "file_hash" in data
    assert "merkle_root" in data
    assert "metadata_digest" in data

    # Verify physical file existence in isolated temporary storage
    uploaded_file = isolated_storage / "uploads" / dataset_id / "training_sample.csv"
    assert uploaded_file.exists()
    assert uploaded_file.read_bytes() == csv_content

    # Verify tree existence
    tree_file = isolated_storage / "trees" / f"{dataset_id}.json"
    assert tree_file.exists()

    # Verify metadata existence
    meta_file = isolated_storage / "metadata" / f"{dataset_id}.json"
    assert meta_file.exists()

    # Test GET /datasets/{id}
    get_res = client.get(f"/datasets/{dataset_id}")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["dataset_id"] == dataset_id
    assert get_data["merkle_root"] == data["merkle_root"]
    assert get_data["metadata_digest"] == data["metadata_digest"]


def test_reject_empty_file():
    """Reject empty file (0 bytes)."""
    response = client.post(
        "/datasets",
        files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_reject_non_csv():
    """Reject non-CSV files based on extension."""
    response = client.post(
        "/datasets",
        files={"file": ("data.txt", io.BytesIO(b"hello world"), "text/plain")},
    )
    assert response.status_code == 400
    assert "csv" in response.json()["detail"].lower()


def test_reject_path_traversal():
    """Reject path traversal in filename."""
    traversal_filenames = [
        "../../etc/passwd.csv",
        "..\\..\\windows\\system32.csv",
        "foo/bar/baz.csv",
    ]

    for fname in traversal_filenames:
        response = client.post(
            "/datasets",
            files={"file": (fname, io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
        )
        assert response.status_code == 400
        assert "traversal" in response.json()["detail"].lower() or "invalid" in response.json()["detail"].lower()


def test_reject_unparseable_csv():
    """Reject corrupt/unparseable CSV files."""
    # Malformed NUL bytes / invalid binary pretending to be CSV
    corrupt_content = b"\x00\xff\xfe\x00malformed_csv_binary"
    response = client.post(
        "/datasets",
        files={"file": ("corrupt.csv", io.BytesIO(corrupt_content), "text/csv")},
    )
    assert response.status_code == 400
    assert "not a valid" in response.json()["detail"].lower()


def test_reject_file_exceeding_size_limit(monkeypatch):
    """Reject file exceeding configured MAX_UPLOAD_SIZE_BYTES limit."""
    # Temporarily set limit to 100 bytes
    monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", "100")

    large_content = b"col1,col2\n" + b"1,2\n" * 50  # ~210 bytes
    response = client.post(
        "/datasets",
        files={"file": ("large.csv", io.BytesIO(large_content), "text/csv")},
    )
    assert response.status_code == 400
    assert "exceeds maximum allowed size" in response.json()["detail"].lower()


def test_get_nonexistent_dataset():
    """GET /datasets/{id} returns 404 for unknown UUID or invalid ID."""
    response = client.get("/datasets/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404

    # Invalid UUID format returns 404
    bad_id_res = client.get("/datasets/not-a-valid-uuid")
    assert bad_id_res.status_code == 404
