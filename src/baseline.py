"""
baseline.py — Step 3 of the agent: quantify the value of prioritizing at all.

The naive baseline models a team that contacts every failed-payment account
in the SAME order they happened to load (no prioritization), spending equal
effort per account, until it exhausts the same "outreach budget" (number of
accounts contacted) the agent uses for its top-N picks.

Two comparisons are reported, isolating exactly one variable — ordering —
so the efficiency gain is fair and explainable, not an apples-to-oranges
stat:

  1. Expected recovery (probability-weighted):
         expected_recovery = sum(plan_amount * pay_likelihood) over contacted accounts
     This is a forward-looking estimate available before anyone is
     actually contacted.

  2. Simulated recovery (concrete, seeded outcomes — see simulate_outcomes.py):
         revenue_recovered = sum(plan_amount for accounts that simulate to "paid")
     This turns the same pay_likelihood into one illustrative real/no-real
     outcome per account, so the dashboard can show a concrete number
     ("7 of 10 recovered, $412") rather than only a probability. It is
     clearly a simulation, not a real payment result — see the docstring
     in simulate_outcomes.py and the UI disclosure.
"""
from simulate_outcomes import simulate_batch, summarize


def expected_recovery(accounts: list[dict]) -> float:
    return round(sum(a["plan_amount"] * a.get("pay_likelihood", 0.5) for a in accounts), 2)


def compare(all_accounts_original_order: list[dict], prioritized_accounts: list[dict], outreach_budget: int) -> dict:
    """
    all_accounts_original_order: the full queue, in whatever order it loaded
                                  (this is what a non-prioritizing team would
                                  work through top-to-bottom)
    prioritized_accounts:        the same accounts, already sorted by
                                  recovery_score (from prioritize.py)
    outreach_budget:             how many accounts get contacted under either
                                  approach (a team only has so much time)
    """
    budget = min(outreach_budget, len(all_accounts_original_order))

    naive_contacted = all_accounts_original_order[:budget]
    agent_contacted = prioritized_accounts[:budget]

    naive_expected = expected_recovery(naive_contacted)
    agent_expected = expected_recovery(agent_contacted)

    total_owed_naive = round(sum(a["plan_amount"] for a in naive_contacted), 2)
    total_owed_agent = round(sum(a["plan_amount"] for a in agent_contacted), 2)

    if naive_expected > 0:
        efficiency_gain_pct = round((agent_expected - naive_expected) / naive_expected * 100, 1)
    else:
        efficiency_gain_pct = 0.0

    # Concrete simulated outcomes for the same two contacted sets.
    naive_simulated = simulate_batch(naive_contacted)
    agent_simulated = simulate_batch(agent_contacted)
    naive_sim_summary = summarize(naive_simulated)
    agent_sim_summary = summarize(agent_simulated)

    if naive_sim_summary["revenue_recovered"] > 0:
        simulated_efficiency_gain_pct = round(
            (agent_sim_summary["revenue_recovered"] - naive_sim_summary["revenue_recovered"])
            / naive_sim_summary["revenue_recovered"] * 100, 1
        )
    else:
        simulated_efficiency_gain_pct = 0.0

    return {
        "outreach_budget": budget,
        "naive": {
            "accounts_contacted": budget,
            "total_amount_targeted": total_owed_naive,
            "expected_recovery": naive_expected,
            **naive_sim_summary,
        },
        "agent": {
            "accounts_contacted": budget,
            "total_amount_targeted": total_owed_agent,
            "expected_recovery": agent_expected,
            **agent_sim_summary,
        },
        "efficiency_gain_pct": efficiency_gain_pct,
        "simulated_efficiency_gain_pct": simulated_efficiency_gain_pct,
        "agent_simulated_accounts": agent_simulated,  # used by agent.py to attach outcomes to the ranked queue
        "explanation": (
            f"Contacting the same number of accounts ({budget}), the naive approach "
            f"(work the queue in load order) has an expected recovery of "
            f"${naive_expected:,.2f}, versus ${agent_expected:,.2f} for the agent's "
            f"prioritized order — a {efficiency_gain_pct:+.1f}% change in expected "
            f"dollars recovered per unit of outreach effort. In the simulated run, "
            f"the naive approach recovered ${naive_sim_summary['revenue_recovered']:,.2f} "
            f"({naive_sim_summary['accounts_recovered']}/{naive_sim_summary['accounts_contacted']} accounts, "
            f"{naive_sim_summary['recovery_rate']*100:.0f}% recovery rate) versus "
            f"${agent_sim_summary['revenue_recovered']:,.2f} "
            f"({agent_sim_summary['accounts_recovered']}/{agent_sim_summary['accounts_contacted']} accounts, "
            f"{agent_sim_summary['recovery_rate']*100:.0f}% recovery rate) for the agent — "
            f"a {simulated_efficiency_gain_pct:+.1f}% change in simulated dollars recovered."
        ),
    }


if __name__ == "__main__":
    from data_loader import load_payments
    from diagnose import diagnose_all
    from prioritize import prioritize

    original = diagnose_all(load_payments())
    prioritized = prioritize(original)
    result = compare(original, prioritized, outreach_budget=10)
    import json
    print(json.dumps({k: v for k, v in result.items() if k != "agent_simulated_accounts"}, indent=2))
