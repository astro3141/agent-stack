#!/bin/sh
# The shared proxy, and one proxy per role that declared its own hosts.
#
# The shared one is what every step had before per-role egress existed (OPERATIONS §45): one
# allowlist for the whole governed network. A role that declares hosts gets its own instance
# instead — its own port, its own filter, and a BasicAuth credential nothing in the agent can read
# except the launcher (§48). Both are tinyproxy; a single instance cannot serve two lists, because
# Filter and BasicAuth are global to a configuration.
#
# The per-role configurations are generated into a volume this container shares with the agent
# (`stack/role_egress.py write`, run as root from scripts/up.sh). Reading them here rather than
# baking them in is what makes a restart pick up a role added yesterday.
set -u
CREDS="${AGENTSTACK_ROLE_CREDS:-/role-egress}"

tinyproxy -d -c /etc/tinyproxy/tinyproxy.conf &
SHARED=$!
echo "egress: shared proxy on 8888 (pid $SHARED)"

started=0
if [ -d "$CREDS" ]; then
  for conf in "$CREDS"/*.conf; do
    [ -f "$conf" ] || continue
    role="$(basename "$conf" .conf)"
    port="$(awk '/^Port /{print $2}' "$conf")"
    if tinyproxy -c "$conf"; then
      started=$((started + 1))
      echo "egress: $role on ${port:-?}"
    else
      echo "egress: $role FAILED to start from $conf" >&2
    fi
  done
fi
echo "egress: $started role proxies"

# The shared proxy is this container's reason to exist: if it ends, the container ends, and the
# restart policy brings both back. A role proxy that dies is reported by the bring-up check instead
# of being restarted silently, because a role that cannot reach anything must not look healthy.
wait "$SHARED"
