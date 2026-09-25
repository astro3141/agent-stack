# Governed runtime for the #278 PoC.
#
# Contains Conductor (workflow authority) and Claude Code (agent runtime) in one
# workload. Per the review: they share a container for reproducibility and to keep
# instrument wiring simple, NOT because a container boundary would make distributed
# tracing impossible (W3C traceparent propagation crosses process boundaries fine).
#
# This image deliberately contains NO Anthropic credential. Credentials are minted
# inside the container at provisioning time and live only in the agent-home volume.
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
USER agent
# Python/requests-based tools read their own bundle; point them at the system store.
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt     SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV HOME=/home/agent \
    PATH=/home/agent/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

# Claude Code (agent runtime). Installs to $HOME/.local/bin.
# Pinned to the version in use (OPERATIONS.md §3). Unpinned, every rebuild drifts: a candidate
# build on 2026-09-23 pulled Claude 2.1.280, Conductor 0.1.39 and Preloop CLI 0.16.0.
ARG CLAUDE_CODE_VERSION=2.1.278
RUN curl -fsSL https://claude.ai/install.sh | bash -s ${CLAUDE_CODE_VERSION}

# uv + Conductor with the extras this PoC needs.
RUN pip install --no-cache-dir --user uv
ARG CONDUCTOR_COMMIT=87f7788e60c7cbb8895832b9edfb4e63f3924590
RUN uv tool install "conductor-cli[telemetry,claude-agent-sdk] @ git+https://github.com/microsoft/conductor.git@${CONDUCTOR_COMMIT}"

# Preloop CLI, so onboarding happens INSIDE the container and never touches the host.
ARG PRELOOP_CLI_VERSION=0.15.0
RUN curl -fsSL https://preloop.ai/install/cli -o /tmp/preloop-cli.sh \
    && PRELOOP_VERSION=${PRELOOP_CLI_VERSION} INSTALL_DIR=/home/agent/.local/bin \
       sh /tmp/preloop-cli.sh < /dev/null || true
RUN test -x /home/agent/.local/bin/preloop

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
RUN python -m venv /opt/venv     && /opt/venv/bin/pip install --no-cache-dir -q pytest 'sympy==1.14.0' 'PyYAML==6.0.2'     && chmod -R a+rX /opt/venv
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
RUN npm install -g --no-fund --no-audit       acpx@0.18.0       @agentclientprotocol/claude-agent-acp@0.79.0       @agentclientprotocol/codex-acp@1.12.0       @openai/codex@0.155.1       @xai-official/grok@1.0.40     && chmod -R a+rX /opt/npm-global
# CodexBar CLI (quota observation). Static musl build: the glibc build needs GLIBC_2.38, bookworm has 2.36. No Windows build exists.
ARG CODEXBAR_VERSION=0.63.0
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
