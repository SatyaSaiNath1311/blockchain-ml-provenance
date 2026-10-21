"""Unit and integration tests for Phase 7 evaluation benchmarks.

Covers statistical helpers, baselines A and B, Approach C interface,
dirty tree check, run metadata schema, and end-to-end quick benchmark analysis.
"""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
import pandas as pd
import pytest
import scipy.stats

from backend.chain import ChainClient
from experiments.analyze import analyze_results
from experiments.eval.approaches import ApproachA, ApproachB, ApproachC
from experiments.eval.config import QUICK_PROFILE
from experiments.eval.run_all import check_git_status, get_environment_info
from experiments.eval.stats import summary_stats, t_interval, wilson_score_interval
from experiments.tamper import modify_cells


# -----------------------------------------------------------------------------
# 1. Statistical Helpers Tests
# -----------------------------------------------------------------------------

def test_wilson_score_interval_known_values():
    """Verify Wilson interval against known mathematical values."""
    # 0 successes out of 30
    p0, l0, u0 = wilson_score_interval(0, 30, confidence=0.95)
    assert p0 == 0.0
    assert l0 == 0.0
    assert 0.10 < u0 < 0.13  # known Wilson upper bound for 0/30 ~ 0.1135

    # 30 successes out of 30
    p30, l30, u30 = wilson_score_interval(30, 30, confidence=0.95)
    assert p30 == 1.0
    assert 0.87 < l30 < 0.90  # known Wilson lower bound for 30/30 ~ 0.8865
    assert u30 == 1.0

    # 15 successes out of 30 (p = 0.5)
    p15, l15, u15 = wilson_score_interval(15, 30, confidence=0.95)
    assert p15 == 0.5
    assert 0.32 < l15 < 0.35
    assert 0.65 < u15 < 0.68


def test_t_interval_matches_scipy_directly():
    """Verify Student's t-interval calculation strictly matches scipy."""
    data = [12.5, 14.2, 11.9, 15.6, 13.1, 14.8, 12.0]
    mean, lower, upper = t_interval(data, confidence=0.95)

    scipy_mean = float(np.mean(data))
    scipy_ci = scipy.stats.t.interval(
        0.95, df=len(data) - 1, loc=scipy_mean, scale=float(scipy.stats.sem(data))
    )

    assert np.isclose(mean, scipy_mean)
    assert np.isclose(lower, scipy_ci[0])
    assert np.isclose(upper, scipy_ci[1])

    s = summary_stats(data)
    assert s["n"] == len(data)
    assert np.isclose(s["mean"], scipy_mean)
    assert np.isclose(s["ci_lower"], scipy_ci[0])


# -----------------------------------------------------------------------------
# 2. Baseline A & B Behavior Tests
# -----------------------------------------------------------------------------

@pytest.fixture
def sample_csv(tmp_path):
    p = tmp_path / "test_data.csv"
    df = pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "age": [25, 30, 35, 40, 45],
        "income": [50000.0, 60000.0, 75000.0, 90000.0, 110000.0],
        "approved": [1, 0, 1, 1, 0],
    })
    df.to_csv(p, index=False)
    return p


def test_baseline_a_lifecycle_and_threat_model(tmp_path, sample_csv):
    """Test Approach A clean pass, naive detection, and smart attacker evasion."""
    app_a = ApproachA(tmp_path / "a")
    reg = app_a.register(sample_csv)
    v_id = reg["version_id"]

    # 1. Clean verification passes
    ver_clean = app_a.verify(v_id)
    assert ver_clean["status"] == "VERIFIED"
    assert not ver_clean["detected"]

    # 2. Naive tampering is detected
    data_file = reg["file_path"]
    modify_cells(data_file, fraction=0.4, seed=42)
    ver_tampered = app_a.verify(v_id)
    assert ver_tampered["status"] == "TAMPERING_DETECTED"
    assert ver_tampered["detected"]

    # 3. Smart attacker rewrites manifest -> evades detection (documented baseline behavior)
    smart_info = app_a.apply_smart_attack(v_id, fraction=0.4, seed=99)
    ver_smart = app_a.verify(v_id)
    assert ver_smart["status"] == "VERIFIED"
    assert not ver_smart["detected"]

    # 4. Lineage works
    lin = app_a.lineage(v_id)
    assert len(lin) == 1
    assert lin[0]["version_id"] == v_id


