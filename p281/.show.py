"""Show what Preloop's own API says about permission-check — asked of the running server.

It used to read a 440 KB copy of Preloop's OpenAPI document committed into this repository. That
document is theirs, not ours, and a repository that can be published does not carry a vendor's API
description for convenience. The running server answers the same question.

usage:  /opt/venv/bin/python /work/p281/.show.py        (in the agent or admin container)
"""
import json, sys, urllib.request

sys.path.insert(0, "/work/p281")
import settings

url = settings.runtime()["preloop"]["api_url"] + "/api/v1/openapi.json"
with urllib.request.urlopen(url, timeout=20) as r:
    d = json.load(r)
op = d["paths"]["/api/v1/agents/permission-check"]
print(json.dumps(op, indent=1)[:2500])
S = d["components"]["schemas"]
for n in S:
    if "ermission" in n:
        print("==", n)
        print(json.dumps(S[n], indent=1)[:3000])
