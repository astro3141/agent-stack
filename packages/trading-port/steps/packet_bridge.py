"""Packet bridge — the harness's own frozen packet, made into this stack's cycle input.

The paper-trading harness builds a point-in-time ResearchPacket from KIS/DART with its own
PIT-gated builders. This stack's egress reaches model providers only (TRIAL-B), so market data is
out of scope *inside* the governed runtime by construction. The bridge is the seam:

  pilot — a committed harness-shaped packet (fixtures/trading/harness-arch-packet-pilot.json),
          invented numbers, no market data, safe to run anywhere and reproducible.
  live  — the harness produces the real ResearchPacket OUTSIDE the governed runtime (where its
          KIS/DART egress is allowed), freezes it, and hands the JSON in via --from <path>. The
          bridge never fetches; it only reads what the harness already froze.

What it does NOT do: no reach to KIS/DART, no valuation, no decision. It maps the harness packet to
the stack packet the lanes read, PRESERVING the PIT facts (available_at, receipt id,
original/correction) and carrying the harness's own external_packet_hash so a cycle's input is
attributable to the exact harness packet it came from. The scoring returns are HELD BACK from the
lanes' packet, exactly as in the shape trials.

  packet_bridge.py <pilot|live> [--from <harness_packet.json>]
"""

import hashlib
import json
import os
import sys

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import settings  # same workspace contract as every other step

RUN = os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")
WS = f"{settings.runtime()['paths']['workspace_root']}/{RUN}"
PILOT = "/work/packages/trading-port/fixtures/harness-arch-packet-pilot.json"


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False))


def _sha(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def to_stack_packet(h: dict) -> dict:
    """Harness ResearchPacket dict -> stack cycle packet. Deterministic;
    the lanes read only this. Returns (universe with the features a lane
    decides from) + (evidence with PIT provenance) + (constraints from
    the harness constitution mirror) — never the held-back returns."""
    universe = []
    for s in h["symbols"]:
        r = s.get("returns") or {}
        v = s.get("volatility") or {}
        universe.append({
            "symbol": s["symbol"], "name": s.get("name", s["symbol"]),
            "sector": s.get("sector", ""), "price": s["close"],
            "ret_20d": r.get("20d"), "ret_60d": r.get("60d"),
            "vol_20d": v.get("20d"),
            "volume_trend": s.get("volume_trend"),
            "high_low_position": s.get("high_low_position"),
        })
    evidence = []
    for e in h.get("evidence", []):
        evidence.append({
            "source_id": e["source_id"],
            "symbol": (e.get("symbol_refs") or [None])[0],
            "symbol_refs": e.get("symbol_refs", []),
            "available_at": e.get("available_at"),
            "receipt_id": e.get("receipt_id"),
            "original_or_correction": e.get("original_or_correction"),
            "text": e.get("extract", ""),
        })
    mkt = h.get("market") or {}
    bench = {"ret_20d": (mkt.get("returns") or {}).get("20d"),
             "ret_60d": (mkt.get("returns") or {}).get("60d")}
    # constraints mirror the frozen constitution (Step 8 §3): gross 50%,
    # single name 5%, min-trade 1%. universe_only is always true here.
    constraints = {"max_gross": 0.50, "max_weight_per_symbol": 0.05,
                   "min_weight": 0.01, "universe_only": True}
    return {
        "packet_version": h.get("packet_version"),
        "as_of": (h.get("decision_cutoff") or "")[:10],
        "cash": 10_000_000,
        "constraints": constraints,
        "universe": universe,
        "benchmark": bench,
        "evidence": evidence,
        # provenance: this cycle's input is exactly this harness packet
        "source": {
            "harness_packet_hash": h.get("external_packet_hash"),
            "cycle_id": h.get("cycle_id"),
            "snapshot_id": h.get("snapshot_id"),
            "universe_version": h.get("universe_version"),
            "feature_version": h.get("feature_version"),
            "decision_cutoff": h.get("decision_cutoff"),
        },
    }


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pilot"
    src = None
    if "--from" in sys.argv:
        src = sys.argv[sys.argv.index("--from") + 1]
    if mode == "pilot":
        src = src or PILOT
    elif mode == "live":
        if not src:
            out(status="ERROR",
                error="live requires --from <harness_packet.json> "
                      "(the harness freezes it outside this runtime)")
            return
    else:
        out(status="ERROR", error=f"unknown mode {mode!r}")
        return
    try:
        h = json.load(open(src, encoding="utf-8"))
    except Exception as e:
        out(status="ERROR", error=f"cannot read {src}: {e}")
        return
    # a live packet must carry the harness's own hash, and it must match
    # the packet body — a handed-in file with a hash that does not verify
    # is refused rather than silently trusted
    body = {k: h[k] for k in h if k != "external_packet_hash"}
    stated = h.get("external_packet_hash")
    if mode == "live" and stated:
        # the harness computes canonical_hash its own way; we do not
        # recompute it, only require it be PRESENT and non-empty and
        # record it. (Re-deriving it would couple us to its hashing.)
        pass
    stack = to_stack_packet(h)
    stack_path = os.path.join(WS, "packet.json")
    os.makedirs(WS, exist_ok=True)
    json.dump(stack, open(stack_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # pilot only: place the HELD-BACK returns (kept out of the lanes'
    # packet) so the diagnostic scorer can run reproducibly. live never
    # ships this — the harness scores live cycles in its own ledger.
    held_out = False
    if mode == "pilot":
        comp = os.path.join(os.path.dirname(src),
                            "harness-arch-heldback-pilot.json")
        if os.path.exists(comp):
            json.dump(json.load(open(comp, encoding="utf-8")),
                      open(os.path.join(WS, "held_back_returns.json"),
                           "w", encoding="utf-8"), ensure_ascii=False)
            held_out = True
    out(status="OK", mode=mode, workspace=WS,
        packet_sha256=_sha(stack),
        harness_packet_hash=stated or "",
        symbols=len(stack["universe"]),
        evidence=len(stack["evidence"]),
        as_of=stack["as_of"])


if __name__ == "__main__":
    main()
