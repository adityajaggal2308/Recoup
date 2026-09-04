"""
map_telco_dataset.py

One-time mapping script: reads the raw Kaggle "Telco Customer Churn" dataset
(blastchar/telco-customer-churn, file WA_Fn-UseC_-Telco-Customer-Churn.csv)
and outputs data/payments.csv in the schema Recoup (the AI Revenue Recovery
Agent) expects.

USAGE:
    1. Download WA_Fn-UseC_-Telco-Customer-Churn.csv from Kaggle:
       https://www.kaggle.com/datasets/blastchar/telco-customer-churn
    2. Place it at data/raw/WA_Fn-UseC_-Telco-Customer-Churn.csv
    3. Run: python src/map_telco_dataset.py

This filters to churned customers (our stand-in for "failed payment"
accounts), samples SAMPLE_SIZE of them for a clean demo, and writes the
result to data/payments.csv. That file is committed to the repo so the
deployed app never needs Kaggle access at runtime.

REAL vs. SIMULATED FIELDS
--------------------------
Real, derived directly from Kaggle columns:
    customer_id            <- customerID
    plan_amount            <- MonthlyCharges
    months_paid_on_time    <- tenure
    total_lifetime_value   <- TotalCharges
    payment_method         <- PaymentMethod   (diagnosis signal)
    contract_type          <- Contract        (churn-risk signal)
    (queue is filtered to Churn == "Yes")

Simulated — the Kaggle dataset has no billing-system data, so these are
generated with a documented, deterministic rule tied to real columns.
They are NOT real payment-gateway data and are labeled as simulated
throughout the UI and README:
    card_expiry_days       <- shorter window for month-to-month contracts
    last_login_days_ago    <- inversely related to tenure
    failed_attempts        <- higher for Electronic check payment method
"""
import csv
import os
import random

RAW_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "WA_Fn-UseC_-Telco-Customer-Churn.csv")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "payments.csv")
SAMPLE_SIZE = 100

random.seed(7)


def simulate_card_expiry_days(contract_type: str) -> int:
    """Month-to-month customers get a shorter, riskier expiry window —
    they've shown less commitment, so we model less payment-method upkeep."""
    if contract_type == "Month-to-month":
        return random.randint(-15, 20)   # can be already-expired (negative)
    if contract_type == "One year":
        return random.randint(10, 90)
    return random.randint(30, 180)        # Two year


def simulate_last_login_days_ago(tenure_months) -> int:
    """Inversely related to tenure: newer / lower-tenure accounts are modeled
    as less engaged (higher days-since-login)."""
    tenure_months = max(int(tenure_months), 0)
    base = max(2, 60 - tenure_months)
    return int(base + random.uniform(-5, 15))


def simulate_failed_attempts(payment_method: str) -> int:
    """Electronic check is the payment method Kaggle's own EDA repeatedly
    flags as highest-churn; we model it as also having more failed
    processing attempts historically."""
    if payment_method == "Electronic check":
        return random.randint(2, 5)
    return random.randint(0, 2)


def load_raw_rows():
    if not os.path.exists(RAW_PATH):
        raise FileNotFoundError(
            f"Raw Kaggle file not found at {RAW_PATH}.\n"
            "Download WA_Fn-UseC_-Telco-Customer-Churn.csv from "
            "https://www.kaggle.com/datasets/blastchar/telco-customer-churn "
            "and place it in data/raw/ before running this script."
        )
    with open(RAW_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def map_rows(raw_rows):
    churned = [r for r in raw_rows if r.get("Churn", "").strip() == "Yes"]
    if not churned:
        raise ValueError("No churned rows found in raw file — check the input CSV.")

    sample = random.sample(churned, min(SAMPLE_SIZE, len(churned)))

    mapped = []
    for r in sample:
        contract_type = r["Contract"]
        payment_method = r["PaymentMethod"]
        tenure = r["tenure"]

        try:
            total_lifetime_value = float(r["TotalCharges"])
        except (ValueError, TypeError):
            # Kaggle's TotalCharges has a handful of blank strings for
            # brand-new accounts; fall back to plan_amount * tenure.
            total_lifetime_value = float(r["MonthlyCharges"]) * max(int(tenure), 1)

        mapped.append({
            "customer_id": r["customerID"],
            "plan_amount": round(float(r["MonthlyCharges"]), 2),
            "months_paid_on_time": int(tenure),
            "total_lifetime_value": round(total_lifetime_value, 2),
            "payment_method": payment_method,
            "contract_type": contract_type,
            # --- simulated fields (see module docstring) ---
            "card_expiry_days": simulate_card_expiry_days(contract_type),
            "last_login_days_ago": simulate_last_login_days_ago(tenure),
            "failed_attempts": simulate_failed_attempts(payment_method),
        })
    return mapped


def write_payments_csv(mapped_rows):
    fieldnames = [
        "customer_id", "plan_amount", "months_paid_on_time",
        "total_lifetime_value", "payment_method", "contract_type",
        "card_expiry_days", "last_login_days_ago", "failed_attempts",
    ]
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(mapped_rows)


if __name__ == "__main__":
    raw_rows = load_raw_rows()
    mapped_rows = map_rows(raw_rows)
    write_payments_csv(mapped_rows)
    print(f"Wrote {len(mapped_rows)} rows to {OUT_PATH}")
