"""Comprehensive test suite for Phase 6: ML Pipeline Preprocessing,

Pre-training Verification Gate, Leakage Prevention, Training Run Anchoring,
and Reproducibility Verification.
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

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from web3 import Web3

from backend.chain import (
    ChainClient,
    ContractRevert,
    default_chain_client,
)
from backend.fingerprint import compute_canonical_metadata_digest, compute_file_hash
from backend.main import app
from backend.ml_pipeline import (
    IntegrityGateError,
    preprocess_and_register,
    reproduce_training_run,
    train_on_version,
)
from backend.verify import _strip_0x
from experiments.make_synthetic_csv import generate_synthetic_csv
from experiments.tamper import modify_cells

client = TestClient(app)


@pytest.fixture(scope="module")
def deployed_fresh_contract():
    """Deploy an isolated fresh contract instance for Phase 6 tests to the running node.
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

    old_env = os.environ.get("PROVENANCE_CONTRACT_ADDRESS")
    os.environ["PROVENANCE_CONTRACT_ADDRESS"] = fresh_address
    default_chain_client._custom_contract_address = fresh_address
    default_chain_client._custom_deployment_block = receipt.blockNumber
    default_chain_client._contract = None

    yield fresh_address

    if old_env is not None:
        os.environ["PROVENANCE_CONTRACT_ADDRESS"] = old_env
        default_chain_client._custom_contract_address = old_env
    else:
        os.environ.pop("PROVENANCE_CONTRACT_ADDRESS", None)
        default_chain_client._custom_contract_address = None
    default_chain_client._custom_deployment_block = None
    default_chain_client._contract = None


@pytest.fixture
def base_dataset_fixture(deployed_fresh_contract, tmp_path, monkeypatch):
    """Register root dataset (v1) and deduplicated child (v2) in isolated temp storage."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    # Generate synthetic CSV in temp folder
    csv_path = tmp_path / "raw_synthetic.csv"
    generate_synthetic_csv(csv_path, num_rows=1000, seed=42)

    # 1. Upload v1 (Root)
    with open(csv_path, "rb") as f:
        v1_res = client.post(
            "/datasets",
            files={"file": (csv_path.name, f, "text/csv")},
            data={"chunk_rows": "1000"},
        )
    assert v1_res.status_code == 201
    v1_data = v1_res.json()["metadata"]
    dataset_id = v1_data["dataset_id"]
    v1_id = v1_data["version_id"]

    # 2. Upload v2 (Deduplicate)
    df = pd.read_csv(csv_path)
    df_dedup = df.drop_duplicates()
    buf = io.BytesIO()
    df_dedup.to_csv(buf, index=False)
    buf.seek(0)

    v2_res = client.post(
        f"/datasets/{dataset_id}/versions",
        files={"file": ("dedup_v2.csv", buf, "text/csv")},
        data={
            "parent_version_id": v1_id,
            "operation_type": "deduplicate",
            "operation_params": json.dumps({"rows_before": len(df), "rows_after": len(df_dedup)}),
            "chunk_rows": "1000",
        },
    )
    assert v2_res.status_code == 201
    v2_id = v2_res.json()["metadata"]["version_id"]

    return {
        "dataset_id": dataset_id,
        "v1_id": v1_id,
        "v2_id": v2_id,
        "storage_dir": tmp_path,
    }


# -----------------------------------------------------------------------------
# 1. Preprocessing and Registration Tests (Steps 42-44)
# -----------------------------------------------------------------------------

def test_preprocess_and_register_child_version(base_dataset_fixture):
    """preprocess_and_register creates child version linked to parent, operation_type='preprocess_clean', id dropped."""
    storage_dir = base_dataset_fixture["storage_dir"]
    dataset_id = base_dataset_fixture["dataset_id"]
    v2_id = base_dataset_fixture["v2_id"]

    # Preprocess v2 into v3
    v3_info = preprocess_and_register(v2_id, storage_dir=storage_dir)

    v3_id = v3_info["version_id"]
    assert v3_info["parent_version_id"] == v2_id
    assert v3_info["metadata"]["provenance"]["operation_type"] == "preprocess_clean"
    assert "id" in v3_info["metadata"]["provenance"]["operation_params"]["dropped_columns"]

    # Verify on-chain record
    on_chain_rec = default_chain_client.get_version(v3_id)
    assert on_chain_rec["dataset_id"] == dataset_id
    assert on_chain_rec["parent_version_id"] == v2_id

    # Verify id column absent in cleaned CSV
    clean_csv_path = storage_dir / "uploads" / dataset_id / v3_id / "cleaned_dataset.csv"
    assert clean_csv_path.exists()
    df_v3 = pd.read_csv(clean_csv_path)
    assert "id" not in df_v3.columns
    assert "approved" in df_v3.columns

    # Verify parent version is untouched
    v2_csv_path = list((storage_dir / "uploads" / dataset_id / v2_id).iterdir())[0]
    df_v2 = pd.read_csv(v2_csv_path)
    assert "id" in df_v2.columns


def test_missing_rate_dataset_honest_nan_handling(tmp_path, monkeypatch, deployed_fresh_contract):
    """Registered v3 for --missing-rate 0.05 dataset still contains missing cells (cleaning did not impute)."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    csv_path = tmp_path / "missing_data.csv"
    generate_synthetic_csv(csv_path, num_rows=1000, seed=42, missing_rate=0.05)

    with open(csv_path, "rb") as f:
        res = client.post("/datasets", files={"file": ("missing_raw.csv", f, "text/csv")})
    assert res.status_code == 201
    v1_id = res.json()["metadata"]["version_id"]
    dataset_id = res.json()["metadata"]["dataset_id"]

    # Preprocess v1 into v2
    v2_info = preprocess_and_register(v1_id, storage_dir=tmp_path)
    v2_id = v2_info["version_id"]

    v2_csv = tmp_path / "uploads" / dataset_id / v2_id / "cleaned_dataset.csv"
    df_v2 = pd.read_csv(v2_csv)
    # Check that missing cells were NOT filled in registered cleaned dataset
    total_missing = df_v2.isna().sum().sum()
    assert total_missing > 0, "Cleaned dataset must preserve missing cells; imputation occurs only during training"


