"""Master execution script for Phase 7 evaluation benchmarks.

Orchestrates Experiments E1, E1b, E2, E3, E4, and E5 under the specified profile.
Enforces clean git state (unless --allow-dirty is provided).
Records comprehensive run metadata in run_metadata.json.
"""

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.chain import ChainClient, default_chain_client
from experiments.eval.config import PROFILES, EvalProfile
from experiments.eval.e1_detection import run_e1_experiments
from experiments.eval.e2_timing import run_e2_experiments
from experiments.eval.e3_storage import run_e3_experiments
from experiments.eval.e4_chunksize import run_e4_experiments
from experiments.eval.e5_lineage import run_e5_experiments
from experiments.make_synthetic_csv import generate_synthetic_dataset


def check_git_status() -> tuple[str, bool]:
    """Check git revision and whether repository is dirty (ignoring experiments/results)."""
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()

        status_out = subprocess.check_output(
            ["git", "status", "--porcelain"], stderr=subprocess.DEVNULL
        ).decode("utf-8").strip()

        dirty_lines = [
            line for line in status_out.splitlines()
            if line.strip() and "experiments/results" not in line
        ]
        is_dirty = len(dirty_lines) > 0
        return commit, is_dirty
    except Exception:
        return "unknown", False


def get_environment_info(profile: EvalProfile, chain_client: ChainClient) -> dict:
    """Collect platform, software versions, and blockchain network parameters."""
    commit, is_dirty = check_git_status()

    # Software versions
    pkgs = ["pandas", "numpy", "scikit-learn", "scipy", "matplotlib", "joblib", "web3", "fastapi"]
    sw_versions = {"python": platform.python_version()}
    for p in pkgs:
        try:
            sw_versions[p] = importlib.metadata.version(p)
        except Exception:
            sw_versions[p] = "unknown"

    # Node & Hardhat versions
    node_ver = "unknown"
    try:
        node_ver = subprocess.check_output(["node", "--version"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        pass

    hardhat_ver = "unknown"
    try:
        hardhat_ver = subprocess.check_output(["npx", "hardhat", "--version"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        pass

    # Chain parameters
    chain_id = -1
    gas_limit = -1
    try:
        chain_id = chain_client.w3.eth.chain_id
        latest_block = chain_client.w3.eth.get_block("latest")
        gas_limit = latest_block.get("gasLimit", -1)
    except Exception:
        pass

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "git_dirty": is_dirty,
        "profile": profile.name,
        "trials_per_condition": profile.trials_per_condition,
        "clean_trials_fpr": profile.clean_trials_fpr,
        "base_seed": profile.base_seed,
        "chunk_rows": profile.e4_chunk_rows,
        "e4_dataset_label": profile.e4_dataset_label,
        "e4_note": (
            f"E4 chunk rows scaled for {profile.name} profile ({profile.e4_chunk_rows}) "
            f"producing >= 10 chunks on {profile.e4_dataset_label}."
        ),
        "estimated_runtime_seconds": round(profile.estimate_runtime_seconds(), 2),
        "software_versions": sw_versions,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "toolchain": {
            "node": node_ver,
            "hardhat": hardhat_ver,
        },
        "blockchain": {
            "chain_id": chain_id,
            "block_gas_limit": gas_limit,
            "contract_address": chain_client.contract_address,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Run Phase 7 evaluation benchmarks.")
    parser.add_argument("--profile", choices=["quick", "full"], default="quick", help="Benchmark profile")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow running on a dirty git working tree")
    parser.add_argument("--out-dir", type=str, default=None, help="Custom results output directory")
    args = parser.parse_args()

    commit, is_dirty = check_git_status()
    if is_dirty and not args.allow_dirty:
        print("ERROR: Git repository has uncommitted modifications.")
        print("Commit your changes or use --allow-dirty for test runs.")
        sys.exit(1)

    profile = PROFILES[args.profile]
    print(f"=== Starting Phase 7 Evaluation (Profile: {profile.name}) ===")
    est_runtime = profile.estimate_runtime_seconds()
    print(f"Estimated benchmark runtime: {est_runtime:.2f} seconds")

    # Connect chain client
    chain_client = default_chain_client

    # Prepare output directory: experiments/results/<UTC timestamp>_<commit>/
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    commit_short = commit[:7] if commit != "unknown" else "local"
    if args.out_dir:
        res_dir = Path(args.out_dir).resolve()
    else:
        res_dir = Path(f"experiments/results/{ts_str}_{commit_short}").resolve()
    res_dir.mkdir(parents=True, exist_ok=True)
    print(f"Results destination: {res_dir}")

    # Write run_metadata.json
    metadata = get_environment_info(profile, chain_client)
    meta_path = res_dir / "run_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"Recorded run metadata: {meta_path}")

    # Prepare shared data directory
    data_dir = res_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    base_csv = data_dir / "base_synthetic.csv"
    if not base_csv.exists():
        df_base = generate_synthetic_dataset(num_rows=profile.dataset_sizes[0]["rows"], random_state=profile.base_seed)
        df_base.to_csv(base_csv, index=False)

    start_total = time.perf_counter()

    # 1. Run E1 & E1b
    print("\n[1/5] Running E1 Detection & E1b Localization...")
    e1_csv, e1b_csv = run_e1_experiments(profile, base_csv, res_dir, chain_client=chain_client)
    print(f"  -> Generated {e1_csv.name} and {e1b_csv.name}")

    # 2. Run E2
    print("\n[2/5] Running E2 Latency Decomposition...")
    e2_csv = run_e2_experiments(profile, data_dir, res_dir, chain_client=chain_client)
    print(f"  -> Generated {e2_csv.name}")

    # 3. Run E3
    print("\n[3/5] Running E3 Storage & Gas Overhead...")
    e3_csv = run_e3_experiments(profile, data_dir, res_dir, chain_client=chain_client)
    print(f"  -> Generated {e3_csv.name}")

    # 4. Run E4
    print("\n[4/5] Running E4 Chunk-Size Sensitivity...")
    e4_csv = run_e4_experiments(profile, data_dir, res_dir, chain_client=chain_client)
    print(f"  -> Generated {e4_csv.name}")

    # 5. Run E5
    print("\n[5/5] Running E5 Lineage, Contamination & Reproducibility...")
    e5_csv, e5_qual = run_e5_experiments(profile, base_csv, res_dir, chain_client=chain_client)
    print(f"  -> Generated {e5_csv.name} and {e5_qual.name}")

    elapsed = time.perf_counter() - start_total
    print(f"\n=== Benchmark Complete in {elapsed:.2f}s ===")
    print(f"All CSV outputs written to: {res_dir}")
    return res_dir


if __name__ == "__main__":
    main()
