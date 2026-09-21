import json
d=json.load(open('/work/p281/.preloop-openapi.json'))
op=d['paths']['/api/v1/agents/permission-check']
print(json.dumps(op,indent=1)[:2500])
S=d['components']['schemas']
for n in S:
    if 'ermission' in n: print('==',n); print(json.dumps(S[n],indent=1)[:3000])
