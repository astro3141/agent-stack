#!/bin/sh
# Option B run. usage: .b-run.sh <case> <file-name> [approve|decline|none]; PROV selects vendor.
C=$1; W=/ws/$C; rm -rf $W /tmp/agentstack/runs/$C; mkdir -p $W
cat > /tmp/agentstack/req-$C.json <<J
{"run_id":"$C","provider":"${PROV:-claude}","cwd":"$W","timeout_ms":${TMO:-400000},"native_tools":false,
 "prompt":"Create a file named $2 in the directory $W containing exactly: B1. Use the write_file tool from the preloop MCP server with the absolute path. Do not do anything else."}
J
[ "${3:-none}" != none ] && { python3 /work/stack/approver.py $W $3 300 > /tmp/agentstack/approver-$C.out & }
node /work/stack/run-agent.mjs /tmp/agentstack/req-$C.json; echo "exit=$?"
echo "file: $(cat $W/$2 2>/dev/null || echo ABSENT)"
sleep 1; cat /tmp/agentstack/approver-$C.out 2>/dev/null
