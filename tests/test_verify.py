"""Comprehensive test suite for Phase 5: Cryptographic Integrity Verification,

Tampering Attacks, Untrusted Artifacts, and Error Scenarios.
"""

import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from web3 import Web3

from backend.chain import (
    ChainClient,
    ChainUnavailable,
    ContractRevert,
    bytes32_to_uuid,
    default_chain_client,
    uuid_to_bytes32,
)
from backend.main import app, get_storage_dir
from backend.verify import verify_version
from experiments.tamper import (
    consistent_local_forgery,
    delete_rows,
    flip_labels,
    forge_metadata,
    insert_rows,
    modify_cells,
    modify_preprocessing_output,
    replace_file,
    rollback_to_version,
    swap_columns,
)

client = TestClient(app)


@pytest.fixture(scope="module")
def deployed_fresh_contract():
    """Deploy an isolated fresh contract instance for verify tests to the running node.
    Does NOT modify backend/contracts/deployment.json.
    """
    rpc_url = os.getenv("RPC_URL", "http://127.0.0.1:8545")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        pytest.skip(f"Hardhat node not running at {rpc_url}")

    artifact_path = Path("blockchain/artifacts/contracts/ProvenanceRegistry.sol/ProvenanceRegistry.json")
    if not artifact_path.exists():
        subprocess.run(["npx", "hardhat", "compile"], cwd="blockchain", check=True)

    with open(artifact_path, "r", encoding="utf-8") as f:
        artifact = json.load(f)

    deployer = w3.eth.accounts[0]
    Factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
    tx_hash = Factory.constructor().transact({"from": deployer})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=10)
    fresh_address = receipt.contractAddress

    # Point global chain client and environment to this fresh instance
    old_env = os.environ.get("PROVENANCE_CONTRACT_ADDRESS")
    os.environ["PROVENANCE_CONTRACT_ADDRESS"] = fresh_address
    default_chain_client._custom_contract_address = fresh_address
    default_chain_client._contract = None

    yield fresh_address

    if old_env is not None:
        os.environ["PROVENANCE_CONTRACT_ADDRESS"] = old_env
        default_chain_client._custom_contract_address = old_env
    else:
        os.environ.pop("PROVENANCE_CONTRACT_ADDRESS", None)
        default_chain_client._custom_contract_address = None
    default_chain_client._contract = None


