# This instance's own OS packages (OPERATIONS §113)

`docker/apt/apt.local` — git-ignored, absent on a fresh clone, beside `docker/python/python.local`
and `docker/egress/allow.local` — is the operator's list of Debian packages that only this
instance's packages need in the agent image: one per line, `name` or `name=version`, comments
after `#`. `scripts/up.sh` reads it before any build (a line that is not a package name fails
the bring-up, and `--check` says so), the image build installs the lines after the stack's own,
and what the image ended with is left in `/opt/apt/installed.txt` for the release record
(`apt.installed`). A release keeps the file as a member and a rollback restores it, absence
included; a backup carries it.

The stack's own packages do not go here: they are the toolchain's and stay in
`docker/agent.Dockerfile` (`poppler-utils` for the CLI's PDF reading, §112, among them). A package
names what it needs in its manifest (`requires: {apt: [tesseract-ocr]}`) and
`scripts/packages.py apt` prints the lines to copy here — it installs nothing.