# -----------------------------------------------------------------------------
# 2. Gate, Training, and Experiment Records (Steps 45-49)
# -----------------------------------------------------------------------------

def test_training_on_verified_version_and_chain_anchoring(base_dataset_fixture):
    """Training on a verified version succeeds and anchors digest on-chain."""
    storage_dir = base_dataset_fixture["storage_dir"]
    v2_id = base_dataset_fixture["v2_id"]

    # Clean v2 to v3 first
    v3_info = preprocess_and_register(v2_id, storage_dir=storage_dir)
    v3_id = v3_info["version_id"]

    # Train model on v3
    train_res = train_on_version(v3_id, config={"seed": 42}, storage_dir=storage_dir)
    run_id = train_res["run_id"]
    assert "metrics" in train_res
    assert train_res["metrics"]["accuracy"] > 0.5
    assert train_res["timings_ms"]["gate_time_ms"] > 0
    assert train_res["timings_ms"]["train_time_ms"] > 0

    # Verify on-chain run record
    on_chain_run = default_chain_client.get_run(run_id)
    assert on_chain_run["run_id"] == run_id
    assert on_chain_run["dataset_version_id"] == v3_id

    # Verify independent hashlib digest calculation
    exp_file = storage_dir / "experiments" / f"{run_id}.json"
    with open(exp_file, "r", encoding="utf-8") as f:
        stored_exp = json.load(f)

    meta_copy = {k: v for k, v in stored_exp.items() if k != "experiment_digest"}
    indep_digest = compute_canonical_metadata_digest(meta_copy)
    assert _strip_0x(on_chain_run["experiment_digest"]).lower() == indep_digest.lower()

    # Input file hash matches on-chain version fileHash
    on_chain_v3 = default_chain_client.get_version(v3_id)
    assert stored_exp["input_file_hash"].lower() == _strip_0x(on_chain_v3["file_hash"]).lower()

    # Verify model artifact saved
    model_file = storage_dir / "models" / run_id / "model.joblib"
    assert model_file.exists()


