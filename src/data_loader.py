"""
data_loader.py — loads and lightly validates the payments queue.

The mapping step (map_telco_dataset.py) already filters to churned /
failed-payment accounts and writes a clean CSV, so this module's job is
just: load it, coerce types defensively, and hand back a list of plain
dicts the rest of the pipeline can work with (no pandas objects leaking
into the agent logic).
"""
import csv
import os

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "payments.csv")

REQUIRED_FIELDS = [
    "customer_id", "plan_amount", "months_paid_on_time",
    "total_lifetime_value", "payment_method", "contract_type",
    "card_expiry_days", "last_login_days_ago", "failed_attempts",
]

NUMERIC_FIELDS = {
    "plan_amount": float,
    "months_paid_on_time": int,
    "total_lifetime_value": float,
    "card_expiry_days": int,
    "last_login_days_ago": int,
    "failed_attempts": int,
}


class PaymentsLoadError(Exception):
    pass


def load_payments(path: str = DEFAULT_PATH) -> list[dict]:
    if not os.path.exists(path):
        raise PaymentsLoadError(
            f"payments.csv not found at {path}. "
            "Run src/map_telco_dataset.py first, or make sure data/payments.csv "
            "is committed to the repo."
        )

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise PaymentsLoadError("payments.csv is empty.")

    missing = set(REQUIRED_FIELDS) - set(rows[0].keys())
    if missing:
        raise PaymentsLoadError(f"payments.csv is missing required columns: {sorted(missing)}")

    clean_rows = []
    for i, row in enumerate(rows):
        clean = dict(row)
        for field, caster in NUMERIC_FIELDS.items():
            try:
                clean[field] = caster(row[field])
            except (ValueError, TypeError):
                raise PaymentsLoadError(f"Row {i} ({row.get('customer_id')}): bad value for {field!r}: {row.get(field)!r}")
        clean_rows.append(clean)

    return clean_rows


if __name__ == "__main__":
    payments = load_payments()
    print(f"Loaded {len(payments)} accounts")
    print(payments[0])
