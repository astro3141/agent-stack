# From a clone to a running stack

```bash
git clone <this repository> && cd agent-stack
scripts/install.sh --check      # what the host is missing; changes nothing
scripts/install.sh              # installs Preloop OSS if needed, then brings the stack up
```

Measured: on a Linux runner with none of this present, that sequence ends with the account claimed,
the policy applied, the principals created and the runtime refused every write to the control plane
(OPERATIONS §25). The only checks that fail are the provider logins, and those are a person's.

## What the host needs

| | why |
|---|---|
| Docker, and a running daemon | everything here is containers |
| **Docker Compose 2.24+** | the composition uses `env_file: required: false`; older compose fails with a parse error that does not name the feature |
| bash, git, curl | the scripts, and Preloop's own installer |
| **x86_64**, or arm64 untried | the agent image picks its Node and CodexBar by `TARGETARCH`; every image pulled is multi-arch. amd64 is what this has been built and run on, arm64 is parameterized and has never been built — the host check says so rather than letting a build discover it |
| ~11GB of images, plus volumes | measured |

`install.sh --check` asks for each of these by name and stops on the first that is missing, rather
than failing five minutes into a build.

## What the installer does

1. checks the host, as above;
2. runs **Preloop's own installer** into `~/.preloop-oss` when that directory is not there
   (`--preloop-dir` puts it elsewhere; the directory is also read from `config/instance.env`),
   pinned to the version this stack is measured against — `PRELOOP_VERSION=0.15.0` by default,
   overridable, because their installer otherwise takes whatever is current and a second machine
   would quietly be running a different subject;
3. hands over to `scripts/up.sh`.

## What `up.sh` does every time

- builds the images whose source is this tree (an edit to `ops/server.py` that is not built is an
  edit that does not run);
- brings up the composition, then Preloop, and **waits for Preloop's API to answer** rather than
  for a number of seconds;
- **claims a fresh Preloop**: registers the first user with the bootstrap token, issues the
  runtime's credential and installs the permission hook. The instance's own row count decides
  whether it is unclaimed — `POST /auth/register` on a claimed instance would quietly create a
  second tenant;
- applies the account policy from `policy/` and the principals from `config/principals.yaml`;
- reloads the approval guard's rules;
- runs about twenty checks and prints the capabilities this composition has.

## What no script will do for you

**Sign in to a provider.** Claude, Codex and Grok accounts belong to a person, on the vendor's own
page. The panel's 계정 tab (`http://127.0.0.1:8780`) starts the official login and takes the code.
Until then runs hold with `no eligible provider`, and the bring-up says so:

```
FAIL  every provider's state is knowable   expected 0, got 1
      claude: unknown: unparseable observed_at
```

That check exists because a login **file** can be there while its token is dead: an expired Claude
OAuth token once held three runs while `claude /route login` still said `true`.

## Secrets, and where they live

| | |
|---|---|
| `docker/preloop-owner.env` | the console account `up.sh` created (username, email, password) |
| `docker/principals.env` | one credential per role principal |
| `docker/operator.env` | a credential of the operator's own for the panel, if they make one |

All three are git-ignored, written by the **host** at mode 0600, and never printed. A container
mints a credential inside itself and `up.sh` moves it into place — a container writing into this
tree fails on Linux, and the failure once left an account whose password nobody knew.

## Choices the script does not make for you

- **Which composition** — `full`, `no-record` (no MLflow), `runtime` (no panel).
  `--composition <name>`, and `up.sh` prints what each costs.
- **Where Preloop lives** — `--preloop-dir`.
- **The instance's name and ports** — `config/instance.env`: `STACK`, `HUB_PORT`, `OPS_PORT`,
  `MLFLOW_PORT`, `PRELOOP_*_PORT`, `PRELOOP_PROJECT`, `PRELOOP_DIR`, `POC_HOST_DIR`.

## Installing a workflow

