"""
Data Siege defense: one cheap tool call per event, decision from free baseline
constants plus calibrated thresholds. No file I/O, no stdout prints.
"""
import math

from api import Verdict

# Calibrated gaps between clean variation and fault magnitude (see lab guide).
FEATURE_SHIFT_THRESHOLD = 0.65
EMBED_SHIFT_THRESHOLD = 0.040
EMBED_AGE_THRESHOLD = 45.0
COMPOSITE_THRESHOLD = 1.30
# Clean practice runs top out at ~4630 ms; baseline (mu+3sigma) is 5135, which is loose.
LINEAGE_RUNTIME_THRESHOLD = 4650.0
REQUIRED_UPSTREAM = ("raw.orders", "raw.customers")


def register(ctx):
    ctx.on("data_batch", check_data_batch)
    ctx.on("contract_checkpoint", check_contract_checkpoint)
    ctx.on("lineage_run", check_lineage_run)
    ctx.on("feature_materialization", check_feature_materialization)
    ctx.on("embedding_batch", check_embedding_batch)


def _ok(res):
    return isinstance(res, dict) and "error" not in res


def check_data_batch(payload, ctx):
    b = ctx.baseline
    p = ctx.tools.batch_profile(payload["batch_id"])
    if not _ok(p):
        return Verdict(alert=False, pillar="checks")

    rows = p["row_count"]
    null = p["null_rate"]["customer_id"] if isinstance(p["null_rate"], dict) else p["null_rate"]
    mean = p["mean_amount"]
    stale = p["staleness_min"]

    reasons = []
    if not b["row_count_min"] <= rows <= b["row_count_max"]:
        reasons.append("row_count out of range")
    if null > b["null_rate_max"]:
        reasons.append("null_rate high")
    if not b["mean_amount_min"] <= mean <= b["mean_amount_max"]:
        reasons.append("mean_amount out of range")
    if stale > b["staleness_min_max"]:
        reasons.append("staleness high")

    if not reasons:
        # bounds are mu +/- 3 sigma: centre them and scale by the half-range (3 sigma units)
        mu_r = (b["row_count_min"] + b["row_count_max"]) / 2
        sd_r = (b["row_count_max"] - b["row_count_min"]) / 2
        mu_m = (b["mean_amount_min"] + b["mean_amount_max"]) / 2
        sd_m = (b["mean_amount_max"] - b["mean_amount_min"]) / 2
        norm2 = math.sqrt(
            ((rows - mu_r) / sd_r) ** 2
            + ((mean - mu_m) / sd_m) ** 2
            + (null / b["null_rate_max"]) ** 2
            + (stale / b["staleness_min_max"]) ** 2
        )
        ctx.state.setdefault("norm2", []).append(norm2)
        if norm2 > COMPOSITE_THRESHOLD:
            reasons.append(f"composite norm2={norm2:.2f}")

    return Verdict(alert=bool(reasons), pillar="checks", reason="; ".join(reasons))


def check_contract_checkpoint(payload, ctx):
    d = ctx.tools.contract_diff(payload["contract_id"], payload["checkpoint_batch_id"])
    if not _ok(d):
        return Verdict(alert=False, pillar="contracts")

    if d.get("violations"):
        return Verdict(alert=True, pillar="contracts", reason=f"violations: {d['violations']}")

    delay = d["freshness_delay_min"]
    declared = (payload.get("declared_sla") or {}).get("freshness_min")
    limit = ctx.baseline["freshness_delay_max_min"]
    if declared is not None:
        limit = min(limit, declared)
    if delay > limit:
        return Verdict(alert=True, pillar="contracts", reason=f"freshness delay {delay} > {limit}")
    return Verdict(alert=False, pillar="contracts")


def check_lineage_run(payload, ctx):
    s = ctx.tools.lineage_graph_slice(payload["run_id"])
    if not _ok(s):
        return Verdict(alert=False, pillar="lineage")

    if s.get("actual_downstream_count") == 0:
        return Verdict(alert=True, pillar="lineage", reason="orphan output")
    upstream = set(s.get("actual_upstream") or [])
    missing = [u for u in REQUIRED_UPSTREAM if u not in upstream]
    if missing and upstream is not None and _is_stg_orders(payload):
        return Verdict(alert=True, pillar="lineage", reason=f"missing upstream {missing}")
    if s["duration_ms"] > min(LINEAGE_RUNTIME_THRESHOLD, ctx.baseline["lineage_duration_ms_max"]):
        return Verdict(alert=True, pillar="lineage", reason="runtime anomaly")
    return Verdict(alert=False, pillar="lineage")


def _is_stg_orders(payload):
    return "stg_orders" in str(payload.get("model") or payload.get("job") or payload)


def check_feature_materialization(payload, ctx):
    r = ctx.tools.feature_drift(payload["feature_view"], payload["batch_id"])
    if not _ok(r):
        return Verdict(alert=False, pillar="ai_infra")
    if r["mean_shift_sigma"] > FEATURE_SHIFT_THRESHOLD:
        return Verdict(alert=True, pillar="ai_infra", reason=f"feature shift {r['mean_shift_sigma']:.3f}")
    return Verdict(alert=False, pillar="ai_infra")


def check_embedding_batch(payload, ctx):
    r = ctx.tools.embedding_drift(payload["corpus"], payload["chunk_batch_id"])
    if not _ok(r):
        return Verdict(alert=False, pillar="ai_infra")
    if r["centroid_shift"] > EMBED_SHIFT_THRESHOLD:
        return Verdict(alert=True, pillar="ai_infra", reason=f"centroid shift {r['centroid_shift']:.4f}")
    if r["avg_doc_age_days"] > EMBED_AGE_THRESHOLD:
        return Verdict(alert=True, pillar="ai_infra", reason=f"stale corpus {r['avg_doc_age_days']}d")
    return Verdict(alert=False, pillar="ai_infra")
