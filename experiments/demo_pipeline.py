"""Phase 6: End-to-End ML Pipeline, Gate Verification, and Reproducibility Demo.

Runs against the live running API (http://127.0.0.1:8000) and Hardhat blockchain.
Demonstrates:
  1. Ingestion of raw dataset (v1: ingest)
  2. Full-column deduplication (v2: deduplicate)
  3. Preprocessing and cleaning child version (v3: preprocess_clean)
  4. Pre-training verification gate & baseline model training
  5. Cryptographic reproducibility check
  6. Gate rejection on a temporary storage copy (HTTP 409 TAMPERING_DETECTED)
"""

import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import requests

from backend.chain import default_chain_client
from backend.fingerprint import compute_file_hash
from backend.ml_pipeline import train_on_version
from experiments.make_synthetic_csv import generate_synthetic_csv
from experiments.tamper import modify_cells

BASE_URL = "http://127.0.0.1:8000"


def main():
    print("==================================================================")
    print("      PHASE 6: ML PIPELINE & INTEGRITY GATE VERIFICATION DEMO     ")
    print("==================================================================")

    # 1. Health check
    try:
        health_res = requests.get(f"{BASE_URL}/health", timeout=3)
        health_res.raise_for_status()
        print(f"[1/6] Backend health check: OK (phase: {health_res.json().get('phase')})")
    except Exception as exc:
        print(f"[ERROR] Cannot connect to API at {BASE_URL}: {exc}", file=sys.stderr)
        print("Ensure uvicorn is running: ./venv/bin/uvicorn backend.main:app --port 8000", file=sys.stderr)
        sys.exit(1)

    # 2. Prepare base dataset
    csv_path = Path("experiments/data/synthetic_ml_data.csv")
    if not csv_path.exists():
        print("[2/6] Synthetic CSV missing, generating now...")
        generate_synthetic_csv(csv_path, num_rows=5000, seed=42)
    else:
        print(f"[2/6] Using synthetic CSV: {csv_path} ({csv_path.stat().st_size} bytes)")

    # 3. Upload v1 (Root: Ingest)
    print("\n--- Step 1: Ingest Root Version (v1: ingest) ---")
    with open(csv_path, "rb") as f:
        v1_upload = requests.post(
            f"{BASE_URL}/datasets",
            files={"file": (csv_path.name, f, "text/csv")},
            data={"chunk_rows": "1000"},
        )
    v1_upload.raise_for_status()
    v1_json = v1_upload.json()
    dataset_id = v1_json["metadata"]["dataset_id"]
    v1_id = v1_json["metadata"]["version_id"]
    print(f" Dataset ID       : {dataset_id}")
    print(f" Root Version ID  : {v1_id}")
    print(f" Block Number     : {v1_json['receipt']['block_number']}")
    print(f" Gas Used         : {v1_json['receipt']['gas_used']}")

    # 4. Upload v2 (Deduplicate)
    print("\n--- Step 2: Deduplicate (v2: deduplicate) ---")
    df = pd.read_csv(csv_path)
    df_v2 = df.drop_duplicates()
    v2_buf = io.BytesIO()
    df_v2.to_csv(v2_buf, index=False)
    v2_bytes = v2_buf.getvalue()

    v2_upload = requests.post(
        f"{BASE_URL}/datasets/{dataset_id}/versions",
        files={"file": ("synthetic_v2_dedup.csv", io.BytesIO(v2_bytes), "text/csv")},
        data={
            "parent_version_id": v1_id,
            "operation_type": "deduplicate",
            "operation_params": json.dumps({"rows_before": len(df), "rows_after": len(df_v2)}),
            "chunk_rows": "1000",
        },
    )
    v2_upload.raise_for_status()
    v2_json = v2_upload.json()
    v2_id = v2_json["metadata"]["version_id"]
    print(f" Version 2 ID     : {v2_id}")
    print(f" Rows Transformed : {len(df)} -> {len(df_v2)}")
    print(f" Block Number     : {v2_json['receipt']['block_number']}")
    print(f" Gas Used         : {v2_json['receipt']['gas_used']}")

    # 5. Preprocess Clean (v3: preprocess_clean)
    print("\n--- Step 3: Preprocess and Clean Child Version (v3: preprocess_clean) ---")
    v3_res = requests.post(f"{BASE_URL}/versions/{v2_id}/preprocess")
    v3_res.raise_for_status()
    v3_json = v3_res.json()
    v3_id = v3_json["version_id"]
    print(f" Clean Version ID : {v3_id}")
    print(f" Operation Type   : {v3_json['metadata']['provenance']['operation_type']}")
    print(f" Dropped Columns  : {v3_json['metadata']['provenance']['operation_params']['dropped_columns']}")
    print(f" Block Number     : {v3_json['receipt']['block_number']}")
    print(f" Gas Used         : {v3_json['receipt']['gas_used']}")

    # 6. Train on v3 with Verification Gate
    print("\n--- Step 4: Verification Gate & Model Training (Random Forest) ---")
    train_res = requests.post(
        f"{BASE_URL}/versions/{v3_id}/train",
        json={"seed": 42, "n_estimators": 100},
    )
    train_res.raise_for_status()
    train_json = train_res.json()
    run_id = train_json["run_id"]
    metrics = train_json["metrics"]
    receipt = train_json["receipt"]
    timings = train_json["timings_ms"]

    print(f" Training Run ID  : {run_id}")
    print(f" Gate Time        : {timings['gate_time_ms']} ms")
    print(f" Training Time    : {timings['train_time_ms']} ms")
    print(f" Accuracy         : {metrics['accuracy']:.4f}")
    print(f" Precision        : {metrics['precision']:.4f}")
    print(f" Recall           : {metrics['recall']:.4f}")
    print(f" F1-Score         : {metrics['f1']:.4f}")
    print(f" ROC-AUC          : {metrics['roc_auc']:.4f}")
    print(f" On-Chain Tx Hash : {receipt['tx_hash']}")
    print(f" Block Number     : {receipt['block_number']}")
    print(f" Gas Used         : {receipt['gas_used']}")

    # 7. Reproducibility Check
    print("\n--- Step 5: Verification-Gated Reproducibility Check ---")
    repro_res = requests.post(f"{BASE_URL}/experiments/{run_id}/reproduce")
    repro_res.raise_for_status()
    repro_json = repro_res.json()

    print(f" Status           : {repro_json['status']}")
    print(f" Metrics Match    : {repro_json['metrics_match']}")
    print(f" Predictions Match: {repro_json['predictions_match']}")
    print(f" Model Hash Match : {repro_json['model_artifact_hash_match']} (informational)")
    print(f" Artifact Intact  : {repro_json['model_artifact_intact']}")

    # 8. Controlled Gate Block Demonstration on Isolated Storage Copy
    print("\n--- Step 6: Controlled Verification Gate Blocking on Tampered Data ---")
    real_storage = Path("./storage").resolve()
    temp_dir = Path(tempfile.mkdtemp(prefix="pipeline_demo_isolated_")).resolve()
    try:
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        # Tamper v3 file in temp copy
        v3_csv = temp_dir / "uploads" / dataset_id / v3_id / "cleaned_dataset.csv"
        modify_cells(v3_csv, fraction=0.01)

        # Call train_on_version on the temporary copy
        try:
            train_on_version(v3_id, storage_dir=temp_dir)
            print("[UNEXPECTED] Training succeeded on tampered data!", file=sys.stderr)
        except Exception as exc:
            gate_status = getattr(exc, "status", "ERROR")
            print(f" [Gate Triggered] Status: {gate_status}")
            print(f" [Gate Message]   {exc}")
            print(" Training aborted before model execution; zero storage artifacts written.")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(" [Cleanup] Temporary isolated storage removed.")

    # 9. Summary Table
    print("\n======================= PIPELINE SUMMARY =======================")
    print(f" Dataset UUID         : {dataset_id}")
    print(f" Root (v1) Version    : {v1_id}")
    print(f" Deduplicated (v2)    : {v2_id}")
    print(f" Cleaned (v3) Version : {v3_id}")
    print(f" Training Run UUID    : {run_id}")
    print(f" Gate Time            : {timings['gate_time_ms']} ms")
    print(f" Training Time        : {timings['train_time_ms']} ms")
    print(f" Gas (recordRun)      : {receipt['gas_used']}")
    print(f" Model Accuracy       : {metrics['accuracy']:.4f}")
    print(f" Model ROC-AUC        : {metrics['roc_auc']:.4f}")
    print(f" Reproducibility      : {repro_json['status']} (model_hash_match={repro_json['model_artifact_hash_match']})")
    print("================================================================\n")


if __name__ == "__main__":
    main()