Declaring it is what installs it (packages.md): a directory copied under `packages/` without a
declaration is listed with that as its reason and offered as nothing.

```bash
# 1. declare it — config/packages.yaml for one this repository carries, config/packages.local.yaml
#    (git-ignored) for one that is yours alone
cat >> config/packages.local.yaml <<'EOF'
packages:
  trading-port:
    from: https://github.com/<owner>/trading-port.git
    ref: main
EOF
scripts/packages.sh install trading-port     # fetches it into packages/ and writes the lock
scripts/up.sh                                # its principals are created with their rights
docker exec agentstack-agent /opt/venv/bin/python /work/stack/packages.py          # listed, with no reason against it
scripts/cycle.sh trading-port research-default                                     # or, by hand:
docker exec agentstack-agent /opt/venv/bin/python /work/stack/run_workflow.py start first-port-1 trading-port research-default
```

A run id is `[a-z0-9-]`, 6 to 40 characters (`run_workflow.py` refuses a shorter one and says so).
Nothing in the platform is edited. `packages/hello-lane` is a working example of the shape
(concepts.md, OPERATIONS §27).

## A second instance on the same machine

Give it its own `config/instance.env` (name, ports, Preloop project and directory) and it runs
beside the first — separate containers, volumes and networks.

Set every port, including Preloop's. Preloop's own compose has 8000 / 8001 / 3000 written into it,
so `install.sh` rewrites those three lines to `${PRELOOP_API_PORT:-8000}` and friends — the same
numbers by default, this instance's when `config/instance.env` says so. (An
`docker-compose.override.yaml` does *not* work for this: compose reads that file only when it
resolves the files itself, and every call here names them with `-f`.) Their installer may fail to
start Preloop on a busy machine; that is not a failed install, and `up.sh` starts it on the right
ports afterwards.

A minimal second instance, beside a running first:

```
# config/instance.env
STACK=agst2
PRELOOP_PROJECT=preloop-two
PRELOOP_DIR=/home/you/.preloop-two
POC_HOST_DIR=/home/you/agent-stack-two
HUB_PORT=8880
OPS_PORT=8881
MLFLOW_PORT=5100
PRELOOP_API_PORT=8020
PRELOOP_GATEWAY_PORT=8021
PRELOOP_CONSOLE_PORT=3020
```

Never point a second instance at a first one's Preloop (`--no-preloop` with a shared directory):
the policy and the principals would be applied to **that** account.

Three things the second cold start found (OPERATIONS §69), each now handled:

- **Images are named for the instance** (`${STACK}/governed-runtime:local` and so on). Before
  this every instance built `agentstack/*:local`, so a second instance's build re-tagged the
  images the live one was running on; the live containers kept their image until recreated,
  and `release.sh record` reported it as a pruned image.
- **`docker/.env` is written from `config/instance.env`** by `up.sh` (and `restore.sh`), key by
  key, keeping anything else in it. A bare `docker compose …` in the second instance's directory
  therefore names that instance; before this it fell back to the live instance's names.
- **Networks are counted before the build.** One instance is 15 networks (14 of its own, each an
  isolation boundary, plus Preloop's), and Docker's default address pools hold about 31 — two
  instances fit, a third fails inside compose with "address pools fully subnetted".
  `install.sh --check` says how many are in use and how many this instance needs. For more than
  two instances, widen the daemon's pools (Docker Desktop: Settings → Docker Engine; Linux:
  `/etc/docker/daemon.json`) and restart Docker:

  ```json
  {"default-address-pools": [{"base": "10.200.0.0/16", "size": 24}]}
  ```

  That is 256 networks of 254 addresses each. Fewer networks per instance is not the remedy:
  each one is a boundary something was measured against.

## Addresses

| | |
|---|---|
| panel | `http://127.0.0.1:8780` |
| ops API (what the panel calls) | `http://127.0.0.1:8781` |
| MLflow | `http://127.0.0.1:5000` |
| Preloop console | `http://localhost:3000` |
