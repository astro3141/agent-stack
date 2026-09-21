#!/bin/sh
# One escalated permission-check, resolved over HTTP by a second party after 3 s.
# usage: .roundtrip.sh approve|decline
ACT=$1
TOK=$(python3 -c "import json,glob;print(json.load(open(glob.glob('/home/agent/.preloop/agents/*/permission_hook.json')[0]))['token'])")
sh /work/p281/pcheck.sh Bash - "{\"command\":\"echo RT-$ACT > marker.txt\"}" 60 > /tmp/p281/rt-$ACT.out &
P=$!
sleep 3
ID=$(curl -s -H "Authorization: Bearer $TOK" 'http://console/api/v1/approval-requests?limit=10' | python3 -c "
import json,sys
for r in json.load(sys.stdin):
    if r['status']=='pending' and r['tool_args'].get('command')=='echo RT-$ACT > marker.txt': print(r['id']); break")
echo "request=$ID"
if [ "$ACT" = approve ]; then BODY='{"approved": true}'; else BODY='{"approved": false, "comment": "p281 decline control"}'; fi
curl -s -o /dev/null -w "resolve http=%{http_code}\n" -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' -d "$BODY" "http://console/api/v1/approval-requests/$ID/$ACT"
wait $P
cat /tmp/p281/rt-$ACT.out
