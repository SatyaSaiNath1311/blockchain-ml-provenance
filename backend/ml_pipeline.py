"""ML pipeline integration: data cleaning, pre-training verification gate, training, and reproducibility."""

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from backend.chain import (
    ChainClient,
    default_chain_client,
)
from backend.fingerprint import (
    build_merkle_tree,
    compute_canonical_metadata_digest,
    compute_file_hash,
    split_csv_into_chunks,
)
from backend.verify import _strip_0x, verify_version


class IntegrityGateError(Exception):
    """Raised when dataset verification fails before preprocessing or model training."""

    def __init__(self, status: str, verification_result: dict[str, Any]):
        super().__init__(f"Pre-training verification gate rejected version: {status}")
        self.status = status
        self.verification_result = verification_result


def get_software_versions() -> dict[str, str]:
    """Capture runtime software versions of critical libraries."""
    versions = {"python": platform.python_version()}
    for pkg in ["pandas", "numpy", "scikit-learn", "joblib", "web3", "fastapi"]:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except Exception:
            versions[pkg] = "unknown"
    return versions


def _locate_stored_file(storage_root: Path, dataset_id: str, version_id: str) -> Path:
    """Safely locate the file path for a version inside uploads/."""
    upload_dir = storage_root / "uploads" / dataset_id / version_id
    if not upload_dir.exists() or not upload_dir.is_dir():
        raise FileNotFoundError(f"Directory not found: {upload_dir}")
    candidates = [f for f in upload_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
    if not candidates:
        raise FileNotFoundError(f"No file found in {upload_dir}")
    return candidates[0]


# -----------------------------------------------------------------------------
# 1. Deterministic Data Cleaning & Child Version Registration (Steps 42-44)
# -----------------------------------------------------------------------------

def preprocess_and_register(
    version_id: str | uuid.UUID,
    storage_dir: Path | str | None = None,
    chain_client: ChainClient | None = None,
) -> dict[str, Any]:
    """Clean dataset deterministically (leakage-free) and register as a child version.

    TOCTOU protection: Copies file to private temp dir, verifies copy, then cleans from that copy.
    """
    v_id = str(version_id)
    client = chain_client or default_chain_client
    storage_root = Path(storage_dir or os.getenv("STORAGE_DIR", "./storage")).resolve()

    # Query on-chain record for dataset_id
    parent_rec = client.get_version(v_id)
    dataset_id = parent_rec["dataset_id"]

    stored_file = _locate_stored_file(storage_root, dataset_id, v_id)

    temp_gate_dir = Path(tempfile.mkdtemp(prefix="gate_preprocess_toctou_"))
    try:
        temp_copy = temp_gate_dir / stored_file.name
        shutil.copy2(stored_file, temp_copy)

        # 1. Gate verification on copy
        gate_res = verify_version(v_id, file_path=temp_copy, storage_dir=storage_root, chain_client=client)
        if gate_res["status"] != "VERIFIED":
            raise IntegrityGateError(gate_res["status"], gate_res)

        # 2. Read only from the verified copy
        df = pd.read_csv(temp_copy)
        initial_rows = len(df)
        dropped_cols = []

        # Drop 'id' column
        if "id" in df.columns:
            df = df.drop(columns=["id"])
            dropped_cols.append("id")

        # Drop rows with missing target label only
        target_col = "approved" if "approved" in df.columns else df.columns[-1]
        if target_col in df.columns:
            df = df.dropna(subset=[target_col]).reset_index(drop=True)

        # Strip whitespace and title-case categoricals (preserving NaNs)
        cat_cols = ["education", "employment", "home_ownership"]
        for col in cat_cols:
            if col in df.columns:
                mask = df[col].notna()
                df.loc[mask, col] = df.loc[mask, col].astype(str).str.strip().str.title()

        # Cast integer columns with nullable Int64 only where appropriate
        int_candidates = ["age", "credit_score", target_col]
        for col in int_candidates:
            if col in df.columns:
                if df[col].isna().sum() == 0:
                    df[col] = df[col].astype("int64")
                else:
                    df[col] = df[col].astype("Int64")

        # Cast floats
        float_candidates = ["income", "loan_amount"]
        for col in float_candidates:
            if col in df.columns:
                df[col] = df[col].astype(float)

        op_params = {
            "dropped_columns": dropped_cols,
            "rows_before": initial_rows,
            "rows_after": len(df),
            "rules": [
                "drop_id",
                "drop_missing_target",
                "strip_normalize_categoricals",
                "cast_types_nullable",
            ],
        }

        # 3. Register cleaned dataset as new child version
        new_version_id = str(uuid.uuid4())
        clean_csv_bytes = df.to_csv(index=False).encode("utf-8")
        clean_file_hash = compute_file_hash(clean_csv_bytes)
        chunks = split_csv_into_chunks(clean_csv_bytes, chunk_rows=1000)
        clean_merkle_root, clean_levels = build_merkle_tree(chunks)

        meta_dict = {
            "version_id": new_version_id,
            "dataset_id": dataset_id,
            "parent_version_id": v_id,
            "filename": "cleaned_dataset.csv",
            "size_bytes": len(clean_csv_bytes),
            "num_chunks": len(chunks),
            "chunk_rows": 1000,
            "file_hash": clean_file_hash,
            "merkle_root": clean_merkle_root,
            "provenance": {
                "operation_type": "preprocess_clean",
                "operation_params": op_params,
                "software_versions": get_software_versions(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        metadata_digest = compute_canonical_metadata_digest(meta_dict)
        meta_dict["metadata_digest"] = metadata_digest

        # Save off-chain files
        new_upload_dir = storage_root / "uploads" / dataset_id / new_version_id
        new_upload_dir.mkdir(parents=True, exist_ok=True)
        (new_upload_dir / "cleaned_dataset.csv").write_bytes(clean_csv_bytes)

        trees_dir = storage_root / "trees"
        trees_dir.mkdir(parents=True, exist_ok=True)
        with open(trees_dir / f"{new_version_id}.json", "w", encoding="utf-8") as f:
            json.dump({"root": clean_merkle_root, "levels": clean_levels}, f, indent=2)

        meta_dir = storage_root / "metadata"
        meta_dir.mkdir(parents=True, exist_ok=True)
        with open(meta_dir / f"{new_version_id}.json", "w", encoding="utf-8") as f:
            json.dump(meta_dict, f, indent=2)

        # 4. Anchor on-chain
        try:
            receipt = client.register_version(
                dataset_id=dataset_id,
                version_id=new_version_id,
                parent_version_id=v_id,
                file_hash=clean_file_hash,
                merkle_root=clean_merkle_root,
                num_chunks=len(chunks),
                metadata_digest=metadata_digest,
            )
            receipts_dir = storage_root / "receipts"
            receipts_dir.mkdir(parents=True, exist_ok=True)
            with open(receipts_dir / f"{new_version_id}.json", "w", encoding="utf-8") as f:
                json.dump(receipt, f, indent=2)

            return {
                "version_id": new_version_id,
                "dataset_id": dataset_id,
                "parent_version_id": v_id,
                "metadata": meta_dict,
                "receipt": receipt,
            }
        except Exception:
            shutil.rmtree(new_upload_dir, ignore_errors=True)
            (trees_dir / f"{new_version_id}.json").unlink(missing_ok=True)
            (meta_dir / f"{new_version_id}.json").unlink(missing_ok=True)
            raise

    finally:
        shutil.rmtree(temp_gate_dir, ignore_errors=True)


# -----------------------------------------------------------------------------
# 2. Gate & Model Training (Steps 45-49)
# -----------------------------------------------------------------------------

def train_on_version(
    version_id: str | uuid.UUID,
    config: dict[str, Any] | None = None,
    storage_dir: Path | str | None = None,
    chain_client: ChainClient | None = None,
) -> dict[str, Any]:
    """Pre-training verification gate and model training."""
    v_id = str(version_id)
    client = chain_client or default_chain_client
    storage_root = Path(storage_dir or os.getenv("STORAGE_DIR", "./storage")).resolve()

    parent_rec = client.get_version(v_id)
    dataset_id = parent_rec["dataset_id"]
    stored_file = _locate_stored_file(storage_root, dataset_id, v_id)

    # TOCTOU Protection: Copy file to private temp dir, gate-verify copy, load from copy
    temp_gate_dir = Path(tempfile.mkdtemp(prefix="gate_train_toctou_"))
    try:
        temp_copy = temp_gate_dir / stored_file.name
        shutil.copy2(stored_file, temp_copy)

        t_gate_start = time.perf_counter()
        gate_res = verify_version(v_id, file_path=temp_copy, storage_dir=storage_root, chain_client=client)
        gate_time_ms = (time.perf_counter() - t_gate_start) * 1000.0

        if gate_res["status"] != "VERIFIED":
            raise IntegrityGateError(gate_res["status"], gate_res)

        # Read and prepare features strictly from verified copy
        df = pd.read_csv(temp_copy)
        target_col = "approved" if "approved" in df.columns else df.columns[-1]
        y = df[target_col].astype(int)
        X = df.drop(columns=[target_col])
        if "id" in X.columns:
            X = X.drop(columns=["id"])

        cfg = config or {}
        seed = int(cfg.get("seed", 42))
        test_size = float(cfg.get("test_size", 0.2))
        n_estimators = int(cfg.get("n_estimators", 100))
        max_depth = cfg.get("max_depth", None)
        n_jobs = int(cfg.get("n_jobs", 1))

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=seed, stratify=y
        )

        numeric_cols = [c for c in X.columns if pd.api.types.is_numeric_dtype(X[c])]
        categorical_cols = [c for c in X.columns if c not in numeric_cols]

        numeric_pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ])
        categorical_pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ])

        preprocessor = ColumnTransformer(transformers=[
            ("num", numeric_pipeline, numeric_cols),
            ("cat", categorical_pipeline, categorical_cols),
        ])

        clf = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            n_jobs=n_jobs,
            random_state=seed,
        )

        model_pipeline = Pipeline([
            ("preprocessor", preprocessor),
            ("classifier", clf),
        ])

        t_train_start = time.perf_counter()
        model_pipeline.fit(X_train, y_train)
        train_time_ms = (time.perf_counter() - t_train_start) * 1000.0

        # Evaluation metrics on test split
        y_pred = model_pipeline.predict(X_test)
        y_prob = model_pipeline.predict_proba(X_test)

        metrics = {
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 6),
            "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 6),
            "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 6),
            "f1": round(float(f1_score(y_test, y_pred, zero_division=0)), 6),
            "roc_auc": round(float(roc_auc_score(y_test, y_prob[:, 1])), 6),
        }

        # Deterministic SHA-256 of test predictions
        pred_list = y_pred.tolist()
        test_predictions_sha256 = hashlib.sha256(
            json.dumps(pred_list, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        run_id = str(uuid.uuid4())

        # Save model artifact
        models_dir = storage_root / "models" / run_id
        models_dir.mkdir(parents=True, exist_ok=True)
        model_path = models_dir / "model.joblib"
        joblib.dump(model_pipeline, model_path)
        model_artifact_sha256 = compute_file_hash(model_path.read_bytes())

        # Build off-chain experiment record
        record: dict[str, Any] = {
            "run_id": run_id,
            "dataset_version_id": v_id,
            "dataset_id": dataset_id,
            "input_file_hash": gate_res["details"]["expected_file_hash"],
            "input_merkle_root": gate_res["details"]["expected_merkle_root"],
            "gate_result_summary": {
                "status": "VERIFIED",
                "gate_time_ms": round(gate_time_ms, 3),
            },
            "preprocessing_config": {
                "numeric_imputer": "SimpleImputer(median)",
                "numeric_scaler": "StandardScaler",
                "categorical_imputer": "SimpleImputer(most_frequent)",
                "categorical_encoder": "OneHotEncoder(handle_unknown='ignore')",
            },
            "split_config": {
                "test_size": test_size,
                "stratified": True,
                "train_rows": len(X_train),
                "test_rows": len(X_test),
                "random_state": seed,
            },
            "model_params": {
                "classifier": "RandomForestClassifier",
                "n_estimators": n_estimators,
                "max_depth": max_depth,
                "n_jobs": n_jobs,
                "random_state": seed,
            },
            "random_seed": seed,
            "software_versions": get_software_versions(),
            "metrics": metrics,
            "test_predictions_sha256": test_predictions_sha256,
            "model_artifact_sha256": model_artifact_sha256,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        experiment_digest = compute_canonical_metadata_digest(record)
        record["experiment_digest"] = experiment_digest

        exp_dir = storage_root / "experiments"
        exp_dir.mkdir(parents=True, exist_ok=True)
        exp_path = exp_dir / f"{run_id}.json"
        with open(exp_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

        # Anchor on-chain
        try:
            # Timing the transaction latency
            t_tx_start = time.perf_counter()
            receipt = client.record_training_run(
                run_id=run_id,
                dataset_version_id=v_id,
                experiment_digest=experiment_digest,
            )
            tx_latency_ms = (time.perf_counter() - t_tx_start) * 1000.0
            with open(exp_dir / f"{run_id}.receipt.json", "w", encoding="utf-8") as f:
                json.dump(receipt, f, indent=2)

            return {
                "run_id": run_id,
                "dataset_version_id": v_id,
                "metrics": metrics,
                "experiment_record": record,
                "receipt": receipt,
                "timings_ms": {
                    "gate_time_ms": round(gate_time_ms, 3),
                    "train_time_ms": round(train_time_ms, 3),
                    "tx_latency_ms": round(tx_latency_ms, 3),
                },
            }
        except Exception:
            shutil.rmtree(models_dir, ignore_errors=True)
            exp_path.unlink(missing_ok=True)
            raise

    finally:
        shutil.rmtree(temp_gate_dir, ignore_errors=True)


# -----------------------------------------------------------------------------
# 3. Reproducibility Check Workflow (Step 50)
# -----------------------------------------------------------------------------

def reproduce_training_run(
    run_id: str | uuid.UUID,
    storage_dir: Path | str | None = None,
    chain_client: ChainClient | None = None,
) -> dict[str, Any]:
    """Deterministic reproducibility check without writing to storage or blockchain."""
    r_id = str(run_id)
    client = chain_client or default_chain_client
    storage_root = Path(storage_dir or os.getenv("STORAGE_DIR", "./storage")).resolve()

    # 1. Read run record from chain
    chain_run = client.get_run(r_id)
    dataset_version_id = chain_run["dataset_version_id"]

    # 2. Load off-chain experiment record
    exp_path = storage_root / "experiments" / f"{r_id}.json"
    if not exp_path.exists():
        return {
            "status": "NOT_REPRODUCIBLE",
            "reason": f"Experiment record file not found: {exp_path}",
            "run_id": r_id,
        }

    with open(exp_path, "r", encoding="utf-8") as f:
        record = json.load(f)

    # 3. Recompute canonical digest and verify against blockchain
    meta_copy = {k: v for k, v in record.items() if k != "experiment_digest"}
    recomputed_digest = compute_canonical_metadata_digest(meta_copy)
    on_chain_digest = _strip_0x(chain_run["experiment_digest"])
    if recomputed_digest.lower() != on_chain_digest.lower():
        return {
            "status": "RECORD_TAMPERED",
            "reason": "Off-chain experiment record digest does not match on-chain digest.",
            "run_id": r_id,
        }

    # Verify record's input hashes against on-chain version record
    chain_version = client.get_version(dataset_version_id)
    expected_v_file_hash = _strip_0x(chain_version["file_hash"])
    expected_v_merkle_root = _strip_0x(chain_version["merkle_root"])

    if (
        record.get("input_file_hash", "").lower() != expected_v_file_hash.lower()
        or record.get("input_merkle_root", "").lower() != expected_v_merkle_root.lower()
    ):
        return {
            "status": "RECORD_TAMPERED",
            "reason": "Recorded input hashes do not match on-chain version record.",
            "run_id": r_id,
        }

    # 4. Check model artifact intactness (hashing only, never unpickling)
    model_path = storage_root / "models" / r_id / "model.joblib"
    model_artifact_intact = False
    if model_path.exists():
        actual_model_hash = compute_file_hash(model_path.read_bytes())
        model_artifact_intact = (actual_model_hash.lower() == record["model_artifact_sha256"].lower())

    # 5. Gate check on dataset version with TOCTOU copy
    stored_file = _locate_stored_file(storage_root, chain_version["dataset_id"], dataset_version_id)
    temp_repro_dir = Path(tempfile.mkdtemp(prefix="repro_gate_toctou_"))
    try:
        temp_copy = temp_repro_dir / stored_file.name
        shutil.copy2(stored_file, temp_copy)

        gate_res = verify_version(
            dataset_version_id, file_path=temp_copy, storage_dir=storage_root, chain_client=client
        )
        if gate_res["status"] != "VERIFIED":
            return {
                "status": "BLOCKED_BY_GATE",
                "reason": f"Dataset version failed verification gate: {gate_res['status']}",
                "run_id": r_id,
                "gate_result": gate_res,
                "model_artifact_intact": model_artifact_intact,
            }

        # 6. Retrain model in memory / isolated temp location with identical seed & config
        df = pd.read_csv(temp_copy)
        target_col = "approved" if "approved" in df.columns else df.columns[-1]
        y = df[target_col].astype(int)
        X = df.drop(columns=[target_col])
        if "id" in X.columns:
            X = X.drop(columns=["id"])

        split_cfg = record["split_config"]
        seed = int(record["random_seed"])
        test_size = float(split_cfg.get("test_size", 0.2))

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=seed, stratify=y
        )

        numeric_cols = [c for c in X.columns if pd.api.types.is_numeric_dtype(X[c])]
        categorical_cols = [c for c in X.columns if c not in numeric_cols]

        numeric_pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ])
        categorical_pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ])

        preprocessor = ColumnTransformer(transformers=[
            ("num", numeric_pipeline, numeric_cols),
            ("cat", categorical_pipeline, categorical_cols),
        ])

        model_params = record["model_params"]
        clf = RandomForestClassifier(
            n_estimators=int(model_params.get("n_estimators", 100)),
            max_depth=model_params.get("max_depth"),
            n_jobs=int(model_params.get("n_jobs", 1)),
            random_state=seed,
        )

        pipeline = Pipeline([
            ("preprocessor", preprocessor),
            ("classifier", clf),
        ])
        pipeline.fit(X_train, y_train)

        repro_pred = pipeline.predict(X_test)
        repro_prob = pipeline.predict_proba(X_test)

        repro_metrics = {
            "accuracy": round(float(accuracy_score(y_test, repro_pred)), 6),
            "precision": round(float(precision_score(y_test, repro_pred, zero_division=0)), 6),
            "recall": round(float(recall_score(y_test, repro_pred, zero_division=0)), 6),
            "f1": round(float(f1_score(y_test, repro_pred, zero_division=0)), 6),
            "roc_auc": round(float(roc_auc_score(y_test, repro_prob[:, 1])), 6),
        }

        repro_pred_hash = hashlib.sha256(
            json.dumps(repro_pred.tolist(), separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        # Temporary artifact hashing without touching real storage
        temp_model_path = temp_repro_dir / "temp_repro_model.joblib"
        joblib.dump(pipeline, temp_model_path)
        repro_model_hash = compute_file_hash(temp_model_path.read_bytes())

        metrics_match = (repro_metrics == record["metrics"])
        predictions_match = (repro_pred_hash == record["test_predictions_sha256"])
        model_artifact_hash_match = (repro_model_hash == record["model_artifact_sha256"])

        curr_sw = get_software_versions()
        differing_sw = {
            pkg: {"recorded": record["software_versions"].get(pkg), "current": curr_sw.get(pkg)}
            for pkg in curr_sw
            if curr_sw.get(pkg) != record["software_versions"].get(pkg)
        }

        if metrics_match and predictions_match:
            status = "REPRODUCED"
            reason = "Exact match on evaluation metrics and test predictions."
        else:
            status = "NOT_REPRODUCED"
            reason = "Evaluation metrics or predictions hash differed."

        return {
            "status": status,
            "reason": reason,
            "run_id": r_id,
            "metrics_match": metrics_match,
            "predictions_match": predictions_match,
            "model_artifact_hash_match": model_artifact_hash_match,
            "model_artifact_intact": model_artifact_intact,
            "original_metrics": record["metrics"],
            "reproduced_metrics": repro_metrics,
            "differing_software_versions": differing_sw,
        }

    finally:
        shutil.rmtree(temp_repro_dir, ignore_errors=True)