@pytest.fixture
def clean_dataset_setup(deployed_fresh_contract, tmp_path, monkeypatch):
    """Register a multi-version dataset (v1 -> v2) in an isolated storage directory."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    # 1. Upload v1 (Root)
    csv_bytes = (
        b"id,age,income,credit_score,approved\n"
        b"1,25,50000.0,650,1\n"
        b"2,30,60000.0,700,1\n"
        b"3,35,45000.0,600,0\n"
        b"4,40,80000.0,750,1\n"
        b"5,45,30000.0,550,0\n"
        b"6,50,95000.0,800,1\n"
    )
    v1_res = client.post(
        "/datasets",
        files={"file": ("raw_data.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={"chunk_rows": "2"},  # 1 header + 3 data chunks = 4 chunks
    )
    assert v1_res.status_code == 201
    v1_data = v1_res.json()["metadata"]
    dataset_id = v1_data["dataset_id"]
    v1_id = v1_data["version_id"]

    # 2. Upload v2 (Child)
    v2_bytes = (
        b"id,age,income,credit_score,approved\n"
        b"1,25,50000.0,650,1\n"
        b"2,30,60000.0,700,1\n"
        b"3,35,45000.0,600,0\n"
        b"4,40,80000.0,750,1\n"
    )
    v2_res = client.post(
        f"/datasets/{dataset_id}/versions",
        files={"file": ("filtered_v2.csv", io.BytesIO(v2_bytes), "text/csv")},
        data={
            "parent_version_id": v1_id,
            "operation_type": "filter",
            "operation_params": json.dumps({"reason": "remove_seniors"}),
            "chunk_rows": "2",
        },
    )
    assert v2_res.status_code == 201
    v2_data = v2_res.json()["metadata"]
    v2_id = v2_data["version_id"]

    return {
        "dataset_id": dataset_id,
        "v1_id": v1_id,
        "v2_id": v2_id,
        "storage_dir": tmp_path,
    }


# -----------------------------------------------------------------------------
# 1. Clean Baseline & False-Positive Rate (30 runs)
# -----------------------------------------------------------------------------

def test_clean_version_verification(clean_dataset_setup):
    """A clean unmodified version verifies with status VERIFIED and all checks True."""
    v2_id = clean_dataset_setup["v2_id"]
    res = verify_version(v2_id, storage_dir=clean_dataset_setup["storage_dir"])

    assert res["status"] == "VERIFIED"
    for check_name, check_val in res["checks"].items():
        assert check_val is True, f"Check {check_name} expected True, got {check_val}"

    assert res["details"]["localization_available"] is True
    assert res["details"]["changed_chunks"] == []
    assert res["details"]["matches_version_id"] is None


def test_zero_false_positives_30_runs(clean_dataset_setup):
    """30 repeated verifications of unmodified version all return VERIFIED without creating new versions."""
    v2_id = clean_dataset_setup["v2_id"]
    storage_dir = clean_dataset_setup["storage_dir"]
    durations = []

    for i in range(30):
        res = verify_version(v2_id, storage_dir=storage_dir)
        assert res["status"] == "VERIFIED", f"Iteration {i} failed with status {res['status']}"
        durations.append(res["timings_ms"]["total_ms"])

    mean_latency = sum(durations) / len(durations)
    max_latency = max(durations)
    print(f"\n[30-Run Clean Latency] Mean: {mean_latency:.2f} ms | Max: {max_latency:.2f} ms")
    assert len(durations) == 30


# -----------------------------------------------------------------------------
# 2. Tampering Library: Guarantees Output Differs Across Fractions
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("fraction", [0.001, 0.01, 0.1])
def test_tamper_functions_guarantee_byte_difference(tmp_path, fraction):
    """Every attack function guarantees output bytes differ from input bytes across fractions."""
    base_csv = tmp_path / "base.csv"
    # Create 1000 row CSV
    df = pd.DataFrame({
        "id": range(1, 1001),
        "age": [20 + (i % 50) for i in range(1000)],
        "income": [30000.0 + (i * 10) for i in range(1000)],
        "credit_score": [500 + (i % 300) for i in range(1000)],
        "approved": [i % 2 for i in range(1000)],
    })
    df.to_csv(base_csv, index=False)
    orig_bytes = base_csv.read_bytes()

    # 1. modify_cells
    f1 = tmp_path / f"mod_{fraction}.csv"
    shutil.copy2(base_csv, f1)
    modify_cells(f1, fraction=fraction)
    assert f1.read_bytes() != orig_bytes

    # 2. delete_rows
    f2 = tmp_path / f"del_{fraction}.csv"
    shutil.copy2(base_csv, f2)
    delete_rows(f2, fraction=fraction)
    assert f2.read_bytes() != orig_bytes

    # 3. insert_rows
    f3 = tmp_path / f"ins_{fraction}.csv"
    shutil.copy2(base_csv, f3)
    insert_rows(f3, fraction=fraction)
    assert f3.read_bytes() != orig_bytes

    # 4. flip_labels
    f4 = tmp_path / f"flip_{fraction}.csv"
    shutil.copy2(base_csv, f4)
    flip_labels(f4, fraction=fraction)
    assert f4.read_bytes() != orig_bytes

    # 5. swap_columns
    f5 = tmp_path / f"swap_{fraction}.csv"
    shutil.copy2(base_csv, f5)
    swap_columns(f5)
    assert f5.read_bytes() != orig_bytes

    # 6. replace_file
    f6 = tmp_path / f"rep_{fraction}.csv"
    shutil.copy2(base_csv, f6)
    replace_file(f6)
    assert f6.read_bytes() != orig_bytes

    # 7. modify_preprocessing_output
    f7 = tmp_path / f"prep_{fraction}.csv"
    df_scaled = df.copy()
    df_scaled["income"] = df_scaled["income"] / 100000.0
    df_scaled.to_csv(f7, index=False)
    scaled_orig = f7.read_bytes()
    modify_preprocessing_output(f7, fraction=fraction)
    assert f7.read_bytes() != scaled_orig


# -----------------------------------------------------------------------------
# 3. Controlled Attack Detection on Stored Version
# -----------------------------------------------------------------------------

def test_tamper_modify_cells(clean_dataset_setup):
    """Modifying a cell produces TAMPERING_DETECTED and localizes the exact chunk."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    v2_csv = list((storage_dir / "uploads" / dataset_id / v2_id).iterdir())[0]
    # Modify row 1 (in chunk 1: rows 0 and 1 are in chunk 1)
    df = pd.read_csv(v2_csv)
    df.at[1, "income"] = 999999.0
    df.to_csv(v2_csv, index=False)

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is False
    assert res["checks"]["merkle_root_match"] is False
    assert res["checks"]["tree_integrity"] is True
    # Chunk 0 is header, chunk 1 is rows 0-1, so chunk 1 must be flagged
    assert 1 in res["details"]["changed_chunks"]


