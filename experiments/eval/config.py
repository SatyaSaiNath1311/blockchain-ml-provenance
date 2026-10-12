"""Configuration and profile definitions for Phase 7 evaluation benchmarks."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvalProfile:
    name: str
    trials_per_condition: int
    clean_trials_fpr: int
    warmup_trials: int
    dataset_sizes: list[dict[str, Any]]
    e4_chunk_rows: list[int]
    e4_dataset_label: str
    attack_fractions: list[float]
    base_seed: int = 42

    def estimate_runtime_seconds(self) -> float:
        """Estimate total benchmark runtime in seconds based on trial counts and sizes."""
        # E1 detection: ~14 attack conditions * 3 approaches * trials * ~0.15s
        e1_time = 14 * 3 * self.trials_per_condition * 0.15 + (3 * self.clean_trials_fpr * 0.05)
        # E1b localization: ~4 in-place conditions * trials * ~0.15s
        e1b_time = 4 * self.trials_per_condition * 0.15
        # E2 timing: len(sizes) * 3 approaches * (warmup + trials) * ~0.3s
        e2_time = len(self.dataset_sizes) * 3 * (self.warmup_trials + self.trials_per_condition) * 0.4
        # E3 storage: len(sizes) * 3 approaches * 0.2s
        e3_time = len(self.dataset_sizes) * 3 * 0.2
        # E4 chunksize: len(e4_chunk_rows) * trials * 0.2s
        e4_time = len(self.e4_chunk_rows) * self.trials_per_condition * 0.2
        # E5 lineage: 3 approaches * 5 versions + attacks ~10s
        e5_time = 3 * 5 * 0.5 + 10.0

        return e1_time + e1b_time + e2_time + e3_time + e4_time + e5_time


QUICK_PROFILE = EvalProfile(
    name="quick",
    trials_per_condition=3,
    clean_trials_fpr=100,  # Amendment 2: N=100 clean verifications
    warmup_trials=1,
    dataset_sizes=[
        {"label": "50KB", "target_bytes": 50 * 1024, "rows": 850},
        {"label": "150KB", "target_bytes": 150 * 1024, "rows": 2550},
        {"label": "300KB", "target_bytes": 300 * 1024, "rows": 5100},
    ],
    # Amendment 1: scaled chunk sizes so every setting produces >= 10 chunks on 5100 rows
    e4_chunk_rows=[50, 150, 300],
    e4_dataset_label="300KB",
    attack_fractions=[0.001, 0.01, 0.1],
    base_seed=1337,
)

FULL_PROFILE = EvalProfile(
    name="full",
    trials_per_condition=30,
    clean_trials_fpr=100,  # Amendment 2: N=100 clean verifications
    warmup_trials=2,
    dataset_sizes=[
        {"label": "1MB", "target_bytes": 1 * 1024 * 1024, "rows": 17500},
        {"label": "10MB", "target_bytes": 10 * 1024 * 1024, "rows": 175000},
        {"label": "100MB", "target_bytes": 100 * 1024 * 1024, "rows": 1750000},
    ],
    # Full profile keeps {100, 1000, 10000} on 10MB
    e4_chunk_rows=[100, 1000, 10000],
    e4_dataset_label="10MB",
    attack_fractions=[0.001, 0.01, 0.1],
    base_seed=42,
)

PROFILES = {
    "quick": QUICK_PROFILE,
    "full": FULL_PROFILE,
}
