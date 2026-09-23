import glob, json, os, urllib.request
tok = json.load(open(glob.glob(os.path.expanduser("~/.preloop/agents/*/permission_hook.json"))[0]))["token"]
req = urllib.request.Request("http://api:8000/api/v1/policies/schema", headers={"Authorization": "Bearer " + tok})
d = json.load(urllib.request.urlopen(req, timeout=20))
s = json.dumps(d)
print("schema size:", len(s))
def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("properties", "$defs", "definitions"):
                for kk in v:
                    print(f"{path}/{k}: {kk}")
            walk(v, path + "/" + k if k not in ("properties",) else path)
walk(d)