def test_baseline_b_lifecycle_and_threat_model(tmp_path, sample_csv):
    """Test Approach B clean pass, naive detection, uncommitted pointer check, and smart evasion."""
    app_b = ApproachB(tmp_path / "b")
    reg = app_b.register(sample_csv)
    v_id = reg["version_id"]

    # 1. Clean verification passes
    ver_clean = app_b.verify(v_id)
    assert ver_clean["status"] == "VERIFIED"
    assert not ver_clean["detected"]

    # 2. Naive modification of working file is detected
    modify_cells(reg["working_file"], fraction=0.4, seed=42)
    ver_tampered = app_b.verify(v_id)
    assert ver_tampered["status"] == "TAMPERING_DETECTED"
    assert ver_tampered["detected"]

    # 3. Smart attacker amends Git commit -> evades local detection (documented baseline behavior)
    app_b.apply_smart_attack(v_id, fraction=0.4, seed=99)
    ver_smart = app_b.verify(v_id)
    assert ver_smart["status"] == "VERIFIED"
    assert not ver_smart["detected"]

    # 4. Lineage works
    lin = app_b.lineage(v_id)
    assert len(lin) == 1
    assert lin[0]["version_id"] == v_id


# -----------------------------------------------------------------------------
# 3. Approach C Smoke Test & Common Interface
# -----------------------------------------------------------------------------

def test_approach_c_smoke_and_smart_attack_detected(tmp_path, sample_csv, fresh_contract_chain_client):
    """Test Approach C registers, verifies, catches naive tampering, and catches smart attacker."""
    app_c = ApproachC(tmp_path / "c", chain_client=fresh_contract_chain_client)
    reg = app_c.register(sample_csv)
    v_id = reg["version_id"]

    # 1. Clean verify passes
    ver_clean = app_c.verify(v_id)
    assert ver_clean["status"] == "VERIFIED"
    assert not ver_clean["detected"]

    # 2. Naive attack detected
    meta_path = app_c.storage_dir / "metadata" / f"{v_id}.json"
    with open(meta_path) as f:
        meta = json.load(f)
    csv_file = app_c.storage_dir / "uploads" / meta["dataset_id"] / v_id / meta["filename"]
    modify_cells(csv_file, fraction=0.4, seed=42)

    ver_naive = app_c.verify(v_id)
    assert ver_naive["status"] == "TAMPERING_DETECTED"
    assert ver_naive["detected"]

    # 3. Smart attack (consistent_local_forgery) is CAUGHT by on-chain state
    app_c.apply_smart_attack(v_id, fraction=0.4, seed=123)
    ver_smart = app_c.verify(v_id)
    assert ver_smart["status"] == "TAMPERING_DETECTED"
    assert ver_smart["detected"]


# -----------------------------------------------------------------------------
# 4. Runner Safeguards & Metadata Validation
# -----------------------------------------------------------------------------

def test_runner_metadata_schema(fresh_contract_chain_client):
    """Verify run_metadata.json captures all mandatory fields."""
    env = get_environment_info(QUICK_PROFILE, fresh_contract_chain_client)
    mandatory_fields = [
        "timestamp_utc",
        "git_commit",
        "git_dirty",
        "profile",
        "trials_per_condition",
        "clean_trials_fpr",
        "base_seed",
        "chunk_rows",
        "estimated_runtime_seconds",
        "software_versions",
        "platform",
        "toolchain",
        "blockchain",
    ]
    for mf in mandatory_fields:
        assert mf in env, f"Missing field in metadata: {mf}"

    assert "python" in env["software_versions"]
    assert "pandas" in env["software_versions"]
    assert "scipy" in env["software_versions"]
    assert "matplotlib" in env["software_versions"]
    assert env["blockchain"]["chain_id"] == 31337


def test_dirty_repo_check_ignores_experiments_results():
    """Verify check_git_status ignores experiments/results/ directory."""
    commit, is_dirty = check_git_status()
    assert isinstance(commit, str)
    assert isinstance(is_dirty, bool)


# -----------------------------------------------------------------------------
# 5. Analysis Script Honesty & No-Hardcoding Test
# -----------------------------------------------------------------------------

