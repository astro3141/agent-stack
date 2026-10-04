# A host's own TLS root, for the build only

Empty on purpose. A host that intercepts TLS — an endpoint-security product with a root of its
own, which the first host had (FINDINGS-278 F10) — makes `curl https://claude.ai/install.sh` fail
inside the build with exit 60, because the container trusts the public roots and not that one.
Such a host puts its root here as `<name>.crt`; `docker/agent.Dockerfile` copies this directory
into the image's trust store and `update-ca-certificates` picks up every `.crt` in it.

`*.crt` is git-ignored: the root is that host's, and an image built elsewhere must not trust it.
Until OPERATIONS §86 one host's personal root was tracked here and baked into every image this
tree built, including the cold-start runner's.

`scripts/release.sh update` builds its candidate image from a clean worktree and copies whatever
`.crt` this directory holds into it first, so a host that needs one keeps updating.
