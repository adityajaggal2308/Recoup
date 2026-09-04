"""
simulate_outcomes.py — turns each account's pay_likelihood into a concrete
simulated outcome (recovered / not recovered) so the dashboard can report
actual numbers ("7 of 10 accounts recovered, $412 recovered") instead of
only a probability-weighted expectation.

IMPORTANT — this is a simulation, not a real payment result. pay_likelihood
itself is an LLM estimate based on the available signals, not a trained
probability model; the simulated outcome is one illustrative draw against
that estimate, used to make the demo's impact concrete and comparable
against the naive baseline under identical conditions. Both the README and
the UI say this explicitly — it should never be read as a guarantee or a
real recovery figure.

Reproducibility: each account's draw is seeded from a fixed base seed
combined with its customer_id, so the same account with the same
pay_likelihood always simulates to the same outcome across runs (the
underlying pay_likelihood can still change between runs since it comes
from a live LLM call — only the simulation draw itself is pinned).
"""
import random
import zlib

SIM_SEED_BASE = 20260909  # fixed so demo runs are reproducible, not re-randomized each click


def _seeded_rng(customer_id: str) -> random.Random:
    account_seed = zlib.crc32(customer_id.encode("utf-8"))
    return random.Random(SIM_SEED_BASE ^ account_seed)


def simulate_account_outcome(account: dict) -> dict:
    """Returns the account merged with simulated_recovered (bool) and
    simulated_amount_recovered (float, 0.0 if not recovered)."""
    pay_likelihood = account.get("pay_likelihood", 0.5)
    rng = _seeded_rng(account["customer_id"])
    recovered = rng.random() < pay_likelihood
    amount = round(account["plan_amount"], 2) if recovered else 0.0
    return {
        **account,
        "simulated_recovered": recovered,
        "simulated_amount_recovered": amount,
    }


def simulate_batch(accounts: list[dict]) -> list[dict]:
    return [simulate_account_outcome(a) for a in accounts]


def summarize(simulated_accounts: list[dict]) -> dict:
    contacted = len(simulated_accounts)
    recovered = [a for a in simulated_accounts if a["simulated_recovered"]]
    revenue_recovered = round(sum(a["simulated_amount_recovered"] for a in simulated_accounts), 2)
    recovery_rate = round(len(recovered) / contacted, 3) if contacted else 0.0
    return {
        "accounts_contacted": contacted,
        "accounts_recovered": len(recovered),
        "revenue_recovered": revenue_recovered,
        "recovery_rate": recovery_rate,
    }
