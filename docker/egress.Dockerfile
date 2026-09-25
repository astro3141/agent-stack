# #281 option B egress proxy (allowlist). Dual-homed on purpose: governed (where the agent is)
# and egressnet (internet). It is the only such member for model traffic; it runs no other service.
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends tinyproxy \
    && rm -rf /var/lib/apt/lists/*
COPY egress/tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY egress/allow /etc/tinyproxy/allow
# One proxy per role that declares its own hosts, beside the shared one (OPERATIONS §48).
COPY egress/start.sh /usr/local/bin/start.sh
RUN chmod 0755 /usr/local/bin/start.sh
EXPOSE 8888
CMD ["/usr/local/bin/start.sh"]