def test_tamper_insert_rows_shifts_chunks(clean_dataset_setup):
    """Inserting rows in the middle shifts later chunks and triggers num_chunks mismatch."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    v2_csv = list((storage_dir / "uploads" / dataset_id / v2_id).iterdir())[0]
    insert_rows(v2_csv, fraction=0.5)

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is False
    assert res["checks"]["merkle_root_match"] is False
    assert res["checks"]["num_chunks_match"] is False
    assert len(res["details"]["changed_chunks"]) > 0


def test_tamper_flip_labels(clean_dataset_setup):
    """Flipping classification labels triggers TAMPERING_DETECTED."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    v2_csv = list((storage_dir / "uploads" / dataset_id / v2_id).iterdir())[0]
    flip_labels(v2_csv, fraction=0.5)

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is False


def test_tamper_swap_columns(clean_dataset_setup):
    """Swapping columns triggers TAMPERING_DETECTED."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    v2_csv = list((storage_dir / "uploads" / dataset_id / v2_id).iterdir())[0]
    swap_columns(v2_csv)

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is False


def test_tamper_replace_file(clean_dataset_setup):
    """Replacing entire file triggers TAMPERING_DETECTED."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    v2_csv = list((storage_dir / "uploads" / dataset_id / v2_id).iterdir())[0]
    replace_file(v2_csv)

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is False


def test_tamper_rollback_version_swap_detection(clean_dataset_setup):
    """Rolling back v2's file to v1's file detects matches_version_id == v1_id."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v1_id = clean_dataset_setup["v1_id"]
    v2_id = clean_dataset_setup["v2_id"]

    v1_csv = list((storage_dir / "uploads" / dataset_id / v1_id).iterdir())[0]
    v2_csv = list((storage_dir / "uploads" / dataset_id / v2_id).iterdir())[0]

    rollback_to_version(v2_csv, v1_csv)

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is False
    assert res["details"]["matches_version_id"] == v1_id


def test_tamper_forged_off_chain_metadata(clean_dataset_setup):
    """Forging metadata parent_version_id triggers TAMPERING_DETECTED."""
    storage_dir = clean_dataset_setup["storage_dir"]
    v2_id = clean_dataset_setup["v2_id"]

    meta_file = storage_dir / "metadata" / f"{v2_id}.json"
    forge_metadata(meta_file, field="parent_version_id", new_value=str(uuid.uuid4()))

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["metadata_digest_match"] is False
    assert res["checks"]["lineage_consistency"] is False


def test_tamper_consistent_local_forgery(clean_dataset_setup):
    """A smart attacker altering CSV, local tree, and metadata is still caught by on-chain root."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    consistent_local_forgery(storage_dir, dataset_id, v2_id, tamper_fraction=0.5)

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is False
    assert res["checks"]["merkle_root_match"] is False
    assert res["checks"]["tree_integrity"] is False
    assert res["checks"]["metadata_digest_match"] is False
    assert res["details"]["localization_available"] is False


def test_tamper_tree_with_untouched_file(clean_dataset_setup):
    """Tampering with off-chain tree leaves while file is untouched flags tree_integrity=False and TAMPERING_DETECTED."""
    storage_dir = clean_dataset_setup["storage_dir"]
    v2_id = clean_dataset_setup["v2_id"]

    tree_path = storage_dir / "trees" / f"{v2_id}.json"
    with open(tree_path, "r", encoding="utf-8") as f:
        t_data = json.load(f)

    # Corrupt one leaf
    t_data["levels"][0][0] = "00" * 32
    with open(tree_path, "w", encoding="utf-8") as f:
        json.dump(t_data, f)

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is True
    assert res["checks"]["tree_integrity"] is False
    assert res["details"]["localization_available"] is False


# -----------------------------------------------------------------------------
# 4. Negative Scenarios & Missing Artifact Precedence (Step 41)
# -----------------------------------------------------------------------------