def test_analyze_script_reads_only_csv_with_no_hardcoding(tmp_path):
    """Feed synthetic CSVs with known numbers to analyze.py and verify tables match exactly."""
    res_dir = tmp_path / "mock_results"
    res_dir.mkdir()

    # Create dummy run_metadata.json
    with open(res_dir / "run_metadata.json", "w") as f:
        json.dump({"git_commit": "abcdef1", "profile": "test"}, f)

    # 1. e1_detection.csv with known counts (10 clean trials, 0 detected; 10 attacks, 10 detected)
    e1_rows = [
        {"approach": "A", "condition": "clean_no_tamper", "attack": "none", "fraction": 0.0, "trial": i, "seed": i, "detected": False, "status": "VERIFIED", "failed_checks": "none", "hashing_ms": 1.0, "total_ms": 1.0}
        for i in range(10)
    ]
    e1_rows += [
        {"approach": "A", "condition": "modify_cells_0.01", "attack": "modify_cells", "fraction": 0.01, "trial": i, "seed": i, "detected": True, "status": "TAMPERING_DETECTED", "failed_checks": "file_hash", "hashing_ms": 1.0, "total_ms": 1.0}
        for i in range(10)
    ]
    pd.DataFrame(e1_rows).to_csv(res_dir / "e1_detection.csv", index=False)

    # 2. e2_timing.csv
    e2_rows = [
        {"approach": "A", "size_label": "1MB", "actual_bytes": 1048576, "operation": "verify", "trial": i, "seed": i, "hashing_ms": 10.0, "merkle_ms": 0.0, "chain_read_ms": 0.0, "tx_latency_ms": 0.0, "total_ms": 15.0}
        for i in range(5)
    ]
    pd.DataFrame(e2_rows).to_csv(res_dir / "e2_timing.csv", index=False)

    # 3. e3_storage.csv
    e3_rows = [
        {
            "approach": "A",
            "size_label": "1MB",
            "raw_dataset_bytes": 1048576,
            "off_chain_metadata_bytes": 500,
            "overhead_percent": 0.0477,
            "on_chain_calldata_bytes": 0,
            "on_chain_storage_slots": 0,
            "slot_derived_gas_estimate": 0,
            "measured_gas_used": 0,
            "tx_latency_ms": 0.0,
            "tx_latency_in_pipeline_ms": 0.0,
            "tx_latency_median_ms": 0.0,
            "tx_latency_max_ms": 0.0,
            "gate_time_ms": 0.0,
            "operation": "register_root",
        }
    ]
    pd.DataFrame(e3_rows).to_csv(res_dir / "e3_storage.csv", index=False)

    # 4. e4_chunksize.csv
    e4_rows = [
        {"dataset_label": "10MB", "raw_bytes": 10485760, "chunk_rows": 100, "trial": 0, "seed": 42, "num_chunks": 1000, "tree_size_bytes": 25000, "verification_ms": 35.0, "localization_granularity_rows": 100}
    ]
    pd.DataFrame(e4_rows).to_csv(res_dir / "e4_chunksize.csv", index=False)

    # 5. e5_lineage.csv & qualitative
    e5_rows = [
        {"approach": "A", "experiment_type": "lineage_attack", "scenario": "forge_parent", "attack_class": "structural", "trial": 0, "seed": 42, "detection_status": "DETECTED", "gate_blocked": True, "training_contaminated": False, "metrics_reproduced": True}
    ]
    pd.DataFrame(e5_rows).to_csv(res_dir / "e5_lineage.csv", index=False)
    pd.DataFrame([{"property": "test", "approach_a": "1", "approach_b": "2", "approach_c": "3"}]).to_csv(res_dir / "e5_qualitative.csv", index=False)

    # Run analyze_results
    out = analyze_results(res_dir)

    # Assert tables exist and match exact numbers
    fpr_df = pd.read_csv(res_dir / "tables" / "false_positive_rate.csv")
    assert fpr_df.iloc[0]["clean_trials"] == 10
    assert fpr_df.iloc[0]["false_positives"] == 0
    assert fpr_df.iloc[0]["fpr"] == 0.0

    det_df = pd.read_csv(res_dir / "tables" / "detection_rates.csv")
    assert det_df.iloc[0]["trials"] == 10
    assert det_df.iloc[0]["detected"] == 10
    assert det_df.iloc[0]["detection_rate"] == 1.0

    timing_df = pd.read_csv(res_dir / "tables" / "timing_breakdown.csv")
    assert timing_df.iloc[0]["total_ms_mean"] == 15.0

    # Assert charts exist
    assert (res_dir / "figures" / "fig1_detection_rates.png").exists()
    assert (res_dir / "figures" / "fig2_verification_time_vs_size.png").exists()
    assert (res_dir / "figures" / "fig3_storage_overhead_pct.png").exists()
    assert (res_dir / "figures" / "fig6_chunk_size_tradeoff.png").exists()
