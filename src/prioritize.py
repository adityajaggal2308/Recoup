"""
prioritize.py — Step 2 of the agent: explainable prioritization.

No LLM call here on purpose. Prioritization is the part of the system that
most needs to be auditable — a business needs to be able to point at the
formula and defend it, not trust a black box. Every input to the score is
either raw account data or a value diagnose.py already explained.

    recovery_score = amount_owed x pay_likelihood x urgency

- amount_owed         -> account["plan_amount"] (the amount actually at risk this cycle)
- pay_likelihood      -> diagnose.py's estimate that this account pays if contacted
- urgency             -> derived below from card_expiry_days and last_login_days_ago:
                         a card that's expiring/expired soon, or an account still
                         logging in (not fully disengaged), is more urgent to act on
                         *before* the window to recover it closes.
"""

URGENCY_MIN, URGENCY_MAX = 0.3, 1.0


def compute_urgency(account: dict) -> float:
    """Blend two signals into a single 0.3-1.0 urgency multiplier:
    - card_expiry_days: negative or near-zero => card is (or is about to be)
      unusable => highest urgency.
    - last_login_days_ago: an account still actively logging in is more
      urgent to recover than one that's gone fully dark (that's a lower
      pay_likelihood problem, not an urgency one, and pay_likelihood already
      captures it).
    """
    expiry = account["card_expiry_days"]
    if expiry <= 0:
        expiry_urgency = 1.0
    elif expiry <= 15:
        expiry_urgency = 0.85
    elif expiry <= 45:
        expiry_urgency = 0.6
    else:
        expiry_urgency = 0.35

    last_login = account["last_login_days_ago"]
    if last_login <= 14:
        engagement_urgency = 0.9
    elif last_login <= 45:
        engagement_urgency = 0.6
    else:
        engagement_urgency = 0.35

    blended = 0.6 * expiry_urgency + 0.4 * engagement_urgency
    return round(max(URGENCY_MIN, min(URGENCY_MAX, blended)), 3)


def score_account(account: dict) -> dict:
    urgency = compute_urgency(account)
    pay_likelihood = account.get("pay_likelihood", 0.5)
    amount_owed = account["plan_amount"]

    recovery_score = round(amount_owed * pay_likelihood * urgency, 2)

    return {
        **account,
        "urgency": urgency,
        "recovery_score": recovery_score,
        "score_formula": f"{amount_owed:.2f} (amount owed) x {pay_likelihood:.2f} (pay likelihood) x {urgency:.2f} (urgency) = {recovery_score:.2f}",
    }


def prioritize(accounts: list[dict]) -> list[dict]:
    scored = [score_account(a) for a in accounts]
    scored.sort(key=lambda a: a["recovery_score"], reverse=True)
    for i, a in enumerate(scored, start=1):
        a["rank"] = i
    return scored


if __name__ == "__main__":
    from data_loader import load_payments
    from diagnose import diagnose_all
    accounts = diagnose_all(load_payments()[:5])
    for a in prioritize(accounts):
        print(a["rank"], a["customer_id"], a["recovery_score"], a["score_formula"])
