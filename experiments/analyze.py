"""Analysis and visualization generator for Phase 7 evaluation results.

Strictly reads ONLY raw CSV files and run_metadata.json from a results folder.
Produces publication-grade Markdown and CSV tables in <results_dir>/tables/
and high-resolution PNG and PDF figures in <results_dir>/figures/.
"""

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from experiments.eval.stats import summary_stats, t_interval, wilson_score_interval


def df_to_markdown(df: pd.DataFrame) -> str:
    """Format a pandas DataFrame as a clean Markdown table without external tabulate dependency."""
    if df.empty:
        return ""
    headers = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for _, row in df.iterrows():
        row_str = [str(x) for x in row.values]
        lines.append("| " + " | ".join(row_str) + " |")
    return "\n".join(lines) + "\n"


def analyze_results(results_dir: Path | str) -> dict[str, Any]:
    """Process raw CSV files and generate summary tables and plots."""
    r_dir = Path(results_dir).resolve()
    if not r_dir.exists() or not r_dir.is_dir():
        raise FileNotFoundError(f"Results directory not found: {r_dir}")

    tables_dir = r_dir / "tables"
    figures_dir = r_dir / "figures"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    # Read run_metadata.json
    meta_path = r_dir / "run_metadata.json"
    git_commit = "unknown"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
            git_commit = meta.get("git_commit", "unknown")[:7]

    footer_text = f"Commit: {git_commit} | Lightweight Blockchain Framework Evaluation"

    # =========================================================================
    # 1. E1 Detection & False Positive Rates
    # =========================================================================
    e1_path = r_dir / "e1_detection.csv"
    if e1_path.exists():
        df_e1 = pd.read_csv(e1_path)

        # Separate clean trials from attacks
        df_clean = df_e1[df_e1["condition"] == "clean_no_tamper"]
        df_attacks = df_e1[df_e1["condition"] != "clean_no_tamper"]

        # --- False Positive Rate Table ---
        fpr_rows = []
        for app in sorted(df_clean["approach"].unique()):
            sub = df_clean[df_clean["approach"] == app]
            total_clean = len(sub)
            false_positives = int(sub["detected"].sum())
            p_hat, ci_l, ci_u = wilson_score_interval(false_positives, total_clean)
            fpr_rows.append({
                "approach": app,
                "clean_trials": total_clean,
                "false_positives": false_positives,
                "fpr": round(p_hat, 4),
                "fpr_ci_lower_95": round(ci_l, 4),
                "fpr_ci_upper_95": round(ci_u, 4),
            })
        df_fpr = pd.DataFrame(fpr_rows)
        df_fpr.to_csv(tables_dir / "false_positive_rate.csv", index=False)
        (tables_dir / "false_positive_rate.md").write_text(df_to_markdown(df_fpr), encoding="utf-8")

        # --- Detection Rate Table by Attack & Approach ---
        det_rows = []
        grouped = df_attacks.groupby(["condition", "attack", "approach"])
        for (cond, atk, app), group in grouped:
            trials = len(group)
            detected = int(group["detected"].sum())
            p_hat, ci_l, ci_u = wilson_score_interval(detected, trials)
            det_rows.append({
                "condition": cond,
                "attack": atk,
                "approach": app,
                "trials": trials,
                "detected": detected,
                "detection_rate": round(p_hat, 4),
                "ci_lower_95": round(ci_l, 4),
                "ci_upper_95": round(ci_u, 4),
            })
        df_det = pd.DataFrame(det_rows)
        df_det.to_csv(tables_dir / "detection_rates.csv", index=False)
        (tables_dir / "detection_rates.md").write_text(df_to_markdown(df_det), encoding="utf-8")

        # --- Figure 1: Detection Rate by Attack Condition ---
        fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
        # Select representative attacks
        rep_attacks = ["modify_cells_0.01", "insert_rows_0.01", "delete_rows_0.01", "swap_columns", "rollback_to_version", "smart_attacker"]
        plot_df = df_det[df_det["condition"].isin(rep_attacks)].copy()
        if not plot_df.empty:
            pivot_det = plot_df.pivot(index="condition", columns="approach", values="detection_rate").fillna(0.0)
            pivot_det.plot(kind="bar", ax=ax, width=0.8, colormap="viridis")
            ax.set_ylabel("Detection Rate")
            ax.set_xlabel("Attack Scenario")
            ax.set_ylim(-0.05, 1.1)
            ax.set_title("Detection Rate Comparison Across Approaches (Wilson 95% CI)")
            ax.grid(axis="y", linestyle="--", alpha=0.5)
            plt.xticks(rotation=25, ha="right")
            plt.figtext(0.98, 0.01, footer_text, ha="right", fontsize=8, color="gray")
            plt.tight_layout()
            plt.savefig(figures_dir / "fig1_detection_rates.png")
            plt.savefig(figures_dir / "fig1_detection_rates.pdf")
            plt.close()

    # =========================================================================
    # 2. E1b Merkle Tree Localization
    # =========================================================================
    e1b_path = r_dir / "e1b_localization.csv"
    if e1b_path.exists():
        df_e1b = pd.read_csv(e1b_path)
        loc_rows = []
        for (cond, atk), group in df_e1b.groupby(["condition", "attack"]):
            n = len(group)
            prec_m, prec_l, prec_u = t_interval(group["precision"])
            rec_m, rec_l, rec_u = t_interval(group["recall"])
            exact_pct = group["exact_match"].mean() * 100.0
            first_match_pct = group["first_chunk_matched"].mean() * 100.0
            loc_rows.append({
                "condition": cond,
                "attack": atk,
                "trials": n,
                "precision_mean": round(prec_m, 4),
                "recall_mean": round(rec_m, 4),
                "exact_match_pct": round(exact_pct, 2),
                "first_chunk_match_pct": round(first_match_pct, 2),
            })
        df_loc = pd.DataFrame(loc_rows)
        df_loc.to_csv(tables_dir / "localization_accuracy.csv", index=False)
        (tables_dir / "localization_accuracy.md").write_text(df_to_markdown(df_loc), encoding="utf-8")

        # --- Figure 5: Localization Recall vs Modification Fraction ---
        inplace_df = df_e1b[df_e1b["attack"].isin(["modify_cells", "flip_labels"])].copy()
        if not inplace_df.empty:
            fig, ax = plt.subplots(figsize=(7, 4.5), dpi=300)
            for atk, grp in inplace_df.groupby("attack"):
                summary_by_frac = grp.groupby("fraction")["recall"].agg(["mean", "std"]).reset_index()
                ax.errorbar(
                    summary_by_frac["fraction"],
                    summary_by_frac["mean"],
                    yerr=summary_by_frac["std"].fillna(0),
                    marker="o",
                    label=atk,
                    capsize=4,
                )
            ax.set_xscale("log")
            ax.set_xlabel("Modification Fraction (log scale)")
            ax.set_ylabel("Chunk Localization Recall")
            ax.set_ylim(-0.05, 1.1)
            ax.set_title("Merkle Tree Localization Recall vs Modification Intensity")
            ax.grid(True, linestyle="--", alpha=0.5)
            ax.legend()
            plt.figtext(0.98, 0.01, footer_text, ha="right", fontsize=8, color="gray")
            plt.tight_layout()
            plt.savefig(figures_dir / "fig5_localization_recall_vs_fraction.png")
            plt.savefig(figures_dir / "fig5_localization_recall_vs_fraction.pdf")
            plt.close()

    # =========================================================================
    # 3. E2 Timing Decomposition
    # =========================================================================
    e2_path = r_dir / "e2_timing.csv"
    if e2_path.exists():
        df_e2 = pd.read_csv(e2_path)
        t_rows = []
        for (app, sz, op), group in df_e2.groupby(["approach", "size_label", "operation"]):
            stats_tot = summary_stats(group["total_ms"])
            stats_hash = summary_stats(group["hashing_ms"])
            stats_merkle = summary_stats(group["merkle_ms"])
            stats_tx = summary_stats(group["tx_latency_ms"])
            chain_read = group["chain_read_ms"].fillna(0.0)
            other = (group["total_ms"] - group["hashing_ms"].fillna(0.0)
                     - group["merkle_ms"].fillna(0.0) - chain_read
                     - group["tx_latency_ms"].fillna(0.0))
            t_rows.append({
                "approach": app,
                "size_label": sz,
                "operation": op,
                "n_trials": stats_tot["n"],
                "total_ms_mean": round(stats_tot["mean"], 3),
                "total_ms_std": round(stats_tot["std"], 3),
                "total_ms_median": round(stats_tot["median"], 3),
                "total_ci_lower_95": round(stats_tot["ci_lower"], 3),
                "total_ci_upper_95": round(stats_tot["ci_upper"], 3),
                "hashing_ms_mean": round(stats_hash["mean"], 3),
                "merkle_ms_mean": round(stats_merkle["mean"], 3),
                "tx_latency_ms_mean": round(stats_tx["mean"], 3),
                "chain_read_ms_mean": round(float(chain_read.mean()), 3),
                "other_ms_mean": round(float(other.mean()), 3),
                "other_ms_median": round(float(other.median()), 3),
            })
        df_timing = pd.DataFrame(t_rows)
        df_timing.to_csv(tables_dir / "timing_breakdown.csv", index=False)
        (tables_dir / "timing_breakdown.md").write_text(df_to_markdown(df_timing), encoding="utf-8")

        # --- Figure 2: Verification Time vs Dataset Size (Log-Log Scale) ---
        ver_df = df_e2[df_e2["operation"] == "verify"].copy()
        if not ver_df.empty:
            fig, ax = plt.subplots(figsize=(7, 4.5), dpi=300)
            for app, grp in ver_df.groupby("approach"):
                sz_summary = grp.groupby(["size_label", "actual_bytes"])["total_ms"].agg(["mean", "std"]).reset_index()
                sz_summary = sz_summary.sort_values("actual_bytes")
                ax.errorbar(
                    sz_summary["actual_bytes"] / 1024,
                    sz_summary["mean"],
                    yerr=sz_summary["std"].fillna(0),
                    marker="s",
                    label=f"Approach {app}",
                    capsize=4,
                )
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_xlabel("Dataset Size (KB, log scale)")
            ax.set_ylabel("Verification Time (ms, log scale)")
            ax.set_title("Verification Latency vs Dataset Size (Log-Log)")
            ax.grid(True, which="both", linestyle="--", alpha=0.5)
            ax.legend()
            plt.figtext(0.98, 0.01, footer_text, ha="right", fontsize=8, color="gray")
            plt.tight_layout()
            plt.savefig(figures_dir / "fig2_verification_time_vs_size.png")
            plt.savefig(figures_dir / "fig2_verification_time_vs_size.pdf")
            plt.close()

    # =========================================================================
    # 4. E3 Storage & Gas Footprint
    # =========================================================================
    e3_path = r_dir / "e3_storage.csv"
    if e3_path.exists():
        df_e3 = pd.read_csv(e3_path)
        df_e3.to_csv(tables_dir / "storage_footprint.csv", index=False)
        df_e3_md = df_e3.copy().astype(object)
        _mask = df_e3_md["operation"] == "record_training_run"
        df_e3_md.loc[_mask, ["off_chain_metadata_bytes", "overhead_percent"]] = "n/a"
        df_e3_md = df_e3_md.where(df_e3_md.notna(), "")
        (tables_dir / "storage_footprint.md").write_text(df_to_markdown(df_e3_md), encoding="utf-8")

        # Gas Table for Approach C (measured gasUsed is primary, slot-derived is cross-check)
        df_c_gas = df_e3[df_e3["approach"] == "C"][[
            "operation",
            "size_label",
            "measured_gas_used",
            "slot_derived_gas_estimate",
            "on_chain_calldata_bytes",
            "on_chain_storage_slots",
            "tx_latency_ms",
        ]].drop_duplicates()
        df_c_gas.to_csv(tables_dir / "gas_and_slots.csv", index=False)
        (tables_dir / "gas_and_slots.md").write_text(df_to_markdown(df_c_gas), encoding="utf-8")

        # --- Figure 3: Storage Overhead % vs Dataset Size ---
        root_reg = df_e3[df_e3["operation"] == "register_root"].copy()
        if not root_reg.empty:
            fig, ax = plt.subplots(figsize=(7, 4.5), dpi=300)
            for app, grp in root_reg.groupby("approach"):
                grp_s = grp.sort_values("raw_dataset_bytes")
                ax.plot(
                    grp_s["raw_dataset_bytes"] / 1024,
                    grp_s["overhead_percent"],
                    marker="o",
                    label=f"Approach {app}",
                )
            ax.set_xscale("log")
            ax.set_xlabel("Dataset Size (KB, log scale)")
            ax.set_ylabel("Storage Overhead (%)")
            ax.set_title("Off-Chain Storage Overhead vs Dataset Size")
            ax.grid(True, linestyle="--", alpha=0.5)
            ax.legend()
            plt.figtext(0.98, 0.01, footer_text, ha="right", fontsize=8, color="gray")
            plt.tight_layout()
            plt.savefig(figures_dir / "fig3_storage_overhead_pct.png")
            plt.savefig(figures_dir / "fig3_storage_overhead_pct.pdf")
            plt.close()

        # --- Figure 4: Gas Consumption by Operation (Approach C) ---
        if not df_c_gas.empty:
            fig, ax = plt.subplots(figsize=(7, 4.5), dpi=300)
            unique_ops = df_c_gas.drop_duplicates(subset=["operation"])
            bars = ax.bar(unique_ops["operation"], unique_ops["measured_gas_used"], color="#3b82f6", width=0.5)
            ax.set_ylabel("Measured Gas Used")
            ax.set_title("Gas Consumption per On-Chain Operation (Approach C)")
            ax.grid(axis="y", linestyle="--", alpha=0.5)
            for b in bars:
                h = b.get_height()
                ax.annotate(f"{int(h):,}", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 3), textcoords="offset points", ha="center", va="bottom", fontsize=8)
            plt.figtext(0.98, 0.01, footer_text, ha="right", fontsize=8, color="gray")
            plt.tight_layout()
            plt.savefig(figures_dir / "fig4_gas_per_operation.png")
            plt.savefig(figures_dir / "fig4_gas_per_operation.pdf")
            plt.close()

    # =========================================================================
    # 5. E4 Chunk-Size Sensitivity
    # =========================================================================
    e4_path = r_dir / "e4_chunksize.csv"
    if e4_path.exists():
        df_e4 = pd.read_csv(e4_path)
        e4_rows = []
        for c_rows, group in df_e4.groupby("chunk_rows"):
            stats_v = summary_stats(group["verification_ms"])
            e4_rows.append({
                "chunk_rows": c_rows,
                "num_chunks": group["num_chunks"].iloc[0],
                "tree_size_bytes": group["tree_size_bytes"].iloc[0],
                "verification_ms_mean": round(stats_v["mean"], 3),
                "verification_ms_std": round(stats_v["std"], 3),
                "granularity_rows_per_chunk": c_rows,
            })
        df_e4_sum = pd.DataFrame(e4_rows)
        df_e4_sum.to_csv(tables_dir / "chunk_size_sensitivity.csv", index=False)
        (tables_dir / "chunk_size_sensitivity.md").write_text(df_to_markdown(df_e4_sum), encoding="utf-8")

        # --- Figure 6: Chunk-Size Trade-off ---
        fig, ax1 = plt.subplots(figsize=(7, 4.5), dpi=300)
        ax2 = ax1.twinx()

        color1 = "#2563eb"
        color2 = "#dc2626"

        ax1.plot(df_e4_sum["chunk_rows"], df_e4_sum["verification_ms_mean"], color=color1, marker="o", label="Verification Latency (ms)")
        ax2.plot(df_e4_sum["chunk_rows"], df_e4_sum["tree_size_bytes"] / 1024, color=color2, marker="^", linestyle="--", label="Tree Size (KB)")

        ax1.set_xlabel("Chunk Size (Rows)")
        ax1.set_ylabel("Verification Latency (ms)", color=color1)
        ax2.set_ylabel("Tree File Size (KB)", color=color2)
        ax1.set_title("Chunk Size Trade-Off: Verification Latency vs Tree Storage")
        ax1.grid(True, linestyle="--", alpha=0.5)

        plt.figtext(0.98, 0.01, footer_text, ha="right", fontsize=8, color="gray")
        plt.tight_layout()
        plt.savefig(figures_dir / "fig6_chunk_size_tradeoff.png")
        plt.savefig(figures_dir / "fig6_chunk_size_tradeoff.pdf")
        plt.close()

    # =========================================================================
    # 6. E5 Lineage & Silent Contamination
    # =========================================================================
    e5_path = r_dir / "e5_lineage.csv"
    if e5_path.exists():
        df_e5 = pd.read_csv(e5_path)
        df_e5.to_csv(tables_dir / "lineage_and_contamination.csv", index=False)
        _keys = ["approach", "experiment_type", "scenario"]
        df_e5_agg = df_e5.groupby(_keys + ["detection_status"]).size().reset_index(name="trials")
        _tot = df_e5.groupby(_keys).size().reset_index(name="total_trials")
        df_e5_agg = df_e5_agg.merge(_tot, on=_keys)
        df_e5_agg.to_csv(tables_dir / "lineage_summary.csv", index=False)
        (tables_dir / "lineage_and_contamination.md").write_text(df_to_markdown(df_e5_agg), encoding="utf-8")

    # Qualitative Table
    e5_q_path = r_dir / "e5_qualitative.csv"
    if e5_q_path.exists():
        df_qual = pd.read_csv(e5_q_path)
        df_qual = df_qual.replace({
            "Ethereum Smart Contract (immutable append-only)":
                "Append-only smart contract; immutability holds on a public or permissioned chain (emulated here by a local Hardhat node that is not persistent across restarts)",
            "Decentralized consensus (no trusted local file)":
                "Consensus-backed record on a public or permissioned chain (no trusted local file; emulated here by a local node)",
        })
        df_qual.to_csv(tables_dir / "qualitative_comparison.csv", index=False)
        (tables_dir / "qualitative_comparison.md").write_text(df_to_markdown(df_qual), encoding="utf-8")

    print(f"Generated tables in: {tables_dir}")
    print(f"Generated figures in: {figures_dir}")
    return {"tables_dir": str(tables_dir), "figures_dir": str(figures_dir)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze evaluation benchmark CSVs.")
    parser.add_argument("results_dir", type=str, help="Path to results directory containing CSVs")
    args = parser.parse_args()
    analyze_results(args.results_dir)
