---
name: Package feedback
about: Something a package author found while writing, moving or running a package on this stack
title: "[package: <name>] "
labels: package-feedback
---

<!-- One finding per issue. Measured, not described: the command, what came back, what you expected.
     A sentence you had to work out from the stack's source is a defect of docs/packages.md;
     a thing the stack made you build around is a candidate for the stack (CONTRACT.md). -->

**Package and commit.** `<name>` @ `<commit>` (`requires.stack.min`: `<floor>`)

**Stack revision.** `<commit of this repository the instance runs>` (`scripts/release.sh list`, or `git rev-parse --short HEAD`)

**What you did.** The command, as run:

```
scripts/cycle.sh <workflow> <profile> key=value
```

**What happened.** The run id, the last line of the step's output, the record (MLflow run or `run_workflow.py show <id>`), the controls' output — whichever says it.

**What you expected,** and **which document you had read** when it surprised you (page and section).

**Where you think it belongs.** One of: the stack (which capability) · docs/packages.md (which sentence) · the package (what you changed, if you already did).
