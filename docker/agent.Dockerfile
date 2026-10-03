# Governed runtime for the #278 PoC.
#
# Contains Conductor (workflow authority) and Claude Code (agent runtime) in one
# workload. Per the review: they share a container for reproducibility and to keep
# instrument wiring simple, NOT because a container boundary would make distributed
# tracing impossible (W3C traceparent propagation crosses process boundaries fine).
#
# This image deliberately contains NO Anthropic credential. Credentials are minted
# inside the container at provisioning time and live only in the agent-home volume.
#
# Every tool lives under /opt, in the image (#34, OPERATIONS §76). /home/agent is a volume, and a
# volume is filled from the image once, when it is empty: a tool installed under $HOME would be
# pinned to the image as it was the first time the volume was made, and later pins would silently
# not apply (measured in #280, and again on update days 1 and 2, §65 §73). The image is the
# toolchain; a release is a revision plus image ids plus configuration (scripts/release.sh).
FROM python:3.13-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates git jq procps iproute2 dnsutils sudo bubblewrap \
    && rm -rf /var/lib/apt/lists/*

# This host runs Kaspersky, which terminates TLS for claude.ai with its own root CA.
# That root is trusted by Windows but not by the container, so curl fails with exit 60
# without it. Recorded as a host-environment fact in FINDINGS.md (F10), not hidden.
COPY ca/kaspersky-root.crt /usr/local/share/ca-certificates/kaspersky-root.crt
RUN update-ca-certificates

RUN useradd -m -u 1000 -s /bin/bash agent && groupadd -g 1099 roles && usermod -aG roles agent
# bubblewrap is here for the same reason: the Codex CLI builds its own sandbox, and when it runs as a
# role rather than as the user that installed it, it asks for bubblewrap by name and exits 1 without
# it (measured). Installing it is what lets a model step run as its role at all — and it is a
# sandbox, so the step ends up more confined, not less.
#
# Per-role egress (OPERATIONS §48). A step runs as the role it belongs to, which is what keeps one
# role's proxy credential out of another role's reach — measured: /proc/<pid>/environ is readable at
# the same uid and Permission denied across uids. Dropping to a uid takes privilege, and this image
# deliberately does not run as root, so exactly one program may do it, only for the uids the
# platform assigns to roles, and never for root:
#
#   * role-exec runs as the role sudo switched to, reads that role's own credential (0600, owned by
#     it) and execs the step through the role's proxy.
#   * sudoers lets only `agent` become a member of the `roles` group, and only to run this one
#     program — never root, and never from a process that is already a role. Measured: agent to a
#     role is allowed, agent to root is refused, and one role to another is refused.
#
# The role users themselves are created at bring-up (scripts/up.sh), because which roles exist is
# declared, not baked.
COPY --chown=root:root agent/role-exec /usr/local/bin/role-exec
RUN chmod 0755 /usr/local/bin/role-exec \
 && printf '%s\n' 'Cmnd_Alias ROLE_EXEC = /usr/local/bin/role-exec' \
      '# the step keeps its own PATH: sudo replaces it with secure_path otherwise, and the node the' \
      '# adapter runs is not on it (measured: FileNotFoundError: node)' \
      'Defaults!ROLE_EXEC !secure_path' \
      'agent ALL=(%roles) NOPASSWD:SETENV: ROLE_EXEC' > /etc/sudoers.d/role-exec \
 && chmod 0440 /etc/sudoers.d/role-exec \
 && visudo -c -f /etc/sudoers.d/role-exec
# Python/requests-based tools read their own bundle; point them at the system store.
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt     SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
# The three tools below install as root under /opt and are read by everyone (a+rX): the agent, and
# the role users a step runs as. Nothing of them is under /home/agent. DISABLE_AUTOUPDATER: the
# pin is the version, and /opt is not writable by the user that runs claude anyway.
ENV HOME=/home/agent \
    PATH=/opt/claude/.local/bin:/opt/uv/bin:/opt/preloop/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DISABLE_AUTOUPDATER=1

# Claude Code (agent runtime). Its installer writes to $HOME/.local, so it is given /opt/claude as
# its home for the install: /opt/claude/.local/bin/claude -> /opt/claude/.local/share/claude/versions/<v>.
# Pinned to the version in use (OPERATIONS.md §3). Unpinned, every rebuild drifts: a candidate
# build on 2026-09-23 pulled Claude 2.1.280, Conductor 0.1.39 and Preloop CLI 0.16.0.
ARG CLAUDE_CODE_VERSION=2.1.287
RUN mkdir -p /opt/claude && HOME=/opt/claude bash -c 'curl -fsSL https://claude.ai/install.sh | bash -s ${CLAUDE_CODE_VERSION}' \
    && test -x /opt/claude/.local/bin/claude && chmod -R a+rX /opt/claude

# uv + Conductor with the extras this PoC needs. uv's tool directory and its bin are under /opt
# too (UV_TOOL_DIR, UV_TOOL_BIN_DIR); the venv it makes is /opt/uv/tools/conductor-cli. HOME is
# root's for these two steps: whatever they write beside /opt must not land in /home/agent.
RUN HOME=/root pip install --no-cache-dir --prefix=/opt/uv uv && test -x /opt/uv/bin/uv
# v0.1.41 (2026-09-29): run bundles, secrets bindings on script steps; OPERATIONS §72, #17
ARG CONDUCTOR_COMMIT=11dcc41ed3df78f0806127cc901822fe8758294b
RUN HOME=/root UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/opt/uv/bin \
      uv tool install --no-cache "conductor-cli[telemetry,claude-agent-sdk] @ git+https://github.com/microsoft/conductor.git@${CONDUCTOR_COMMIT}" \
    && test -x /opt/uv/bin/conductor && test -x /opt/uv/tools/conductor-cli/bin/python && chmod -R a+rX /opt/uv

# Preloop CLI, so onboarding happens INSIDE the container and never touches the host. Its installer
# also onboards the agents it finds under $HOME and writes ~/.preloop/config.yaml there — that is
# the agent's home, so this step runs as the agent, as it always did; run as root it left the file
# root-owned and the claim of a fresh instance failed (cold-start run 55, §76). Only the binary's
# directory is handed to root afterwards.
RUN mkdir -p /opt/preloop/bin && chown agent:agent /opt/preloop/bin
USER agent
ARG PRELOOP_CLI_VERSION=0.15.0
RUN curl -fsSL https://preloop.ai/install/cli -o /tmp/preloop-cli.sh \
    && PRELOOP_VERSION=${PRELOOP_CLI_VERSION} INSTALL_DIR=/opt/preloop/bin \
       sh /tmp/preloop-cli.sh < /dev/null || true
USER root
RUN test -x /opt/preloop/bin/preloop && chown -R root:root /opt/preloop && chmod -R a+rX /opt/preloop
# The volume is seeded from /home/agent as it is here, so nothing in it may belong to anyone but
# the agent — the build says so, rather than a fresh instance finding out.
RUN test -z "$(find /home/agent ! -user agent)"
USER agent

# Linux-side virtualenv for the fixture's pytest (the host .venv is a Windows venv).
# Verification venv lives OUTSIDE $HOME on purpose. $HOME is a named volume, and Docker
# only seeds a volume from the image while the volume is empty — a venv under $HOME is
# therefore pinned to whatever the image looked like the first time the volume was made,
# and later image changes silently do not apply. Measured: adding sympy to the image had
# no effect until the venv moved here.
#
# sympy must be baked in at all: the governed runtime has no egress, so installing it at
# run time fails by design.
USER root
RUN python -m venv /opt/venv     && /opt/venv/bin/pip install --no-cache-dir -q pytest 'sympy==1.14.0' 'PyYAML==6.0.2' 'pydantic>=2,<3' 'httpx>=0.27,<1'     && chmod -R a+rX /opt/venv
# pydantic/httpx: declared by the trading package (requires.python, OPERATIONS §62) — C
# extensions cannot travel inside a package directory, so they live here, added by the operator.
USER agent

# ---- #281: common agent execution layer -------------------------------------------------
# Everything lives under /opt, never $HOME: $HOME is a volume, and a tool baked under it would
# be pinned to the image as it was when the volume was first created (measured in #280).
#
# Versions are pinned. acpx's built-in profiles would otherwise run `npx -y <adapter>` at
# launch, which cannot work here: the governed runtime has no egress. Adapters are installed
# ahead of time and invoked by path.
USER root
ARG TARGETARCH
ARG NODE_VERSION=22.14.0
# TARGETARCH is set by BuildKit; uname is the fallback for a build without it. These two downloads
# were the only thing tying this image to x86_64 — every image the stack pulls is multi-arch.
# arm64 is parameterized here and has not been built or run: see OPERATIONS §25.
RUN arch="${TARGETARCH:-$(uname -m)}"; \
    case "$arch" in \
      amd64|x86_64) node_arch=x64;; \
      arm64|aarch64) node_arch=arm64;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1;; \
    esac; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${node_arch}.tar.gz" \
      | tar -xz -C /opt \
    && ln -s "/opt/node-v${NODE_VERSION}-linux-${node_arch}" /opt/node
ENV PATH=/opt/node/bin:/opt/npm-global/bin:/opt/codexbar:$PATH     NPM_CONFIG_PREFIX=/opt/npm-global
RUN npm install -g --no-fund --no-audit       acpx@0.19.4       @agentclientprotocol/claude-agent-acp@0.85.1       @agentclientprotocol/codex-acp@2.1.1       @openai/codex@0.160.0       @xai-official/grok@1.0.46     && chmod -R a+rX /opt/npm-global
# CodexBar CLI (quota observation). Static musl build: the glibc build needs GLIBC_2.38, bookworm has 2.36. No Windows build exists.
ARG CODEXBAR_VERSION=0.70.0
RUN arch="${TARGETARCH:-$(uname -m)}"; \
    case "$arch" in \
      amd64|x86_64) cb_arch=x86_64;; \
      arm64|aarch64) cb_arch=aarch64;; \
      *) echo "unsupported architecture: $arch" >&2; exit 1;; \
    esac; \
    base="https://github.com/steipete/CodexBar/releases/download/v${CODEXBAR_VERSION}/CodexBarCLI-v${CODEXBAR_VERSION}-linux-musl-${cb_arch}.tar.gz"; \
    mkdir -p /opt/codexbar \
    && curl -fsSL -o /tmp/cb.tgz "$base" \
    && curl -fsSL -o /tmp/cb.sha "${base}.sha256" \
    && (cd /tmp && echo "$(awk '{print $1}' cb.sha)  cb.tgz" | sha256sum -c -) \
    && tar -xzf /tmp/cb.tgz -C /opt/codexbar \
    && rm -f /tmp/cb.tgz /tmp/cb.sha \
    && chmod -R a+rX /opt/codexbar
# #281 option B: /ws is the workspace shared with the filesystem MCP container. Created here
# so the named volume is seeded agent-owned. (Native-tool removal is per run, in the
# workspace's project settings — not managed settings, which would also strip Write/Bash
# from the #278 and #280 workflows running in this same container.)
# /obs (quota observations) and /route (routing-layer logins) likewise, so fresh volumes start
# agent-owned and nothing needs a manual chown after a recreate.
RUN mkdir -p /ws /obs /route && chown agent:agent /ws /obs /route && chmod 700 /route
USER agent

WORKDIR /work
CMD ["sleep", "infinity"]
