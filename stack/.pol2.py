import glob, json, os, urllib.request
tok = json.load(open(glob.glob(os.path.expanduser("~/.preloop/agents/*/permission_hook.json"))[0]))["token"]
req = urllib.request.Request("http://api:8000/api/v1/policies/schema", headers={"Authorization": "Bearer " + tok})
d = json.load(urllib.request.urlopen(req, timeout=20))
defs = d["$defs"]
for name in ("ToolDefinition", "ToolCondition", "ConditionType", "ConditionAction", "MCPServerDefinition", "PolicyVersion"):
    o = defs.get(name, {})
    print("==", name)
    if "enum" in o:
        print("   enum:", o["enum"]); continue
    for k, v in (o.get("properties") or {}).items():
        desc = (v.get("description") or "")[:150].replace("\n", " ")
        print(f"   {k}: {desc}")
