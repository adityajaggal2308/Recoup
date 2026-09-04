"""
agent.py — orchestrates the full pipeline and returns one JSON-serializable
result for the API/frontend.

Pipeline:
    load payments.csv                                          [deterministic]
      -> diagnose each account                                 [LLM]
      -> prioritize (explainable formula)                      [deterministic]
      -> compare vs. naive baseline + simulate outcomes         [deterministic]
      -> decide action + draft + self-critique for top N        [LLM, bounded by
         (stopping rule checked first, per account)              stopping rule]

Each stage is defensive: an LLM failure anywhere degrades that one account
to a conservative fallback (see diagnose.py / recommend_action.py) rather
than crashing the whole run, so server.py can always return a clean result.

Every run also gets:
  - a run_id + timestamp (for the audit trail)
  - a top-level pipeline_trace: which stages ran, and whether each is an
    LLM call or deterministic code — this is what the frontend renders as
    the live pipeline indicator, driven by real data instead of a canned
    animation
  - an audit_log: one row per account (the full queue, not just the top N)
    with diagnosis inputs/outputs, score breakdown, contacted/action/
    critique/simulated-outcome fields — exportable as JSON from the UI
"""
import os
import uuid
from datetime import datetime, timezone

from data_loader import load_payments, PaymentsLoadError
from diagnose import diagnose_all
from prioritize import prioritize
from baseline import compare
from recommend_action import recommend_for_top_accounts
from simulate_outcomes import simulate_account_outcome

TOP_N_FOR_ACTION = int(os.environ.get("TOP_N_FOR_ACTION", 5))
OUTREACH_BUDGET = int(os.environ.get("OUTREACH_BUDGET", 10))

PIPELINE_STAGES = [
    {"key": "load", "label": "Loading failed-payment queue", "type": "deterministic"},
    {"key": "diagnose", "label": "Diagnosing each account (technical vs. churn signal)", "type": "llm"},
    {"key": "prioritize", "label": "Scoring recovery priority (amount \u00d7 pay likelihood \u00d7 urgency)", "type": "deterministic"},
    {"key": "baseline", "label": "Comparing against naive baseline + simulating outcomes", "type": "deterministic"},
    {"key": "decide_draft", "label": "Checking stopping rule, deciding action, drafting outreach", "type": "mixed"},
    {"key": "critique", "label": "Self-critiquing and revising drafts", "type": "llm"},
]


def _build_audit_row(account: dict, contacted: bool, top_record: dict | None) -> dict:
    row = {
        "customer_id": account["customer_id"],
        "rank": account["rank"],
        "plan_amount": account["plan_amount"],
        "failure_reason": account.get("failure_reason"),
        "failure_type": account.get("failure_type"),
        "confidence": account.get("confidence"),
        "churn_risk": account.get("churn_risk"),
        "pay_likelihood": account.get("pay_likelihood"),
        "urgency": account.get("urgency"),
        "recovery_score": account.get("recovery_score"),
        "score_formula": account.get("score_formula"),
        "contacted": contacted,
        "simulated_recovered": account.get("simulated_recovered"),
        "simulated_amount_recovered": account.get("simulated_amount_recovered"),
    }
    if top_record is not None:
        row.update({
            "action": top_record.get("action"),
            "stopped_by_rule": top_record.get("stopped_by_rule"),
            "critique_passed": top_record.get("critique_passed"),
            "message_revised": top_record.get("message_revised"),
            "final_message": top_record.get("final_message"),
        })
    return row


def run_pipeline() -> dict:
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    accounts = load_payments()
    diagnosed = diagnose_all(accounts)
    prioritized = prioritize(diagnosed)

    baseline_comparison = compare(
        all_accounts_original_order=diagnosed,
        prioritized_accounts=prioritized,
        outreach_budget=OUTREACH_BUDGET,
    )

    # The comparison step already simulated outcomes for the top
    # `outreach_budget` accounts (the ones actually contacted) — reuse that
    # rather than re-simulating, then fill in "not contacted" for the rest
    # of the queue so every row in the dashboard has a consistent shape.
    simulated_by_id = {a["customer_id"]: a for a in baseline_comparison.pop("agent_simulated_accounts")}
    contacted_ids = set(simulated_by_id.keys())

    ranked_queue = []
    for account in prioritized:
        if account["customer_id"] in simulated_by_id:
            ranked_queue.append(simulated_by_id[account["customer_id"]])
        else:
            ranked_queue.append({**account, "simulated_recovered": None, "simulated_amount_recovered": None})

    top_accounts_with_actions = recommend_for_top_accounts(prioritized, top_n=TOP_N_FOR_ACTION)
    # top_accounts came from `prioritized`, not `ranked_queue`, so attach the
    # simulated outcome for display in the expanded detail view too.
    for rec in top_accounts_with_actions:
        sim = simulated_by_id.get(rec["customer_id"])
        if sim:
            rec["simulated_recovered"] = sim["simulated_recovered"]
            rec["simulated_amount_recovered"] = sim["simulated_amount_recovered"]

    top_by_id = {r["customer_id"]: r for r in top_accounts_with_actions}

    total_revenue_at_risk = round(sum(a["plan_amount"] for a in prioritized), 2)
    recoverable_estimate = round(sum(a["plan_amount"] * a.get("pay_likelihood", 0.5) for a in prioritized), 2)

    escalated_count = sum(1 for r in top_accounts_with_actions if r.get("stopped_by_rule"))

    audit_log = [
        _build_audit_row(a, a["customer_id"] in contacted_ids, top_by_id.get(a["customer_id"]))
        for a in ranked_queue
    ]

    finished_at = datetime.now(timezone.utc).isoformat()

    return {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "pipeline_trace": PIPELINE_STAGES,
        "summary": {
            "total_accounts": len(prioritized),
            "total_revenue_at_risk": total_revenue_at_risk,
            "recoverable_estimate": recoverable_estimate,
            "efficiency_gain_pct": baseline_comparison["efficiency_gain_pct"],
            "simulated_efficiency_gain_pct": baseline_comparison["simulated_efficiency_gain_pct"],
            "outreach_budget": baseline_comparison["outreach_budget"],
            "revenue_recovered": baseline_comparison["agent"]["revenue_recovered"],
            "recovery_rate": baseline_comparison["agent"]["recovery_rate"],
            "accounts_escalated": escalated_count,
        },
        "funnel": {
            "at_risk": len(prioritized),
            "prioritized": len(prioritized),
            "contacted": baseline_comparison["outreach_budget"],
            "recovered": baseline_comparison["agent"]["accounts_recovered"],
        },
        "baseline_comparison": baseline_comparison,
        "ranked_queue": ranked_queue,
        "top_accounts": top_accounts_with_actions,
        "audit_log": audit_log,
    }


if __name__ == "__main__":
    import json
    try:
        result = run_pipeline()
        print(json.dumps(result["summary"], indent=2))
        print(f"\nrun_id: {result['run_id']}")
        print(f"{len(result['top_accounts'])} top accounts drafted, {result['summary']['accounts_escalated']} escalated by stopping rule.")
        print(f"audit_log rows: {len(result['audit_log'])}")
    except PaymentsLoadError as e:
        print(f"Data error: {e}")