def test_missing_file_returns_not_verifiable(clean_dataset_setup):
    """Missing stored file gives NOT_VERIFIABLE with null file checks; never VERIFIED."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    v2_dir = storage_dir / "uploads" / dataset_id / v2_id
    shutil.rmtree(v2_dir)

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "NOT_VERIFIABLE"
    assert res["checks"]["file_hash_match"] is None
    assert res["checks"]["merkle_root_match"] is None
    assert res["checks"]["num_chunks_match"] is None


def test_missing_metadata_file_returns_not_verifiable_with_null(deployed_fresh_contract, tmp_path, monkeypatch):
    """Missing metadata with all else passing gives NOT_VERIFIABLE with metadata_digest_match=None."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))
    csv_bytes = b"id,val\n1,10\n2,20\n"
    up_res = client.post(
        "/datasets",
        files={"file": ("simple.csv", io.BytesIO(csv_bytes), "text/csv")},
        data={"chunk_rows": "1000"},
    )
    assert up_res.status_code == 201
    v_id = up_res.json()["metadata"]["version_id"]

    meta_file = tmp_path / "metadata" / f"{v_id}.json"
    meta_file.unlink()

    res = verify_version(v_id, storage_dir=tmp_path)
    assert res["status"] == "NOT_VERIFIABLE"
    assert res["checks"]["metadata_digest_match"] is None
    assert res["checks"]["file_hash_match"] is True
    assert res["checks"]["merkle_root_match"] is True


def test_clean_file_plus_deleted_tree_returns_not_verifiable(clean_dataset_setup):
    """Clean file with tree file deleted gives NOT_VERIFIABLE with tree_integrity=None and file_hash_match=True."""
    storage_dir = clean_dataset_setup["storage_dir"]
    v2_id = clean_dataset_setup["v2_id"]

    tree_file = storage_dir / "trees" / f"{v2_id}.json"
    tree_file.unlink()

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "NOT_VERIFIABLE"
    assert res["checks"]["tree_integrity"] is None
    assert res["checks"]["file_hash_match"] is True
    assert res["details"]["localization_available"] is False


def test_tampered_file_plus_deleted_tree_gives_tampering_detected(clean_dataset_setup):
    """Tampered file + deleted tree returns TAMPERING_DETECTED (not NOT_VERIFIABLE) with tree_integrity=None."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    # 1. Tamper file
    v2_csv = list((storage_dir / "uploads" / dataset_id / v2_id).iterdir())[0]
    modify_cells(v2_csv, fraction=0.5)

    # 2. Delete tree
    tree_file = storage_dir / "trees" / f"{v2_id}.json"
    tree_file.unlink()

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is False
    assert res["checks"]["tree_integrity"] is None
    assert res["details"]["localization_available"] is False


def test_tampered_file_plus_deleted_metadata_gives_tampering_detected(clean_dataset_setup):
    """Tampered file + deleted metadata file returns TAMPERING_DETECTED with metadata_digest_match=None."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    # 1. Tamper file
    v2_csv = list((storage_dir / "uploads" / dataset_id / v2_id).iterdir())[0]
    modify_cells(v2_csv, fraction=0.5)

    # 2. Delete metadata file
    meta_file = storage_dir / "metadata" / f"{v2_id}.json"
    meta_file.unlink()

    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is False
    assert res["checks"]["metadata_digest_match"] is None


def test_malformed_version_id_endpoint():
    """Malformed UUID returns 400 Bad Request."""
    res = client.get("/versions/not-a-uuid/verify")
    assert res.status_code == 400
    assert "malformed" in res.json()["detail"].lower()


def test_unregistered_version_id_endpoint():
    """Random valid UUID not registered returns 404 Not Found."""
    random_uuid = str(uuid.uuid4())
    res = client.get(f"/versions/{random_uuid}/verify")
    assert res.status_code == 404
    assert "not registered" in res.json()["detail"].lower()


def test_chain_down_endpoint(clean_dataset_setup, monkeypatch):
    """Unreachable RPC URL returns 503 Service Unavailable."""
    # Point client to unreachable port
    unreachable_client = ChainClient(rpc_url="http://127.0.0.1:9999")
    monkeypatch.setattr("backend.main.default_chain_client", unreachable_client)

    res = client.get(f"/versions/{clean_dataset_setup['v2_id']}/verify")
    assert res.status_code == 503


# -----------------------------------------------------------------------------
# 5. Immutability & Trust Rules (User Feedback 3, 5, 6)
# -----------------------------------------------------------------------------

def test_verification_is_read_only_and_preserves_storage_bytes(clean_dataset_setup):
    """Verification must not modify any stored data (files are byte-identical before and after)."""
    storage_dir = clean_dataset_setup["storage_dir"]
    v2_id = clean_dataset_setup["v2_id"]

    # Snapshot all file bytes in storage_dir
    before_snapshot = {}
    for p in storage_dir.rglob("*"):
        if p.is_file():
            before_snapshot[str(p)] = p.read_bytes()

    # Run verify
    res = verify_version(v2_id, storage_dir=storage_dir)
    assert res["status"] == "VERIFIED"

    # Verify identical bytes
    after_snapshot = {}
    for p in storage_dir.rglob("*"):
        if p.is_file():
            after_snapshot[str(p)] = p.read_bytes()

    assert before_snapshot == after_snapshot


