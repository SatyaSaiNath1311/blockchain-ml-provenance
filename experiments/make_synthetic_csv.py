import argparse
from pathlib import Path
import numpy as np
import pandas as pd

def generate_synthetic_csv(
    output_path: Path,
    num_rows: int = 5000,
    seed: int = 42,
) -> Path:
    """Generate a reproducible synthetic ML classification dataset."""
    rng = np.random.default_rng(seed)

    age = rng.integers(18, 76, size=num_rows)
    income = np.round(rng.uniform(20000.0, 150000.0, size=num_rows), 2)
    credit_score = rng.integers(350, 851, size=num_rows)
    loan_amount = np.round(rng.uniform(1000.0, 50000.0, size=num_rows), 2)

    education_choices = ["High School", "Bachelor", "Master", "PhD"]
    education = rng.choice(education_choices, size=num_rows, p=[0.3, 0.45, 0.2, 0.05])

    employment_choices = ["Employed", "Self-Employed", "Unemployed"]
    employment = rng.choice(employment_choices, size=num_rows, p=[0.75, 0.18, 0.07])

    home_choices = ["Rent", "Own", "Mortgage"]
    home_ownership = rng.choice(home_choices, size=num_rows, p=[0.4, 0.25, 0.35])

    # Deterministic label calculation with noise
    score = (
        (credit_score - 350) / 500.0 * 0.45
        + (income / 150000.0) * 0.35
        - (loan_amount / 50000.0) * 0.20
        + rng.normal(0, 0.08, size=num_rows)
    )
    approved = (score > 0.40).astype(int)

    df = pd.DataFrame({
        "id": np.arange(1, num_rows + 1),
        "age": age,
        "income": income,
        "credit_score": credit_score,
        "education": education,
        "employment": employment,
        "home_ownership": home_ownership,
        "loan_amount": loan_amount,
        "approved": approved,
    })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"[Dataset Generator] Created {num_rows} rows at: {output_path} (size: {output_path.stat().st_size} bytes)")
    return output_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic ML tabular CSV.")
    parser.add_argument("--rows", type=int, default=5000, help="Number of rows (default: 5000)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
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
    )