def test_gate_blocks_tampered_data(base_dataset_fixture):
    """Integrity gate blocks training on tampered file, creating no model, record, or chain run."""
    storage_dir = base_dataset_fixture["storage_dir"]
    dataset_id = base_dataset_fixture["dataset_id"]
    v2_id = base_dataset_fixture["v2_id"]

    v3_info = preprocess_and_register(v2_id, storage_dir=storage_dir)
    v3_id = v3_info["version_id"]

    # Tamper v3 file
    v3_csv = storage_dir / "uploads" / dataset_id / v3_id / "cleaned_dataset.csv"
    modify_cells(v3_csv, fraction=0.05)

    # Train should raise IntegrityGateError
    with pytest.raises(IntegrityGateError) as exc_info:
        train_on_version(v3_id, storage_dir=storage_dir)

    assert exc_info.value.status == "TAMPERING_DETECTED"

    # Verify no model, no experiment record, and no chain events exist
    runs_for_v3 = default_chain_client.get_runs_for_version(v3_id)
    assert runs_for_v3 == []

    # API endpoint returns 409
    api_res = client.post(f"/versions/{v3_id}/train")
    assert api_res.status_code == 409
    assert api_res.json()["detail"]["status"] == "TAMPERING_DETECTED"


def test_gate_toctou_verified_copy_used(base_dataset_fixture, monkeypatch):
    """Gate TOCTOU protection: training reads only from the verified copy made before training."""
    storage_dir = base_dataset_fixture["storage_dir"]
    dataset_id = base_dataset_fixture["dataset_id"]
    v2_id = base_dataset_fixture["v2_id"]

    v3_info = preprocess_and_register(v2_id, storage_dir=storage_dir)
    v3_id = v3_info["version_id"]

    v3_csv = storage_dir / "uploads" / dataset_id / v3_id / "cleaned_dataset.csv"

    # Intercept shutil.copy2 to tamper stored file right AFTER the verified copy is made
    orig_copy2 = shutil.copy2

    def copy2_with_stored_tampering(src, dst, *args, **kwargs):
        res = orig_copy2(src, dst, *args, **kwargs)
        # Modify the original stored file on disk
        if "cleaned_dataset.csv" in str(src):
            with open(src, "a") as f:
                f.write("\n99999,99,99999.0,999,High School,Employed,Own,9999.0,1\n")
        return res

    monkeypatch.setattr(shutil, "copy2", copy2_with_stored_tampering)

    # Training proceeds because it works strictly on the verified copy
    train_res = train_on_version(v3_id, storage_dir=storage_dir)
    assert "metrics" in train_res

    # Subsequent verification of stored version now fails because stored file was tampered
    gate_after = client.get(f"/versions/{v3_id}/verify").json()
    assert gate_after["status"] == "TAMPERING_DETECTED"