def test_timings_ms_structure_and_performance(clean_dataset_setup):
    """timings_ms keys exist and total_ms >= hashing_ms."""
    v2_id = clean_dataset_setup["v2_id"]
    res = verify_version(v2_id, storage_dir=clean_dataset_setup["storage_dir"])

    timings = res["timings_ms"]
    for key in ["chain_read_ms", "hashing_ms", "merkle_ms", "total_ms"]:
        assert key in timings
        assert isinstance(timings[key], (int, float))

    assert timings["total_ms"] >= timings["hashing_ms"]


def test_expected_values_strictly_from_chain_not_off_chain_metadata(clean_dataset_setup):
    """Forging metadata file_hash to match tampered file does not fool verification."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    v2_csv = list((storage_dir / "uploads" / dataset_id / v2_id).iterdir())[0]
    modify_cells(v2_csv, fraction=0.5)
    tampered_hash = hashlib.sha256(v2_csv.read_bytes()).hexdigest()

    # Overwrite off-chain metadata file_hash with tampered_hash
    meta_path = storage_dir / "metadata" / f"{v2_id}.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        m = json.load(f)
    m["file_hash"] = tampered_hash
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(m, f)

    res = verify_version(v2_id, storage_dir=storage_dir)
    # Must still be TAMPERING_DETECTED because expected_file_hash comes strictly from the chain!
    assert res["status"] == "TAMPERING_DETECTED"
    assert res["checks"]["file_hash_match"] is False
    assert res["details"]["expected_file_hash"] != tampered_hash


# -----------------------------------------------------------------------------
# 6. Legitimate Update Workflow (Step 40)
# -----------------------------------------------------------------------------

def test_legitimate_update_creates_new_version_and_preserves_old(clean_dataset_setup):
    """Uploading manual_edit as new version preserves old version as VERIFIED while new version is also VERIFIED."""
    storage_dir = clean_dataset_setup["storage_dir"]
    dataset_id = clean_dataset_setup["dataset_id"]
    v2_id = clean_dataset_setup["v2_id"]

    # 1. Register manual_edit version
    v3_bytes = (
        b"id,age,income,credit_score,approved\n"
        b"1,26,52000.0,660,1\n"
        b"2,31,61000.0,710,1\n"
    )
    v3_res = client.post(
        f"/datasets/{dataset_id}/versions",
        files={"file": ("manual_corrected.csv", io.BytesIO(v3_bytes), "text/csv")},
        data={
            "parent_version_id": v2_id,
            "operation_type": "manual_edit",
            "operation_params": json.dumps({"note": "corrected annual incomes"}),
            "chunk_rows": "2",
        },
    )
    assert v3_res.status_code == 201
    v3_id = v3_res.json()["metadata"]["version_id"]

    # 2. Both old version (v2) and new version (v3) verify as VERIFIED
    res_v2 = verify_version(v2_id, storage_dir=storage_dir)
    assert res_v2["status"] == "VERIFIED"

    res_v3 = verify_version(v3_id, storage_dir=storage_dir)
    assert res_v3["status"] == "VERIFIED"


# -----------------------------------------------------------------------------
# 7. Endpoint POST /versions/{id}/verify with Uploaded Multipart File
# -----------------------------------------------------------------------------

def test_post_verify_endpoint_with_uploaded_file(clean_dataset_setup):
    """POST /versions/{id}/verify accepts a file upload, verifies it, and deletes the temporary file."""
    v2_id = clean_dataset_setup["v2_id"]
    valid_csv = (
        b"id,age,income,credit_score,approved\n"
        b"1,25,50000.0,650,1\n"
        b"2,30,60000.0,700,1\n"
        b"3,35,45000.0,600,0\n"
        b"4,40,80000.0,750,1\n"
    )

    # 1. Valid file upload -> VERIFIED
    res1 = client.post(
        f"/versions/{v2_id}/verify",
        files={"file": ("test_verify.csv", io.BytesIO(valid_csv), "text/csv")},
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "VERIFIED"

    # 2. Tampered file upload -> TAMPERING_DETECTED
    tampered_csv = valid_csv.replace(b"50000.0", b"99999.0")
    res2 = client.post(
        f"/versions/{v2_id}/verify",
        files={"file": ("tampered_verify.csv", io.BytesIO(tampered_csv), "text/csv")},
    )
    assert res2.status_code == 200
    assert res2.json()["status"] == "TAMPERING_DETECTED"

    # 3. Check no leftover temp files exist
    temp_dir = clean_dataset_setup["storage_dir"] / "temp"
    if temp_dir.exists():
        assert len(list(temp_dir.iterdir())) == 0
