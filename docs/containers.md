# Which container does what

Half of a first debugging session used to go into finding out where a thing belongs: onboarding a
vendor answered **403** in the agent and worked in the admin container, and the rule behind that was
implied across several sections rather than stated once. This is the statement.

| container | it does | it must not | why |
|---|---|---|---|
| **agent** (`<stack>-agent`) | runs workflows and their steps; holds the provider logins under `/route`; calls models; reaches Preloop's MCP and `permission-check` | write anything to Preloop's control plane — approvals, tool rights, credentials, policy, MCP servers | it is the governed party. The guard refuses those writes from its network, whatever credential it presents (OPERATIONS §20–21) |
| **admin** (`<stack>-admin`) | everything that writes to Preloop: `cfg.py apply`, `cfg.py rescan`, `principals.py apply/create/rules`, `bootstrap_preloop.py`, `preloop agents onboard`, `preloop policy apply` | run workflows; hold provider logins | it is the operator's hand. Same image and tree as the agent, on the admin network, with no workspace and no vendor logins |
| **quota** (`<stack>-quota`) | observes provider quota on its own schedule, with its own login lineage | execute anything, or touch the agent's logins | reading how much is left must not share a credential with spending it. Since §29 it is a **second** source: the routing logins are read directly, so this one is optional |
| **ops** (`<stack>-ops`) | the panel's API: one route per action, each mapping to one known command; answers approvals with its own credential | be reachable from the agent | it is where the person acts. It holds the Docker socket, which is why it is published on loopback only |
| **hub** (`<stack>-hub`) | serves the panel and proxies the Conductor dashboard | hold Docker access or credentials | a screen with no authority of its own |
| **apiguard** (`<stack>-apiguard`) | the only route from the governed network to Preloop; refuses control-plane writes; holds the names `api`, `console`, `gateway` there | — | the approval boundary, drawn as a route (OPERATIONS §20) |
| **toolsvc / fsmcp** | the MCP tool servers the agent reaches **through Preloop**, never directly | be reachable from the agent's network | that indirection is what makes a tool call governable |
| **egress** | the allowlist proxy: the agent's only way out | — | an agent with a route to the internet is not isolated |
| **mlflow** | the record | — | dual-homed so a browser can reach it; the agent stays single-homed |
| **replay** | renders a past run's event log | hold credentials or Docker access | the live dashboard binds the agent's loopback and cannot be published (OPERATIONS §14) |

## The rule behind the table

**The governed party may read the control plane and may not change it.** Everything that changes
what the account enforces runs on the admin side. If a command answers 403 in the agent, that is
not a problem to route around: it is the boundary, and the same command belongs in `admin`.

```bash
docker exec <stack>-agent /opt/venv/bin/python /work/stack/<script>.py …   # runs, reads, MCP
docker exec <stack>-admin /opt/venv/bin/python /work/stack/<script>.py …   # writes to Preloop
```

[commands.md](commands.md) lists every command with the side it belongs on.

## What they share

- `/work` — this tree, in agent, admin and ops.
- `agent-home` — the Preloop CLI's home and the provider logins; mounted in agent and admin (so an
  onboarding done on the admin side is in effect for the agent), read-only in ops.
- `/ws` — the run workspace, shared between the agent and the file tool server so a tool call and a
  step act on the same files.