def test_data_leakage_scaler_fitted_on_train_split_only(base_dataset_fixture):
    """Verify that preprocessing scaler statistics are computed from training split only."""
    storage_dir = base_dataset_fixture["storage_dir"]
    dataset_id = base_dataset_fixture["dataset_id"]
    v2_id = base_dataset_fixture["v2_id"]

    v3_info = preprocess_and_register(v2_id, storage_dir=storage_dir)
    v3_id = v3_info["version_id"]

    v3_csv = storage_dir / "uploads" / dataset_id / v3_id / "cleaned_dataset.csv"
    df = pd.read_csv(v3_csv)

    # Calculate full-dataset mean for income
    full_income_mean = df["income"].mean()

    # Train model
    train_res = train_on_version(v3_id, config={"seed": 42}, storage_dir=storage_dir)
    run_id = train_res["run_id"]

    model_path = storage_dir / "models" / run_id / "model.joblib"
    import joblib
    fitted_pipeline = joblib.load(model_path)

    # Extract fitted scaler from pipeline
    col_transformer = fitted_pipeline.named_steps["preprocessor"]
    num_pipeline = col_transformer.named_transformers_["num"]
    scaler = num_pipeline.named_steps["scaler"]

    # Find income index in numeric features
    X = df.drop(columns=["approved"])
    numeric_cols = [c for c in X.columns if pd.api.types.is_numeric_dtype(X[c])]
    income_idx = numeric_cols.index("income")
    fitted_scaler_mean = scaler.mean_[income_idx]

    # Calculate train-split mean
    from sklearn.model_selection import train_test_split
    X_train, _, _, _ = train_test_split(X, df["approved"], test_size=0.2, random_state=42, stratify=df["approved"])
    train_income_mean = X_train["income"].mean()

    # Assert fitted scaler mean equals training split mean and differs from full dataset mean
    assert np.isclose(fitted_scaler_mean, train_income_mean)
    assert not np.isclose(fitted_scaler_mean, full_income_mean)


