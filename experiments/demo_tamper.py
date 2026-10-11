"""Demonstration script for controlled tampering attacks and integrity verification.

Copies off-chain storage to an isolated temporary directory to ensure zero side-effects
on production or benchmark data.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.chain import default_chain_client
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


def run_demo():
    print("==================================================================")
    print("      PHASE 5: INTEGRITY VERIFICATION & TAMPERING DEMO            ")
    print("==================================================================")

    # 1. Check live blockchain connection
    if not default_chain_client.w3.is_connected():
        print("[ERROR] Hardhat blockchain node is unreachable at http://127.0.0.1:8545", file=sys.stderr)
        sys.exit(1)

    real_storage = Path("./storage").resolve()
    if not (real_storage / "uploads").exists():
        print("[ERROR] storage/uploads does not exist. Run experiments/demo_versions.py first.", file=sys.stderr)
        sys.exit(1)

    # Find the most recently modified dataset in storage/uploads
    datasets = [d for d in (real_storage / "uploads").iterdir() if d.is_dir() and not d.name.startswith(".")]
    if not datasets:
        print("[ERROR] No datasets found in storage/uploads. Run experiments/demo_versions.py first.", file=sys.stderr)
        sys.exit(1)

    datasets.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    target_dataset = datasets[0]
    dataset_id = target_dataset.name

    # Retrieve all versions from blockchain
    chain_versions = default_chain_client.get_dataset_versions(dataset_id)
    if len(chain_versions) < 2:
        print(f"[ERROR] Dataset {dataset_id} requires at least 2 versions for demo (found {len(chain_versions)}).", file=sys.stderr)
        sys.exit(1)

    v1_id = chain_versions[0]
    v2_id = chain_versions[1]
    v3_id = chain_versions[2] if len(chain_versions) > 2 else v2_id

    print(f"Target Dataset ID : {dataset_id}")
    print(f"Base Version (v1) : {v1_id}")
    print(f"Child Version (v2): {v2_id}")
    print(f"Child Version (v3): {v3_id}")

    # 2. Baseline clean verification
    clean_res = verify_version(v2_id, storage_dir=real_storage)
    print(f"\n[Baseline] Unmodified v2 Verification: {clean_res['status']} ({clean_res['timings_ms']['total_ms']} ms)")

    # 3. Setup temporary isolated copy of storage
    temp_dir = Path(tempfile.mkdtemp(prefix="tamper_demo_")).resolve()
    try:
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        print(f"[Isolated Storage] Working directory: {temp_dir}\n")

        results = []

        def get_v_csv(v_id: str) -> Path:
            v_dir = temp_dir / "uploads" / dataset_id / v_id
            files = [f for f in v_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
            return files[0]

        # Attack 1: Modify cells
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        csv_p = get_v_csv(v2_id)
        modify_cells(csv_p, fraction=0.01)
        res = verify_version(v2_id, storage_dir=temp_dir)
        results.append(("modify_cells (1%)", res))

        # Attack 2: Delete rows
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        csv_p = get_v_csv(v2_id)
        delete_rows(csv_p, fraction=0.01)
        res = verify_version(v2_id, storage_dir=temp_dir)
        results.append(("delete_rows (1%)", res))

        # Attack 3: Insert rows
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        csv_p = get_v_csv(v2_id)
        insert_rows(csv_p, fraction=0.01)
        res = verify_version(v2_id, storage_dir=temp_dir)
        results.append(("insert_rows (1%)", res))

        # Attack 4: Flip labels
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        csv_p = get_v_csv(v2_id)
        flip_labels(csv_p, fraction=0.01)
        res = verify_version(v2_id, storage_dir=temp_dir)
        results.append(("flip_labels (1%)", res))

        # Attack 5: Swap columns
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        csv_p = get_v_csv(v2_id)
        swap_columns(csv_p)
        res = verify_version(v2_id, storage_dir=temp_dir)
        results.append(("swap_columns", res))

        # Attack 6: Replace file
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        csv_p = get_v_csv(v2_id)
        replace_file(csv_p)
        res = verify_version(v2_id, storage_dir=temp_dir)
        results.append(("replace_file", res))

        # Attack 7: Rollback to version (replace v2 with v1)
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        v1_csv = get_v_csv(v1_id)
        v2_csv = get_v_csv(v2_id)
        rollback_to_version(v2_csv, v1_csv)
        res = verify_version(v2_id, storage_dir=temp_dir)
        results.append(("rollback_to_version (v2->v1)", res))

        # Attack 8: Modify preprocessing output (tamper v3)
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        v3_csv = get_v_csv(v3_id)
        modify_preprocessing_output(v3_csv, fraction=0.01)
        res = verify_version(v3_id, storage_dir=temp_dir)
        results.append(("modify_preprocessing_output (v3)", res))

        # Attack 9: Forge off-chain metadata (edit parent pointer)
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        meta_p = temp_dir / "metadata" / f"{v2_id}.json"
        forge_metadata(meta_p, field="parent_version_id", new_value="11111111-2222-3333-4444-555555555555")
        res = verify_version(v2_id, storage_dir=temp_dir)
        results.append(("forge_metadata (parent_id)", res))

        # Attack 10: Consistent local forgery (alter file + tree + metadata)
        shutil.copytree(real_storage, temp_dir, dirs_exist_ok=True)
        consistent_local_forgery(temp_dir, dataset_id, v2_id, tamper_fraction=0.01)
        res = verify_version(v2_id, storage_dir=temp_dir)
        results.append(("consistent_local_forgery", res))

        # 4. Print Results Table
        header = f"| {'Attack':<34} | {'Status':<18} | {'Failed Checks':<30} | {'Changed Chunks':<14} | {'Matched Version':<17} | {'Latency':<8} |"
        sep = f"|{'-'*36}|{'-'*20}|{'-'*32}|{'-'*16}|{'-'*19}|{'-'*10}|"
        print("\n" + header)
        print(sep)

        for attack_name, r in results:
            failed = [k for k, v in r["checks"].items() if v is False]
            failed_str = ", ".join(failed) if failed else "None"
            changed = str(r["details"].get("changed_chunks", []))
            if len(changed) > 14:
                changed = changed[:11] + "..."
            matched = str(r["details"].get("matches_version_id") or "None")
            if len(matched) > 17:
                matched = matched[:14] + "..."
            time_ms = f"{r['timings_ms']['total_ms']} ms"

            row = f"| {attack_name:<34} | {r['status']:<18} | {failed_str:<30} | {changed:<14} | {matched:<17} | {time_ms:<8} |"
            print(row)

        print(sep + "\n")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print("[Cleanup] Temporary isolated storage removed.")


if __name__ == "__main__":
    run_demo()
