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
      curl ca-certificates git jq procps iproute2 dnsutils \
    && rm -rf /var/lib/apt/lists/*

# This host runs Kaspersky, which terminates TLS for claude.ai with its own root CA.
# That root is trusted by Windows but not by the container, so curl fails with exit 60
# without it. Recorded as a host-environment fact in FINDINGS.md (F10), not hidden.
COPY ca/kaspersky-root.crt /usr/local/share/ca-certificates/kaspersky-root.crt
RUN update-ca-certificates

RUN useradd -m -u 1000 -s /bin/bash agent
USER agent
# Python/requests-based tools read their own bundle; point them at the system store.
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt     SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV HOME=/home/agent \
    PATH=/home/agent/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

# Claude Code (agent runtime). Installs to $HOME/.local/bin.
RUN curl -fsSL https://claude.ai/install.sh | bash

# uv + Conductor with the extras this PoC needs.
RUN pip install --no-cache-dir --user uv
RUN uv tool install 'conductor-cli[telemetry,claude-agent-sdk] @ git+https://github.com/microsoft/conductor.git'

# Preloop CLI, so onboarding happens INSIDE the container and never touches the host.
RUN curl -fsSL https://preloop.ai/install/cli -o /tmp/preloop-cli.sh \
    && INSTALL_DIR=/home/agent/.local/bin sh /tmp/preloop-cli.sh < /dev/null || true
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
RUN python -m venv /opt/venv     && /opt/venv/bin/pip install --no-cache-dir -q pytest 'sympy==1.14.0'     && chmod -R a+rX /opt/venv
USER agent

# ---- #281: common agent execution layer -------------------------------------------------
# Everything lives under /opt, never $HOME: $HOME is a volume, and a tool baked under it would
# be pinned to the image as it was when the volume was first created (measured in #280).
#
# Versions are pinned. acpx's built-in profiles would otherwise run `npx -y <adapter>` at
# launch, which cannot work here: the governed runtime has no egress. Adapters are installed
# ahead of time and invoked by path.
USER root
ARG NODE_VERSION=22.14.0
RUN curl -fsSL https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.gz       | tar -xz -C /opt     && ln -s /opt/node-v${NODE_VERSION}-linux-x64 /opt/node
ENV PATH=/opt/node/bin:/opt/npm-global/bin:/opt/codexbar:$PATH     NPM_CONFIG_PREFIX=/opt/npm-global
RUN npm install -g --no-fund --no-audit       acpx@0.18.0       @agentclientprotocol/claude-agent-acp@0.79.0       @agentclientprotocol/codex-acp@1.12.0       @openai/codex@0.155.1       @xai-official/grok@1.0.40     && chmod -R a+rX /opt/npm-global
# CodexBar CLI (quota observation). Static musl build: the glibc build needs GLIBC_2.38, bookworm has 2.36. No Windows build exists.
ARG CODEXBAR_VERSION=0.63.0
RUN mkdir -p /opt/codexbar     && curl -fsSL -o /tmp/cb.tgz https://github.com/steipete/CodexBar/releases/download/v${CODEXBAR_VERSION}/CodexBarCLI-v${CODEXBAR_VERSION}-linux-musl-x86_64.tar.gz     && curl -fsSL -o /tmp/cb.sha https://github.com/steipete/CodexBar/releases/download/v${CODEXBAR_VERSION}/CodexBarCLI-v${CODEXBAR_VERSION}-linux-musl-x86_64.tar.gz.sha256     && (cd /tmp && echo "$(awk '{print $1}' cb.sha)  cb.tgz" | sha256sum -c -)     && tar -xzf /tmp/cb.tgz -C /opt/codexbar     && rm -f /tmp/cb.tgz /tmp/cb.sha     && chmod -R a+rX /opt/codexbar
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
