import argparse
from pathlib import Path
import numpy as np
import pandas as pd


def generate_synthetic_dataset(
    num_rows: int = 5000,
    random_state: int = 42,
    duplicate_fraction: float = 0.03,
    missing_rate: float = 0.0,
) -> pd.DataFrame:
    """Generate a reproducible synthetic ML classification DataFrame with exact duplicate rows."""
    rng = np.random.default_rng(random_state)

    num_duplicates = int(round(num_rows * duplicate_fraction))
    num_unique = num_rows - num_duplicates
    if num_unique <= 0:
        num_unique = num_rows
        num_duplicates = 0

    age = rng.integers(18, 76, size=num_unique)
    income = np.round(rng.uniform(20000.0, 150000.0, size=num_unique), 2)
    credit_score = rng.integers(350, 851, size=num_unique)
    loan_amount = np.round(rng.uniform(1000.0, 50000.0, size=num_unique), 2)

    education_choices = ["High School", "Bachelor", "Master", "PhD"]
    education = rng.choice(education_choices, size=num_unique, p=[0.3, 0.45, 0.2, 0.05])

    employment_choices = ["Employed", "Self-Employed", "Unemployed"]
    employment = rng.choice(employment_choices, size=num_unique, p=[0.75, 0.18, 0.07])

    home_choices = ["Rent", "Own", "Mortgage"]
    home_ownership = rng.choice(home_choices, size=num_unique, p=[0.4, 0.25, 0.35])

    # Deterministic label calculation with noise
    score = (
        (credit_score - 350) / 500.0 * 0.45
        + (income / 150000.0) * 0.35
        - (loan_amount / 50000.0) * 0.20
        + rng.normal(0, 0.08, size=num_unique)
    )
    approved = (score > 0.40).astype(int)

    base_df = pd.DataFrame({
        "id": np.arange(1, num_unique + 1),
        "age": age,
        "income": income,
        "credit_score": credit_score,
        "education": education,
        "employment": employment,
        "home_ownership": home_ownership,
        "loan_amount": loan_amount,
        "approved": approved,
    })

    if num_duplicates > 0:
        dup_indices = rng.choice(len(base_df), size=num_duplicates, replace=True)
        dup_df = base_df.iloc[dup_indices].copy()
        combined_df = pd.concat([base_df, dup_df], ignore_index=True)
        perm = rng.permutation(len(combined_df))
        df = combined_df.iloc[perm].reset_index(drop=True)
    else:
        df = base_df

    if missing_rate > 0.0:
        feature_cols = ["age", "income", "credit_score", "education", "employment", "home_ownership", "loan_amount"]
        df["age"] = df["age"].astype(float)
        df["credit_score"] = df["credit_score"].astype(float)
        for col in feature_cols:
            mask = rng.random(size=len(df)) < missing_rate
            df.loc[mask, col] = np.nan

    return df


def generate_synthetic_csv(
    output_path: Path,
    num_rows: int = 5000,
    seed: int = 42,
    duplicate_fraction: float = 0.03,
    missing_rate: float = 0.0,
) -> Path:
    """Generate a reproducible synthetic ML classification dataset with exact duplicate rows."""
    df = generate_synthetic_dataset(
        num_rows=num_rows,
        random_state=seed,
        duplicate_fraction=duplicate_fraction,
        missing_rate=missing_rate,
    )
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    num_duplicates = int(round(num_rows * duplicate_fraction))
    print(
        f"[Dataset Generator] Created {len(df)} rows ({num_duplicates} exact duplicates, "
        f"~{100 - duplicate_fraction * 100:.1f}% unique, missing_rate={missing_rate:.2f}) at: {output_path} "
        f"(size: {output_path.stat().st_size} bytes)"
    )
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic ML tabular CSV.")
    parser.add_argument("--rows", type=int, default=5000, help="Number of rows (default: 5000)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument(
        "--missing-rate",
        type=float,
        default=0.0,
        help="Fraction of feature cells to inject with NaN (default: 0.0)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="experiments/data/synthetic_ml_data.csv",
        help="Target output CSV path",
    )
    args = parser.parse_args()
    generate_synthetic_csv(
        output_path=Path(args.output).resolve(),
        num_rows=args.rows,
        seed=args.seed,
        missing_rate=args.missing_rate,
    )
