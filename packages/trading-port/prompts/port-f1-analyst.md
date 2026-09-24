COMMON CONTRACT (every lane, from the harness constitution):
- Your only input is {WS}/packet.json — a frozen ResearchPacket bridged from the harness
  (universe with per-symbol returns/volatility/volume_trend/high_low_position, evidence with
  source_id + available_at, constraints). No other source exists; invent nothing.
- Every symbol you name MUST be in packet.universe.
- Every weight ∈ [constraints.min_weight, constraints.max_weight_per_symbol]; Σweights ≤ constraints.max_gross.
- Every id in "refs" MUST be an evidence source_id present in the packet (grounding).
- You have NO authority over deterministic math (valuation/scoring/hard-risk) — that is a script step.
- Write files ONLY with the MCP tool preloop__write_file. Reply one short line when done.

LANE F, step 1 — ANALYST. Read the packet and write a bounded analysis (no portfolio yet):
per candidate symbol, the case for/against grounded in evidence. Write {WS}/f_analysis.json:
{"analyst":"...","candidates":[{"symbol":"...","view":"bull|bear|neutral","why":"...","refs":["<source_id>"]}]}
