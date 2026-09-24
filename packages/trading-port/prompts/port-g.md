COMMON CONTRACT (every lane, from the harness constitution):
- Your only input is {WS}/packet.json — a frozen ResearchPacket bridged from the harness
  (universe with per-symbol returns/volatility/volume_trend/high_low_position, evidence with
  source_id + available_at, constraints). No other source exists; invent nothing.
- Every symbol you name MUST be in packet.universe.
- Every weight ∈ [constraints.min_weight, constraints.max_weight_per_symbol]; Σweights ≤ constraints.max_gross.
- Every id in "refs" MUST be an evidence source_id present in the packet (grounding).
- You have NO authority over deterministic math (valuation/scoring/hard-risk) — that is a script step.
- Write files ONLY with the MCP tool preloop__write_file. Reply one short line when done.

LANE G — same single decision as E, but you may cite the packet's evidence as the memory of what
was disclosed and when (available_at). Reason over the disclosure history in the packet only; do
not claim any past fact that is not an evidence item. Write {WS}/lane_G.json EXACTLY:
{"lane":"G","policy":"bounded memory","model_calls":1,
 "targets":[{"symbol":"...","weight":0.0}],"rationale":"<one sentence>","refs":["<source_id>"]}
