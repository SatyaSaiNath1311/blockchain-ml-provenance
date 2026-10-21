"""Experiment E3: Storage Overhead and Gas Consumption.

Measures off-chain storage bytes (and % overhead) and on-chain blockchain footprint
(calldata bytes, storage slots, measured gasUsed from receipts, and slot-derived estimate).
Writes raw CSV results: e3_storage.csv.
"""

import csv
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

import pandas as pd

from backend.chain import ChainClient
from backend.ml_pipeline import train_on_version
from experiments.eval.approaches import ApproachA, ApproachB, ApproachC
from experiments.eval.config import EvalProfile
from experiments.make_synthetic_csv import generate_synthetic_dataset


def run_e3_experiments(
    profile: EvalProfile,
    data_dir: Path | str,
    out_dir: Path | str,
    chain_client: ChainClient | None = None,
) -> Path:
    """Execute E3 storage and gas benchmarks across dataset sizes."""
    data_dir_p = Path(data_dir).resolve()
    data_dir_p.mkdir(parents=True, exist_ok=True)
    out_dir_p = Path(out_dir).resolve()
    out_dir_p.mkdir(parents=True, exist_ok=True)
    e3_csv_path = out_dir_p / "e3_storage.csv"

    fields = [
        "approach",
        "size_label",
        "raw_dataset_bytes",
        "off_chain_metadata_bytes",
        "overhead_percent",
        "on_chain_calldata_bytes",
        "on_chain_storage_slots",
        "measured_gas_used",
        "slot_derived_gas_estimate",
        "tx_latency_ms",
        "gate_time_ms",
        "operation",
    ]
    e3_file = open(e3_csv_path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(e3_file, fieldnames=fields)
    writer.writeheader()

    try:
        # Load or generate dataset sizes
        datasets = []
        for s_cfg in profile.dataset_sizes:
            label = s_cfg["label"]
            target_file = data_dir_p / f"synth_{label}.csv"
            if not target_file.exists():
                df = generate_synthetic_dataset(num_rows=s_cfg["rows"], random_state=profile.base_seed)
                df.to_csv(target_file, index=False)
            actual_size = target_file.stat().st_size
            datasets.append((label, target_file, actual_size))

        for label, dataset_path, raw_bytes in datasets:
            work_dir = Path(tempfile.mkdtemp(prefix=f"eval_e3_{label}_"))
            try:
                app_a = ApproachA(work_dir / "a")
                app_b = ApproachB(work_dir / "b")
                app_c = ApproachC(work_dir / "c", chain_client=chain_client)

                # Approach A
                reg_a = app_a.register(dataset_path)
                foot_a = app_a.storage_footprint(reg_a["version_id"])
                pct_a = (foot_a["total_off_chain_bytes"] / raw_bytes * 100.0) if raw_bytes > 0 else 0.0
                writer.writerow({
                    "approach": "A",
                    "size_label": label,
                    "raw_dataset_bytes": raw_bytes,
                    "off_chain_metadata_bytes": foot_a["total_off_chain_bytes"],
                    "overhead_percent": round(pct_a, 4),
                    "on_chain_calldata_bytes": 0,
                    "on_chain_storage_slots": 0,
                    "slot_derived_gas_estimate": 0,
                    "measured_gas_used": 0,
                    "tx_latency_ms": round(reg_a["timings"]["tx_latency_ms"], 4),
                    "operation": "register_root",
                })

                # Approach B
                reg_b = app_b.register(dataset_path)
                foot_b = app_b.storage_footprint(reg_b["version_id"])
                pct_b = (foot_b["total_off_chain_bytes"] / raw_bytes * 100.0) if raw_bytes > 0 else 0.0
                writer.writerow({
                    "approach": "B",
                    "size_label": label,
                    "raw_dataset_bytes": raw_bytes,
                    "off_chain_metadata_bytes": foot_b["total_off_chain_bytes"],
                    "overhead_percent": round(pct_b, 4),
                    "on_chain_calldata_bytes": 0,
                    "on_chain_storage_slots": 0,
                    "slot_derived_gas_estimate": 0,
                    "measured_gas_used": 0,
                    "tx_latency_ms": round(reg_b["timings"]["tx_latency_ms"], 4),
                    "operation": "register_root",
                })

                # slot_derived_gas_estimate counts storage writes only
                # (21000 base + 22100 per new zero->nonzero slot + 5000 per nonzero->nonzero update).
                # It is an approximate storage-write estimate: slots read earlier in the transaction
                # are warm and cost 20000 instead of 22100, and calldata, events and reads add
                # overhead. measured_gas_used is the headline figure.

                # Approach C: Root Version
                reg_c_root = app_c.register(dataset_path, operation_type="ingest")
                foot_c_root = app_c.storage_footprint(reg_c_root["version_id"])
                pct_c = (foot_c_root["total_off_chain_bytes"] / raw_bytes * 100.0) if raw_bytes > 0 else 0.0
                # 11 locations written (8 struct incl. zero-valued parent slot, exists flag, array length,
                # array element); 10 are new nonzero writes.
                slots_root = 11
                slot_est_root = 21000 + 10 * 22100  # 10 new nonzero slots; = 242000
                writer.writerow({
                    "approach": "C",
                    "size_label": label,
                    "raw_dataset_bytes": raw_bytes,
                    "off_chain_metadata_bytes": foot_c_root["total_off_chain_bytes"],
                    "overhead_percent": round(pct_c, 4),
                    "on_chain_calldata_bytes": foot_c_root["on_chain_calldata_bytes"],
                    "on_chain_storage_slots": slots_root,
                    "slot_derived_gas_estimate": slot_est_root,
                    "measured_gas_used": foot_c_root["gas_used"],
                    "tx_latency_ms": round(reg_c_root["timings"]["tx_latency_ms"], 4),
                    "operation": "register_root",
                })

                # Approach C: Child Version (derived)
                reg_c_child = app_c.register(
                    dataset_path,
                    parent_version_id=reg_c_root["version_id"],
                    operation_type="clean",
                )
                foot_c_child = app_c.storage_footprint(reg_c_child["version_id"])
                # 10 new nonzero slots (8 struct, exists, array element) + array length update at 5000.
                slots_child = 11
                slot_est_child = 21000 + 10 * 22100 + 5000  # = 247000
                writer.writerow({
                    "approach": "C",
                    "size_label": label,
                    "raw_dataset_bytes": raw_bytes,
                    "off_chain_metadata_bytes": foot_c_child["total_off_chain_bytes"],
                    "overhead_percent": round(foot_c_child["total_off_chain_bytes"] / raw_bytes * 100.0, 4),
                    "on_chain_calldata_bytes": foot_c_child["on_chain_calldata_bytes"],
                    "on_chain_storage_slots": slots_child,
                    "slot_derived_gas_estimate": slot_est_child,
                    "measured_gas_used": foot_c_child["gas_used"],
                    "tx_latency_ms": round(reg_c_child["timings"]["tx_latency_ms"], 4),
                    "operation": "register_child",
                })

                # Approach C: Record Training Run
                train_res = train_on_version(
                    version_id=reg_c_root["version_id"],
                    storage_dir=app_c.storage_dir,
                    chain_client=app_c.client,
                )
                run_rcpt = train_res["receipt"]
                # TrainingRunRecord = 4 slots (runId, datasetVersionId, experimentDigest,
                # submitter+timestamp packed) + _runExists = 5.
                slots_run = 5
                slot_est_run = 21000 + slots_run * 22100  # 5 new nonzero slots; = 131500
                writer.writerow({
                    "approach": "C",
                    "size_label": label,
                    "raw_dataset_bytes": raw_bytes,
                    "off_chain_metadata_bytes": 0,
                    "overhead_percent": 0.0,
                    "on_chain_calldata_bytes": 4 + 3 * 32,  # 100 bytes
                    "on_chain_storage_slots": slots_run,
                    "slot_derived_gas_estimate": slot_est_run,
                    "measured_gas_used": run_rcpt["gas_used"],
                    "tx_latency_ms": round(train_res["timings_ms"]["tx_latency_ms"], 4),
                    "gate_time_ms": round(train_res["timings_ms"]["gate_time_ms"], 4),
                    "operation": "record_training_run",
                })
                e3_file.flush()

            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

    finally:
        e3_file.close()

    return e3_csv_path
