#!/usr/bin/env python3
"""Deterministic generator script for sample datasets (seed 42).

Generates three realistic evaluation datasets in frontend/public/samples/:
1. customer_churn.csv (~600 rows, numeric features + binary churn label, ~80-90% RF accuracy)
2. loan_approval.csv (~600 rows, age, income, credit_score, education, employment, home_ownership, loan_amount, approved)
3. sensor_readings.csv (~500 rows, numeric industrial telemetry features + binary anomaly label)
"""

from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split


def generate_customer_churn(out_dir: Path, seed: int = 42) -> Path:
    rng = np.random.RandomState(seed)
    n = 600

    tenure_months = rng.randint(1, 72, size=n)
    monthly_charges = np.round(rng.uniform(20.0, 115.0, size=n), 2)
    total_charges = np.round(tenure_months * monthly_charges * rng.uniform(0.92, 1.05, size=n), 2)
    support_tickets = rng.poisson(lam=1.5, size=n)
    contract_years = rng.choice([0, 1, 2], p=[0.55, 0.25, 0.20], size=n)
    data_usage_gb = np.round(rng.exponential(scale=35.0, size=n) + 5.0, 1)

    # Ground truth logistic probability with controlled signal
    logits = (
        -0.045 * tenure_months
        + 0.025 * monthly_charges
        + 0.55 * support_tickets
        - 1.4 * contract_years
        + rng.normal(0, 0.7, size=n)
    )
    probs = 1.0 / (1.0 + np.exp(-logits))
    churn = (probs > 0.5).astype(int)

    df = pd.DataFrame({
        "tenure_months": tenure_months,
        "monthly_charges": monthly_charges,
        "total_charges": total_charges,
        "support_tickets": support_tickets,
        "contract_years": contract_years,
        "data_usage_gb": data_usage_gb,
        "churn": churn,
    })

    # Validate Random Forest test accuracy is ~80-90%
    X = df.drop(columns=["churn"])
    y = df["churn"]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=y)
    clf = RandomForestClassifier(n_estimators=100, random_state=seed)
    clf.fit(X_train, y_train)
    acc = clf.score(X_test, y_test)
    print(f"customer_churn.csv generated ({len(df)} rows) — RF accuracy: {acc:.2%}")

    file_path = out_dir / "customer_churn.csv"
    df.to_csv(file_path, index=False)
    return file_path


def generate_loan_approval(out_dir: Path, seed: int = 42) -> Path:
    rng = np.random.RandomState(seed)
    n = 600

    age = rng.randint(21, 68, size=n)
    income = np.round(rng.lognormal(mean=10.8, sigma=0.5, size=n), 0)
    credit_score = np.clip(rng.normal(670, 75, size=n).astype(int), 350, 850)

    education_levels = ["High School", "Bachelor", "Master", "Doctorate"]
    education = rng.choice(education_levels, p=[0.25, 0.50, 0.20, 0.05], size=n)

    employment_types = ["Salaried", "Self-Employed", "Contract", "Unemployed"]
    employment = rng.choice(employment_types, p=[0.65, 0.20, 0.10, 0.05], size=n)

    home_ownership_types = ["Rent", "Mortgage", "Own"]
    home_ownership = rng.choice(home_ownership_types, p=[0.45, 0.40, 0.15], size=n)

    loan_amount = np.round(rng.uniform(3000, 50000, size=n), 0)

    # Debt-to-income and credit score score
    dti = loan_amount / np.maximum(income, 10000)
    score = (
        (credit_score - 600) / 100.0 * 1.8
        + (income / 35000.0) * 0.9
        - dti * 2.2
        + (employment == "Salaried").astype(int) * 0.6
        + (home_ownership == "Own").astype(int) * 0.4
        + rng.normal(0, 0.6, size=n)
    )
    approved = (score > 1.0).astype(int)

    df = pd.DataFrame({
        "age": age,
        "income": income,
        "credit_score": credit_score,
        "education": education,
        "employment": employment,
        "home_ownership": home_ownership,
        "loan_amount": loan_amount,
        "approved": approved,
    })

    file_path = out_dir / "loan_approval.csv"
    df.to_csv(file_path, index=False)
    print(f"loan_approval.csv generated ({len(df)} rows)")
    return file_path


def generate_sensor_readings(out_dir: Path, seed: int = 42) -> Path:
    rng = np.random.RandomState(seed)
    n = 500

    temperature_c = np.round(rng.normal(65.0, 8.0, size=n), 2)
    pressure_bar = np.round(rng.normal(4.2, 0.6, size=n), 2)
    vibration_x = np.round(rng.exponential(0.8, size=n), 3)
    vibration_y = np.round(rng.exponential(0.8, size=n), 3)
    vibration_z = np.round(rng.exponential(1.1, size=n), 3)
    voltage_v = np.round(rng.normal(230.0, 4.5, size=n), 1)
    rpm = np.round(rng.normal(1750.0, 95.0, size=n), 0)

    # Anomaly conditions: high temp, high vibration, or pressure anomaly
    anomaly_score = (
        (temperature_c - 70.0) / 10.0 * 1.2
        + (vibration_z - 1.5) / 0.8 * 1.5
        + (np.abs(voltage_v - 230.0) / 8.0) * 1.0
        + rng.normal(0, 0.5, size=n)
    )
    anomaly = (anomaly_score > 0.8).astype(int)

    df = pd.DataFrame({
        "temperature_c": temperature_c,
        "pressure_bar": pressure_bar,
        "vibration_x": vibration_x,
        "vibration_y": vibration_y,
        "vibration_z": vibration_z,
        "voltage_v": voltage_v,
        "rpm": rpm,
        "anomaly": anomaly,
    })

    file_path = out_dir / "sensor_readings.csv"
    df.to_csv(file_path, index=False)
    print(f"sensor_readings.csv generated ({len(df)} rows)")
    return file_path


def main():
    root = Path(__file__).resolve().parent.parent
    samples_dir = root / "public" / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    print(f"Generating deterministic sample datasets in: {samples_dir}")

    generate_customer_churn(samples_dir, seed=42)
    generate_loan_approval(samples_dir, seed=42)
    generate_sensor_readings(samples_dir, seed=42)
    print("Done!")


if __name__ == "__main__":
    main()
