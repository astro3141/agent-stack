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

WORKDIR /work
CMD ["sleep", "infinity"]
