COMMON CONTRACT (every lane, from the harness constitution):
- Your only input is {WS}/packet.json — a frozen ResearchPacket bridged from the harness
  (universe with per-symbol returns/volatility/volume_trend/high_low_position, evidence with
  source_id + available_at, constraints). No other source exists; invent nothing.
- Every symbol you name MUST be in packet.universe.
- Every weight ∈ [constraints.min_weight, constraints.max_weight_per_symbol]; Σweights ≤ constraints.max_gross.
- Every id in "refs" MUST be an evidence source_id present in the packet (grounding).
- You have NO authority over deterministic math (valuation/scoring/hard-risk) — that is a script step.
- Write files ONLY with the MCP tool preloop__write_file. Reply one short line when done.

LANE H, step 3 — DECIDE. A deterministic script has scored your forecasts into {WS}/h_score.json
(you did NOT score them). Read the packet, your {WS}/h_forecast.json and the script's
{WS}/h_score.json, then decide the book. Write {WS}/lane_H.json EXACTLY:
{"lane":"H","policy":"forecast + deterministic score + decide","model_calls":2,
 "targets":[{"symbol":"...","weight":0.0}],"rationale":"<one sentence>","refs":["<source_id>"]}
