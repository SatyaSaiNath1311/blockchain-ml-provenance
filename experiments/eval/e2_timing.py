"""Experiment E2: Latency Decomposition and Timing Benchmarks.

Measures hashing, Merkle construction, blockchain read, transaction latency,
and end-to-end times across dataset sizes with warm-up trials discarded.
Writes raw CSV results: e2_timing.csv.
"""

import csv
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from backend.chain import ChainClient
from experiments.eval.approaches import ApproachA, ApproachB, ApproachC
from experiments.eval.config import EvalProfile
from experiments.make_synthetic_csv import generate_synthetic_dataset


def run_e2_experiments(
    profile: EvalProfile,
    data_dir: Path | str,
    out_dir: Path | str,
    chain_client: ChainClient | None = None,
) -> Path:
    """Execute E2 timing benchmarks across dataset sizes and approaches."""
    data_dir_p = Path(data_dir).resolve()
    data_dir_p.mkdir(parents=True, exist_ok=True)
    out_dir_p = Path(out_dir).resolve()
    out_dir_p.mkdir(parents=True, exist_ok=True)
    e2_csv_path = out_dir_p / "e2_timing.csv"

    fields = [
        "approach",
        "size_label",
        "actual_bytes",
        "operation",
        "trial",
        "seed",
        "hashing_ms",
        "merkle_ms",
        "chain_read_ms",
        "tx_latency_ms",
        "total_ms",
    ]
    e2_file = open(e2_csv_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(e2_file, fieldnames=fields)
    writer.writeheader()

    try:
        # Generate or locate datasets for each size in profile
        generated_datasets = []
        for s_cfg in profile.dataset_sizes:
            label = s_cfg["label"]
            target_file = data_dir_p / f"synth_{label}.csv"
            if not target_file.exists():
                df = generate_synthetic_dataset(num_rows=s_cfg["rows"], random_state=profile.base_seed)
                df.to_csv(target_file, index=False)
            actual_size = target_file.stat().st_size
            generated_datasets.append((label, target_file, actual_size))

        for label, dataset_path, actual_bytes in generated_datasets:
            # Setup isolated temp approach environments per size
            work_dir = Path(tempfile.mkdtemp(prefix=f"eval_e2_{label}_"))
            try:
                app_a = ApproachA(work_dir / "a")
                app_b = ApproachB(work_dir / "b")
                app_c = ApproachC(work_dir / "c", chain_client=chain_client)

                approaches = [
                    ("A", app_a),
                    ("B", app_b),
                    ("C", app_c),
                ]

                for app_code, app_inst in approaches:
                    # 1. Warm-up trials (discarded) to ensure OS file cache is warm
                    for w in range(profile.warmup_trials):
                        reg_res = app_inst.register(dataset_path)
                        app_inst.verify(reg_res["version_id"])

                    # 2. Measurement trials
                    for trial in range(profile.trials_per_condition):
                        seed = profile.base_seed + 1000 + trial

                        # --- Measure Registration ---
                        reg_res = app_inst.register(dataset_path)
                        r_timings = reg_res["timings"]
                        writer.writerow({
                            "approach": app_code,
                            "size_label": label,
                            "actual_bytes": actual_bytes,
                            "operation": "register",
                            "trial": trial,
                            "seed": seed,
                            "hashing_ms": round(r_timings.get("hashing_ms", 0.0), 4),
                            "merkle_ms": round(r_timings.get("merkle_ms", 0.0), 4),
                            "chain_read_ms": 0.0,
                            "tx_latency_ms": round(r_timings.get("tx_latency_ms", 0.0), 4),
                            "total_ms": round(r_timings.get("total_ms", 0.0), 4),
                        })
                        e2_file.flush()

                        # --- Measure Verification ---
                        v_id = reg_res["version_id"]
                        ver_res = app_inst.verify(v_id)
                        v_timings = ver_res["timings"]
                        writer.writerow({
                            "approach": app_code,
                            "size_label": label,
                            "actual_bytes": actual_bytes,
                            "operation": "verify",
                            "trial": trial,
                            "seed": seed,
                            "hashing_ms": round(v_timings.get("hashing_ms", 0.0), 4),
                            "merkle_ms": round(v_timings.get("merkle_ms", 0.0), 4),
                            "chain_read_ms": round(v_timings.get("chain_read_ms", 0.0), 4),
                            "tx_latency_ms": 0.0,
                            "total_ms": round(v_timings.get("total_ms", 0.0), 4),
                        })
                        e2_file.flush()

            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

    finally:
        e2_file.close()

    return e2_csv_path