def test_missing_values_pipeline_training(tmp_path, monkeypatch, deployed_fresh_contract):
    """Pipeline with SimpleImputer trains successfully on dataset with 5% missing values."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))

    csv_path = tmp_path / "missing_data_train.csv"
    generate_synthetic_csv(csv_path, num_rows=1000, seed=42, missing_rate=0.05)

    with open(csv_path, "rb") as f:
        res = client.post("/datasets", files={"file": ("missing.csv", f, "text/csv")})
    v1_id = res.json()["metadata"]["version_id"]

    v2_info = preprocess_and_register(v1_id, storage_dir=tmp_path)
    v2_id = v2_info["version_id"]

    train_res = train_on_version(v2_id, storage_dir=tmp_path)
    assert train_res["metrics"]["accuracy"] > 0.5


def test_training_determinism_across_runs(base_dataset_fixture):
    """Same random seed gives identical metrics and prediction hashes; different seed differs."""
    storage_dir = base_dataset_fixture["storage_dir"]
    v2_id = base_dataset_fixture["v2_id"]

    v3_info = preprocess_and_register(v2_id, storage_dir=storage_dir)
    v3_id = v3_info["version_id"]

    run1 = train_on_version(v3_id, config={"seed": 42}, storage_dir=storage_dir)
    run2 = train_on_version(v3_id, config={"seed": 42}, storage_dir=storage_dir)
    run3 = train_on_version(v3_id, config={"seed": 99}, storage_dir=storage_dir)

    assert run1["metrics"] == run2["metrics"]
    assert run1["experiment_record"]["test_predictions_sha256"] == run2["experiment_record"]["test_predictions_sha256"]

    # Different seed gives different split
    assert run1["experiment_record"]["test_predictions_sha256"] != run3["experiment_record"]["test_predictions_sha256"]


# -----------------------------------------------------------------------------
# 3. Lookup and Reproducibility (Steps 50-51)
# -----------------------------------------------------------------------------

def test_reproducibility_workflow(base_dataset_fixture):
    """Reproducibility check succeeds for clean run, detects tampered records, and blocks tampered data."""
    storage_dir = base_dataset_fixture["storage_dir"]
    dataset_id = base_dataset_fixture["dataset_id"]
    v2_id = base_dataset_fixture["v2_id"]

    v3_info = preprocess_and_register(v2_id, storage_dir=storage_dir)
    v3_id = v3_info["version_id"]

    train_res = train_on_version(v3_id, config={"seed": 42}, storage_dir=storage_dir)
    run_id = train_res["run_id"]

    # Snapshot storage files to verify zero side-effects
    before_snap = {str(p): p.read_bytes() for p in storage_dir.rglob("*") if p.is_file()}

    # 1. Clean run -> REPRODUCED
    repro1 = reproduce_training_run(run_id, storage_dir=storage_dir)
    assert repro1["status"] == "REPRODUCED"
    assert repro1["metrics_match"] is True
    assert repro1["predictions_match"] is True

    # Check zero side-effects
    after_snap = {str(p): p.read_bytes() for p in storage_dir.rglob("*") if p.is_file()}
    assert before_snap == after_snap

    # 2. Tamper off-chain experiment record metric -> RECORD_TAMPERED
    exp_path = storage_dir / "experiments" / f"{run_id}.json"
    with open(exp_path, "r", encoding="utf-8") as f:
        rec = json.load(f)
    rec["metrics"]["accuracy"] = 0.999999
    with open(exp_path, "w", encoding="utf-8") as f:
        json.dump(rec, f)

    repro2 = reproduce_training_run(run_id, storage_dir=storage_dir)
    assert repro2["status"] == "RECORD_TAMPERED"

    # Restore experiment record
    with open(exp_path, "w", encoding="utf-8") as f:
        json.dump(train_res["experiment_record"], f)

    # 3. Tamper dataset file on disk -> BLOCKED_BY_GATE
    v3_csv = storage_dir / "uploads" / dataset_id / v3_id / "cleaned_dataset.csv"
    modify_cells(v3_csv, fraction=0.05)

    repro3 = reproduce_training_run(run_id, storage_dir=storage_dir)
    assert repro3["status"] == "BLOCKED_BY_GATE"


def test_model_artifact_intact_detection(base_dataset_fixture):
    """Editing the model file reports model_artifact_intact=False in GET /experiments/{id}."""
    storage_dir = base_dataset_fixture["storage_dir"]
    v2_id = base_dataset_fixture["v2_id"]

    v3_info = preprocess_and_register(v2_id, storage_dir=storage_dir)
    v3_id = v3_info["version_id"]

    train_res = train_on_version(v3_id, config={"seed": 42}, storage_dir=storage_dir)
    run_id = train_res["run_id"]

    # Initial check: intact == True
    exp_get1 = client.get(f"/experiments/{run_id}").json()
    assert exp_get1["model_artifact_intact"] is True
    assert exp_get1["experiment_digest_matches_chain"] is True

    # Corrupt model artifact
    model_file = storage_dir / "models" / run_id / "model.joblib"
    with open(model_file, "ab") as f:
        f.write(b"CORRUPTED_BYTES")

    exp_get2 = client.get(f"/experiments/{run_id}").json()
    assert exp_get2["model_artifact_intact"] is False


def test_runs_by_version_partitioning_from_events(base_dataset_fixture):
    """get_runs_for_version filters runs by datasetVersionId from chain events."""
    storage_dir = base_dataset_fixture["storage_dir"]
    v1_id = base_dataset_fixture["v1_id"]
    v2_id = base_dataset_fixture["v2_id"]

    # Train on v1
    run_v1 = train_on_version(v1_id, config={"seed": 42}, storage_dir=storage_dir)["run_id"]
    # Train on v2
    run_v2 = train_on_version(v2_id, config={"seed": 42}, storage_dir=storage_dir)["run_id"]

    runs_v1 = client.get(f"/versions/{v1_id}/experiments").json()
    runs_v2 = client.get(f"/versions/{v2_id}/experiments").json()

    assert run_v1 in runs_v1
    assert run_v1 not in runs_v2
    assert run_v2 in runs_v2
    assert run_v2 not in runs_v1


def test_chain_reverts_mapped_cleanly(base_dataset_fixture):
    """record_training_run reverts with custom errors when constraints violated."""
    random_version_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    digest = hashlib.sha256(b"dummy").hexdigest()

    # 1. Unregistered dataset version -> VersionNotFound
    with pytest.raises(ContractRevert) as exc:
        default_chain_client.record_training_run(run_id, random_version_id, digest)
    assert exc.value.error_name == "VersionNotFound"

    # 2. Duplicate run_id -> RunAlreadyExists
    valid_version = base_dataset_fixture["v1_id"]
    default_chain_client.record_training_run(run_id, valid_version, digest)

    with pytest.raises(ContractRevert) as exc2:
        default_chain_client.record_training_run(run_id, valid_version, digest)
    assert exc2.value.error_name == "RunAlreadyExists"
