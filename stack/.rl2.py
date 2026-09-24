import json,os,urllib.request
tok=[l.split(":",1)[1].strip() for l in open(os.path.expanduser("~/.preloop/config.yaml")) if l.startswith("access_token:")][0]
d=json.load(urllib.request.urlopen(urllib.request.Request("http://api:8000/api/v1/account/gateway-usage/rate-limits",headers={"Authorization":"Bearer "+tok}),timeout=20))
for s in d["latest_snapshots"]:
    h=(s.get("rate_limit") or {}).get("headers") or {}
    keys=sorted(k for k in h if "utiliz" in k or "used" in k or "percent" in k or "window" in k)
    print(s["provider_name"], s["model_alias"], s["observed_at"], s["status_code"], s.get("upstream_credential_type"), {k:h[k] for k in keys} or list(h)[:6] or s.get("rate_limit"))
