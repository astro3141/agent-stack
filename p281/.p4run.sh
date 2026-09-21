#!/bin/sh
# usage: .p4run.sh <case> <approve|decline|none> [PRELOOP_URL]
C=$1; W=/tmp/p281/ws-$C; rm -rf $W /tmp/p281/runs/$C; mkdir -p $W
cat > /tmp/p281/req-$C.json <<J
{"run_id":"$C","provider":"claude","cwd":"$W","timeout_ms":${TMO:-240000},
 "prompt":"Create a file named marker.txt in the current directory containing exactly: P4. Use your file-writing tool. Do not do anything else."}
J
[ "$2" != none ] && { python3 /work/p281/approver.py $W $2 200 > /tmp/p281/approver-$C.out & }
[ -n "$3" ] && export PRELOOP_API_URL=$3
node /work/p281/run-agent.mjs /tmp/p281/req-$C.json; echo "exit=$?"
echo "file: $(cat $W/marker.txt 2>/dev/null || echo ABSENT)"
sleep 1; cat /tmp/p281/approver-$C.out 2>/dev/null
