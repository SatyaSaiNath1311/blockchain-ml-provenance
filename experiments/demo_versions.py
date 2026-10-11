import io
import json
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import requests
from sklearn.preprocessing import MinMaxScaler

from experiments.make_synthetic_csv import generate_synthetic_csv

BASE_URL = "http://127.0.0.1:8000"


def main():
    print("=================================================================")
    print("      PHASE 4: MULTI-VERSION PROVENANCE PIPELINE DEMO            ")
    print("=================================================================")

    # 1. Health check
    try:
        health_res = requests.get(f"{BASE_URL}/health", timeout=3)
        health_res.raise_for_status()
        print(f"[1/5] Backend health check: OK (phase: {health_res.json().get('phase')})")
    except Exception as exc:
        print(f"[ERROR] Cannot connect to API at {BASE_URL}: {exc}", file=sys.stderr)
        print("Ensure uvicorn is running: ./venv/bin/uvicorn backend.main:app --port 8000", file=sys.stderr)
        sys.exit(1)

    # 2. Prepare base dataset
    csv_path = Path("experiments/data/synthetic_ml_data.csv")
    if not csv_path.exists():
        print("[2/5] Synthetic CSV missing, generating now...")
        generate_synthetic_csv(csv_path, num_rows=5000, seed=42)
    else:
        print(f"[2/5] Using existing synthetic CSV: {csv_path} ({csv_path.stat().st_size} bytes)")

    receipts_by_version = {}

    # 3. Upload v1 (Root)
    print("\n--- Step 1: Upload Root Version (v1: ingest) ---")
    with open(csv_path, "rb") as f:
        v1_upload = requests.post(
            f"{BASE_URL}/datasets",
            files={"file": (csv_path.name, f, "text/csv")},
            data={"chunk_rows": "1000"},
        )
    v1_upload.raise_for_status()
    v1_json = v1_upload.json()
    v1_meta = v1_json["metadata"]
    v1_receipt = v1_json["receipt"]

    dataset_id = v1_meta["dataset_id"]
    v1_id = v1_meta["version_id"]
    code_hash = v1_meta["provenance"]["code_commit_hash"]
    code_dirty = v1_meta["provenance"]["code_dirty"]
    receipts_by_version[v1_id] = v1_receipt

    print(f" Dataset ID       : {dataset_id}")
    print(f" Root Version ID  : {v1_id}")
    print(f" Code Commit Hash : {code_hash}")
    print(f" Code Dirty State : {code_dirty}")
    print(f" File Hash        : {v1_meta['file_hash']}")
    print(f" Merkle Root      : {v1_meta['merkle_root']}")
    print(f" Num Chunks       : {v1_meta['num_chunks']}")
    print(f" Tx Hash          : {v1_receipt['tx_hash']}")
    print(f" Block Number     : {v1_receipt['block_number']}")
    print(f" Gas Used         : {v1_receipt['gas_used']}")

    # 4. Create v2 (Deduplicate / Filter)
    print("\n--- Step 2: Create Version 2 (v2: deduplicate) ---")
    df = pd.read_csv(csv_path)
    initial_rows = len(df)
    # Deduplicate across ALL columns
    df_v2 = df.drop_duplicates(keep="first")
    v2_rows = len(df_v2)

    print(f" Rows before dedup: {initial_rows}")
    print(f" Rows after dedup : {v2_rows} (dropped {initial_rows - v2_rows}, retained {v2_rows / initial_rows * 100:.1f}%)")

    v2_buffer = io.BytesIO()
    df_v2.to_csv(v2_buffer, index=False)
    v2_bytes = v2_buffer.getvalue()

    v2_upload = requests.post(
        f"{BASE_URL}/datasets/{dataset_id}/versions",
        files={"file": ("synthetic_v2_dedup.csv", io.BytesIO(v2_bytes), "text/csv")},
        data={
            "parent_version_id": v1_id,
            "operation_type": "deduplicate",
            "operation_params": json.dumps({"rows_before": initial_rows, "rows_after": v2_rows}),
            "chunk_rows": "1000",
        },
    )
    v2_upload.raise_for_status()
    v2_json = v2_upload.json()
    v2_meta = v2_json["metadata"]
    v2_receipt = v2_json["receipt"]
    v2_id = v2_meta["version_id"]
    receipts_by_version[v2_id] = v2_receipt

    print(f" Version 2 ID     : {v2_id}")
    print(f" Parent Version ID: {v2_meta['parent_version_id']}")
    print(f" Operation Type   : {v2_meta['provenance']['operation_type']}")
    print(f" Operation Params : {v2_meta['provenance']['operation_params']}")
    print(f" Rows Transformed : {initial_rows} -> {v2_rows}")
    print(f" Merkle Root      : {v2_meta['merkle_root']}")
    print(f" Tx Hash          : {v2_receipt['tx_hash']}")
    print(f" Block Number     : {v2_receipt['block_number']}")
    print(f" Gas Used         : {v2_receipt['gas_used']}")

    # 5. Create v3 (Min-Max Scaling)
    print("\n--- Step 3: Create Version 3 (v3: min_max_scale) ---")
    df_v3 = df_v2.copy()
    numeric_cols = ["age", "income", "credit_score", "loan_amount"]
    scaler = MinMaxScaler()
    df_v3[numeric_cols] = scaler.fit_transform(df_v3[numeric_cols])

    v3_buffer = io.BytesIO()
    df_v3.to_csv(v3_buffer, index=False)
    v3_bytes = v3_buffer.getvalue()

    v3_upload = requests.post(
        f"{BASE_URL}/datasets/{dataset_id}/versions",
        files={"file": ("synthetic_v3_scaled.csv", io.BytesIO(v3_bytes), "text/csv")},
        data={
            "parent_version_id": v2_id,
            "operation_type": "min_max_scale",
            "operation_params": json.dumps({"scaled_columns": numeric_cols, "range": [0, 1]}),
            "chunk_rows": "1000",
        },
    )
    v3_upload.raise_for_status()
    v3_json = v3_upload.json()
    v3_meta = v3_json["metadata"]
    v3_receipt = v3_json["receipt"]
    v3_id = v3_meta["version_id"]
    receipts_by_version[v3_id] = v3_receipt

    print(f" Version 3 ID     : {v3_id}")
    print(f" Parent Version ID: {v3_meta['parent_version_id']}")
    print(f" Operation Type   : {v3_meta['provenance']['operation_type']}")
    print(f" Scaled Columns   : {numeric_cols}")
    print(f" Merkle Root      : {v3_meta['merkle_root']}")
    print(f" Tx Hash          : {v3_receipt['tx_hash']}")
    print(f" Block Number     : {v3_receipt['block_number']}")
    print(f" Gas Used         : {v3_receipt['gas_used']}")

    # 6. Retrieve On-Chain Lineage
    print("\n--- Step 4: Reconstruct On-Chain Lineage ---")
    lineage_res = requests.get(f"{BASE_URL}/versions/{v3_id}/lineage")
    lineage_res.raise_for_status()
    lineage = lineage_res.json()

    print(f"Ancestors retrieved from blockchain: {len(lineage)} version(s)\n")
    for idx, node in enumerate(lineage):
        parent_display = node["parent_version_id"] if node["parent_version_id"] else "None (Root)"
        v_receipt = receipts_by_version.get(node["version_id"], {})
        block_num = v_receipt.get("block_number", node.get("block_number", "N/A"))
        print(f" [{idx + 1}] Version: {node['version_id']}")
        print(f"     Parent       : {parent_display}")
        print(f"     Merkle Root  : {node['merkle_root']}")
        print(f"     Num Chunks   : {node['num_chunks']}")
        print(f"     Block Number : {block_num}")
        print(f"     Timestamp    : {node['timestamp']}")

    total_gas = int(v1_receipt["gas_used"]) + int(v2_receipt["gas_used"]) + int(v3_receipt["gas_used"])

    print("\n==================== PIPELINE SUMMARY ====================")
    print(f" Dataset UUID    : {dataset_id}")
    print(f" Git Revision    : {code_hash} (dirty={code_dirty})")
    print(f" v1 (Root) Gas   : {v1_receipt['gas_used']} (block {v1_receipt['block_number']})")
    print(f" v2 (Child) Gas  : {v2_receipt['gas_used']} (block {v2_receipt['block_number']})")
    print(f" v3 (Child) Gas  : {v3_receipt['gas_used']} (block {v3_receipt['block_number']})")
    print(f" Total Gas Used  : {total_gas}")
    print("=========================================================\n")


if __name__ == "__main__":
    main()
