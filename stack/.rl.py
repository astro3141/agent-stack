import json,os,urllib.request
tok=[l.split(":",1)[1].strip() for l in open(os.path.expanduser("~/.preloop/config.yaml")) if l.startswith("access_token:")][0]
def get(u,t):
    r=urllib.request.Request("http://api:8000"+u,headers={"Authorization":"Bearer "+t})
    try: return json.load(urllib.request.urlopen(r,timeout=20))
    except urllib.error.HTTPError as e: return {"http":e.code,"body":e.read().decode()[:300]}
print(json.dumps(get("/api/v1/account/gateway-usage/rate-limits",tok),indent=1)[:4000])
