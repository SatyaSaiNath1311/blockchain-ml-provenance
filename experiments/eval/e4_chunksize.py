"""Experiment E4: Merkle Chunk-Size Sensitivity Analysis (Approach C only).

Evaluates the trade-off between chunk size, tree JSON storage overhead,
verification latency, and localization granularity.
Writes raw CSV results: e4_chunksize.csv.
"""

import csv
import json
from pathlib import Path
import shutil
import tempfile

from backend.chain import ChainClient
from experiments.eval.approaches import ApproachC
from experiments.eval.config import EvalProfile
from experiments.make_synthetic_csv import generate_synthetic_dataset


def run_e4_experiments(
    profile: EvalProfile,
    data_dir: Path | str,
    out_dir: Path | str,
    chain_client: ChainClient | None = None,
) -> Path:
    """Execute E4 chunk-size sensitivity benchmarks."""
    data_dir_p = Path(data_dir).resolve()
    data_dir_p.mkdir(parents=True, exist_ok=True)
    out_dir_p = Path(out_dir).resolve()
    out_dir_p.mkdir(parents=True, exist_ok=True)
    e4_csv_path = out_dir_p / "e4_chunksize.csv"

    fields = [
        "dataset_label",
        "raw_bytes",
        "chunk_rows",
        "trial",
        "seed",
        "num_chunks",
        "tree_size_bytes",
        "verification_ms",
        "localization_granularity_rows",
    ]
    e4_file = open(e4_csv_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(e4_file, fieldnames=fields)
    writer.writeheader()

    try:
        # Locate target dataset for E4
        target_size_cfg = next(
            (s for s in profile.dataset_sizes if s["label"] == profile.e4_dataset_label),
            profile.dataset_sizes[-1],
        )
        dataset_file = data_dir_p / f"synth_{target_size_cfg['label']}.csv"
        if not dataset_file.exists():
            df = generate_synthetic_dataset(num_rows=target_size_cfg["rows"], random_state=profile.base_seed)
            df.to_csv(dataset_file, index=False)
        raw_bytes = dataset_file.stat().st_size

        chunk_settings = profile.e4_chunk_rows

        for c_rows in chunk_settings:
            work_dir = Path(tempfile.mkdtemp(prefix=f"eval_e4_c{c_rows}_"))
            try:
                app_c = ApproachC(work_dir / "c", chain_client=chain_client)
                reg_res = app_c.register(dataset_file, chunk_rows=c_rows)
                v_id = reg_res["version_id"]

                # Read tree file size and chunk count
                tree_file = app_c.storage_dir / "trees" / f"{v_id}.json"
                tree_size_bytes = tree_file.stat().st_size if tree_file.exists() else 0
                with open(tree_file, "r", encoding="utf-8") as f:
                    tree_data = json.load(f)
                num_chunks = tree_data.get("num_chunks", 0)

                # Verification timing trials
                for trial in range(profile.trials_per_condition):
                    seed = profile.base_seed + 3000 + trial
                    ver_res = app_c.verify(v_id)
                    v_time = ver_res["timings"]["total_ms"]

                    writer.writerow({
                        "dataset_label": target_size_cfg["label"],
                        "raw_bytes": raw_bytes,
                        "chunk_rows": c_rows,
                        "trial": trial,
                        "seed": seed,
                        "num_chunks": num_chunks,
                        "tree_size_bytes": tree_size_bytes,
                        "verification_ms": round(v_time, 4),
                        "localization_granularity_rows": c_rows,
                    })
                    e4_file.flush()

            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

    finally:
        e4_file.close()

    return e4_csv_path
