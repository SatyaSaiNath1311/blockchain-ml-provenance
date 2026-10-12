"""Experiment E1 & E1b: Tampering Detection and Merkle Localization.

Evaluates Approaches A, B, and C across 14 attack conditions and N clean trials (False Positive Rate).
Evaluates chunk-level localization precision and recall for Approach C.
Writes raw CSV results: e1_detection.csv and e1b_localization.csv.
"""

import csv
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

import pandas as pd

from backend.chain import ChainClient
from backend.fingerprint import find_modified_chunks, split_csv_into_chunks
from backend.verify import verify_version
from experiments.eval.approaches import ApproachA, ApproachB, ApproachC
from experiments.eval.config import EvalProfile
from experiments.tamper import (
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


def _get_target_file(approach_obj: Any, v_id: str) -> Path:
    """Helper to locate target CSV file for any approach."""
    if isinstance(approach_obj, ApproachA):
        v_dir = approach_obj.versions_dir / v_id
        with open(v_dir / "manifest.json", "r", encoding="utf-8") as f:
            manifest = json.load(f)
        return v_dir / manifest["filename"]
    elif isinstance(approach_obj, ApproachB):
        ptr_file = approach_obj.pointers_dir / f"{v_id}.dvc"
        with open(ptr_file, "r", encoding="utf-8") as f:
            ptr = json.load(f)
        return approach_obj.data_dir / v_id / ptr["filename"]
    elif isinstance(approach_obj, ApproachC):
        meta_file = approach_obj.storage_dir / "metadata" / f"{v_id}.json"
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return approach_obj.storage_dir / "uploads" / meta["dataset_id"] / v_id / meta["filename"]
    raise TypeError(f"Unknown approach type: {type(approach_obj)}")


def run_e1_experiments(
    profile: EvalProfile,
    base_csv_path: Path | str,
    out_dir: Path | str,
    chain_client: ChainClient | None = None,
) -> tuple[Path, Path]:
    """Execute E1 detection and E1b localization experiments."""
    out_dir_p = Path(out_dir).resolve()
    out_dir_p.mkdir(parents=True, exist_ok=True)
    e1_csv_path = out_dir_p / "e1_detection.csv"
    e1b_csv_path = out_dir_p / "e1b_localization.csv"

    base_csv = Path(base_csv_path).resolve()

    # 1. Prepare E1 CSV writer
    e1_fields = [
        "approach",
        "condition",
        "attack",
        "fraction",
        "trial",
        "seed",
        "detected",
        "status",
        "failed_checks",
        "hashing_ms",
        "total_ms",
    ]
    e1_file = open(e1_csv_path, "w", newline="", encoding="utf-8")
    e1_writer = csv.DictWriter(e1_file, fieldnames=e1_fields)
    e1_writer.writeheader()

    # 2. Prepare E1b CSV writer
    e1b_fields = [
        "condition",
        "attack",
        "fraction",
        "trial",
        "seed",
        "precision",
        "recall",
        "exact_match",
        "first_chunk_matched",
        "chunks_flagged",
        "rows_changed",
    ]
    e1b_file = open(e1b_csv_path, "w", newline="", encoding="utf-8")
    e1b_writer = csv.DictWriter(e1b_file, fieldnames=e1b_fields)
    e1b_writer.writeheader()

    try:
        # Create master temp directories for baseline initializations
        master_work = Path(tempfile.mkdtemp(prefix="eval_e1_master_"))

        # Setup base instances
        app_a_master = ApproachA(master_work / "a")
        app_b_master = ApproachB(master_work / "b")
        app_c_master = ApproachC(master_work / "c", chain_client=chain_client)

        # Register v1 (raw), v2 (derived for rollback), v3 (cleaned)
        # v1:
        reg_a_v1 = app_a_master.register(base_csv, operation_type="ingest")
        reg_b_v1 = app_b_master.register(base_csv, operation_type="ingest")
        reg_c_v1 = app_c_master.register(base_csv, operation_type="ingest")

        # Create a modified version for v2 to allow rollback attack
        df_v1 = pd.read_csv(base_csv)
        v2_temp_file = master_work / "v2_derived.csv"
        df_v2 = df_v1.copy()
        if len(df_v2) > 10:
            df_v2 = df_v2.iloc[:-5]  # drop 5 rows
        df_v2.to_csv(v2_temp_file, index=False)

        reg_a_v2 = app_a_master.register(v2_temp_file, parent_version_id=reg_a_v1["version_id"], operation_type="clean")
        reg_b_v2 = app_b_master.register(v2_temp_file, parent_version_id=reg_b_v1["version_id"], operation_type="clean")
        reg_c_v2 = app_c_master.register(v2_temp_file, parent_version_id=reg_c_v1["version_id"], operation_type="clean")

        approaches = [
            ("A", app_a_master, reg_a_v1["version_id"], reg_a_v2["version_id"]),
            ("B", app_b_master, reg_b_v1["version_id"], reg_b_v2["version_id"]),
            ("C", app_c_master, reg_c_v1["version_id"], reg_c_v2["version_id"]),
        ]

        trials_n = profile.trials_per_condition
        fractions = profile.attack_fractions

        # Attack definition generator
        def get_attacks(trial: int, frac: float, seed: int):
            return [
                ("modify_cells", lambda p: modify_cells(p, fraction=frac, seed=seed), frac),
                ("delete_rows", lambda p: delete_rows(p, fraction=frac, seed=seed), frac),
                ("insert_rows", lambda p: insert_rows(p, fraction=frac, seed=seed), frac),
                ("flip_labels", lambda p: flip_labels(p, fraction=frac, seed=seed), frac),
            ]

        # -------------------------------------------------------------
        # Part A: Multi-intensity file tampering attacks
        # -------------------------------------------------------------
        for frac in fractions:
            for trial in range(trials_n):
                seed = profile.base_seed + int(frac * 10000) + trial

                for app_code, master_app, v1_id, _ in approaches:
                    for attack_name, attack_fn, f_val in get_attacks(trial, frac, seed):
                        cond_name = f"{attack_name}_{f_val}"
                        # Clone storage to fresh temp dir
                        trial_dir = Path(tempfile.mkdtemp(prefix=f"trial_{app_code}_{cond_name}_"))
                        try:
                            cloned_app = _clone_approach(app_code, master_app, trial_dir, chain_client)
                            target_csv = _get_target_file(cloned_app, v1_id)

                            # Apply attack
                            attack_res = attack_fn(target_csv)

                            # Verify
                            ver_res = cloned_app.verify(v1_id)

                            e1_writer.writerow({
                                "approach": app_code,
                                "condition": cond_name,
                                "attack": attack_name,
                                "fraction": f_val,
                                "trial": trial,
                                "seed": seed,
                                "detected": ver_res["detected"],
                                "status": ver_res["status"],
                                "failed_checks": _extract_failed_checks(ver_res),
                                "hashing_ms": round(ver_res["timings"]["hashing_ms"], 4),
                                "total_ms": round(ver_res["timings"]["total_ms"], 4),
                            })
                            e1_file.flush()

                            # E1b Localization for Approach C
                            if app_code == "C":
                                _evaluate_localization(
                                    cloned_app,
                                    v1_id,
                                    cond_name,
                                    attack_name,
                                    f_val,
                                    trial,
                                    seed,
                                    attack_res,
                                    target_csv,
                                    base_csv,
                                    e1b_writer,
                                    e1b_file,
                                )

                        finally:
                            shutil.rmtree(trial_dir, ignore_errors=True)

        # -------------------------------------------------------------
        # Part B: Structural & Advanced Attacks
        # -------------------------------------------------------------
        structural_attacks = [
            ("swap_columns", lambda p, s: swap_columns(p, seed=s)),
            ("replace_file", lambda p, s: replace_file(p, seed=s)),
            ("modify_preprocessing_output", lambda p, s: modify_preprocessing_output(p, fraction=0.01, seed=s)),
        ]

        for a_idx, (attack_name, attack_fn) in enumerate(structural_attacks):
            for trial in range(trials_n):
                seed = profile.base_seed + 5000 + a_idx * 100 + trial
                for app_code, master_app, v1_id, _ in approaches:
                    trial_dir = Path(tempfile.mkdtemp(prefix=f"trial_{app_code}_{attack_name}_"))
                    try:
                        cloned_app = _clone_approach(app_code, master_app, trial_dir, chain_client)
                        target_csv = _get_target_file(cloned_app, v1_id)
                        attack_fn(target_csv, seed)
                        ver_res = cloned_app.verify(v1_id)

                        e1_writer.writerow({
                            "approach": app_code,
                            "condition": attack_name,
                            "attack": attack_name,
                            "fraction": 0.0,
                            "trial": trial,
                            "seed": seed,
                            "detected": ver_res["detected"],
                            "status": ver_res["status"],
                            "failed_checks": _extract_failed_checks(ver_res),
                            "hashing_ms": round(ver_res["timings"]["hashing_ms"], 4),
                            "total_ms": round(ver_res["timings"]["total_ms"], 4),
                        })
                        e1_file.flush()
                    finally:
                        shutil.rmtree(trial_dir, ignore_errors=True)

        # Rollback Attack (v2 rolled back to v1)
        for trial in range(trials_n):
            seed = profile.base_seed + 6000 + trial
            for app_code, master_app, v1_id, v2_id in approaches:
                trial_dir = Path(tempfile.mkdtemp(prefix=f"trial_{app_code}_rollback_"))
                try:
                    cloned_app = _clone_approach(app_code, master_app, trial_dir, chain_client)
                    v1_file = _get_target_file(cloned_app, v1_id)
                    v2_file = _get_target_file(cloned_app, v2_id)
                    rollback_to_version(v2_file, v1_file)
                    ver_res = cloned_app.verify(v2_id)

                    e1_writer.writerow({
                        "approach": app_code,
                        "condition": "rollback_to_version",
                        "attack": "rollback_to_version",
                        "fraction": 0.0,
                        "trial": trial,
                        "seed": seed,
                        "detected": ver_res["detected"],
                        "status": ver_res["status"],
                        "failed_checks": _extract_failed_checks(ver_res),
                        "hashing_ms": round(ver_res["timings"]["hashing_ms"], 4),
                        "total_ms": round(ver_res["timings"]["total_ms"], 4),
                    })
                    e1_file.flush()
                finally:
                    shutil.rmtree(trial_dir, ignore_errors=True)

        # Forge Metadata Attack
        for trial in range(trials_n):
            seed = profile.base_seed + 7000 + trial
            for app_code, master_app, v1_id, _ in approaches:
                trial_dir = Path(tempfile.mkdtemp(prefix=f"trial_{app_code}_forgemeta_"))
                try:
                    cloned_app = _clone_approach(app_code, master_app, trial_dir, chain_client)
                    if app_code == "A":
                        meta_p = cloned_app.versions_dir / v1_id / "manifest.json"
                        with open(meta_p, "r") as f:
                            m = json.load(f)
                        m["parent_version_id"] = "forged-parent-id"
                        with open(meta_p, "w") as f:
                            json.dump(m, f)
                    elif app_code == "B":
                        ptr_p = cloned_app.pointers_dir / f"{v1_id}.dvc"
                        with open(ptr_p, "r") as f:
                            p = json.load(f)
                        p["parent_version_id"] = "forged-parent-id"
                        with open(ptr_p, "w") as f:
                            json.dump(p, f)
                    elif app_code == "C":
                        meta_p = cloned_app.storage_dir / "metadata" / f"{v1_id}.json"
                        forge_metadata(meta_p, field="parent_version_id", new_value="forged-parent-id")

                    ver_res = cloned_app.verify(v1_id)
                    e1_writer.writerow({
                        "approach": app_code,
                        "condition": "forge_metadata",
                        "attack": "forge_metadata",
                        "fraction": 0.0,
                        "trial": trial,
                        "seed": seed,
                        "detected": ver_res["detected"],
                        "status": ver_res["status"],
                        "failed_checks": _extract_failed_checks(ver_res),
                        "hashing_ms": round(ver_res["timings"]["hashing_ms"], 4),
                        "total_ms": round(ver_res["timings"]["total_ms"], 4),
                    })
                    e1_file.flush()
                finally:
                    shutil.rmtree(trial_dir, ignore_errors=True)

        # Smart Attacker (consistent forgery across file and local metadata)
        for trial in range(trials_n):
            seed = profile.base_seed + 8000 + trial
            for app_code, master_app, v1_id, _ in approaches:
                trial_dir = Path(tempfile.mkdtemp(prefix=f"trial_{app_code}_smart_"))
                try:
                    cloned_app = _clone_approach(app_code, master_app, trial_dir, chain_client)
                    cloned_app.apply_smart_attack(v1_id, fraction=0.01, seed=seed)
                    ver_res = cloned_app.verify(v1_id)

                    e1_writer.writerow({
                        "approach": app_code,
                        "condition": "smart_attacker",
                        "attack": "smart_attacker",
                        "fraction": 0.01,
                        "trial": trial,
                        "seed": seed,
                        "detected": ver_res["detected"],
                        "status": ver_res["status"],
                        "failed_checks": _extract_failed_checks(ver_res),
                        "hashing_ms": round(ver_res["timings"]["hashing_ms"], 4),
                        "total_ms": round(ver_res["timings"]["total_ms"], 4),
                    })
                    e1_file.flush()
                finally:
                    shutil.rmtree(trial_dir, ignore_errors=True)

        # -------------------------------------------------------------
        # Part C: False-Positive Rate (N = clean_trials_fpr)
        # -------------------------------------------------------------
        clean_trials = profile.clean_trials_fpr
        for trial in range(clean_trials):
            seed = profile.base_seed + 9000 + trial
            for app_code, master_app, v1_id, _ in approaches:
                # Run clean verify on master without modifying anything
                ver_res = master_app.verify(v1_id)
                e1_writer.writerow({
                    "approach": app_code,
                    "condition": "clean_no_tamper",
                    "attack": "none",
                    "fraction": 0.0,
                    "trial": trial,
                    "seed": seed,
                    "detected": ver_res["detected"],
                    "status": ver_res["status"],
                    "failed_checks": _extract_failed_checks(ver_res),
                    "hashing_ms": round(ver_res["timings"]["hashing_ms"], 4),
                    "total_ms": round(ver_res["timings"]["total_ms"], 4),
                })
                e1_file.flush()

    finally:
        e1_file.close()
        e1b_file.close()
        shutil.rmtree(master_work, ignore_errors=True)

    return e1_csv_path, e1b_csv_path


def _clone_approach(
    app_code: str,
    master_app: Any,
    dest_dir: Path,
    chain_client: ChainClient | None,
) -> Any:
    """Clone master approach directory into dest_dir for isolated trial."""
    if app_code == "A":
        shutil.copytree(master_app.base_dir, dest_dir / "a")
        return ApproachA(dest_dir / "a")
    elif app_code == "B":
        shutil.copytree(master_app.base_dir, dest_dir / "b")
        return ApproachB(dest_dir / "b")
    elif app_code == "C":
        shutil.copytree(master_app.storage_dir, dest_dir / "c")
        return ApproachC(dest_dir / "c", chain_client=chain_client)
    raise ValueError(f"Unknown code: {app_code}")


def _extract_failed_checks(ver_res: dict[str, Any]) -> str:
    """Serialize failed verification checks for CSV reporting."""
    failed = []
    if not ver_res.get("file_hash_match", True):
        failed.append("file_hash")
    if not ver_res.get("merkle_root_match", True):
        failed.append("merkle_root")
    if not ver_res.get("metadata_digest_match", True):
        failed.append("metadata_digest")
    if not ver_res.get("pointer_clean", True):
        failed.append("pointer_uncommitted")
    if not ver_res.get("manifest_intact", True):
        failed.append("manifest_missing")
    return ";".join(failed) if failed else "none"


def _evaluate_localization(
    app_c: ApproachC,
    v_id: str,
    cond_name: str,
    attack_name: str,
    fraction: float,
    trial: int,
    seed: int,
    attack_res: dict[str, Any],
    tampered_csv_path: Path,
    original_csv_path: Path,
    writer: csv.DictWriter,
    file_handle: Any,
) -> None:
    """Evaluate Merkle tree localization precision and recall for Approach C."""
    # Read chunk_rows from tree metadata
    meta_path = app_c.storage_dir / "metadata" / f"{v_id}.json"
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    chunk_rows = meta.get("chunk_rows", 1000)

    # Compute actual modified chunks using find_modified_chunks
    orig_bytes = original_csv_path.read_bytes()
    tampered_bytes = tampered_csv_path.read_bytes()
    orig_chunks = split_csv_into_chunks(orig_bytes, chunk_rows=chunk_rows)
    tampered_chunks = split_csv_into_chunks(tampered_bytes, chunk_rows=chunk_rows)

    flagged_indices = set(find_modified_chunks(orig_chunks, tampered_chunks))

    if attack_name in ("modify_cells", "flip_labels"):
        rows_modified = attack_res.get("rows_modified") or attack_res.get("flipped_rows") or []
        # Chunk 0 has 1 header row + (chunk_rows - 1) data rows.
        # Chunk k has chunk_rows data rows.
        # Header row count is 1.
        # Data row i (0-indexed) maps to:
        gt_chunks = set()
        for r_idx in rows_modified:
            if r_idx < (chunk_rows - 1):
                gt_chunks.add(0)
            else:
                c_idx = 1 + (r_idx - (chunk_rows - 1)) // chunk_rows
                gt_chunks.add(c_idx)

        tp = len(flagged_indices.intersection(gt_chunks))
        fp = len(flagged_indices.difference(gt_chunks))
        fn = len(gt_chunks.difference(flagged_indices))

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        exact_match = (flagged_indices == gt_chunks)

        writer.writerow({
            "condition": cond_name,
            "attack": attack_name,
            "fraction": fraction,
            "trial": trial,
            "seed": seed,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "exact_match": exact_match,
            "first_chunk_matched": True,
            "chunks_flagged": len(flagged_indices),
            "rows_changed": len(rows_modified),
        })
        file_handle.flush()

    elif attack_name in ("insert_rows", "delete_rows"):
        rows_changed = attack_res.get("rows_inserted") or len(attack_res.get("rows_deleted", [])) or 1
        # For shift attacks, all chunks after insertion/deletion point shift
        # Check if first reported chunk matches ground truth first affected chunk
        gt_first_row = attack_res.get("insert_position") or (min(attack_res.get("rows_deleted", [0])))
        if gt_first_row < (chunk_rows - 1):
            gt_first_chunk = 0
        else:
            gt_first_chunk = 1 + (gt_first_row - (chunk_rows - 1)) // chunk_rows

        first_reported = min(flagged_indices) if flagged_indices else -1
        first_match = (first_reported == gt_first_chunk)

        writer.writerow({
            "condition": cond_name,
            "attack": attack_name,
            "fraction": fraction,
            "trial": trial,
            "seed": seed,
            "precision": 0.0,
            "recall": 1.0 if flagged_indices else 0.0,
            "exact_match": False,
            "first_chunk_matched": first_match,
            "chunks_flagged": len(flagged_indices),
            "rows_changed": rows_changed,
        })
        file_handle.flush()
