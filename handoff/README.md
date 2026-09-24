# Hand-in

Data that arrives from outside a run goes here, by **file name**.

Run inputs are letters, digits, dot, underscore, hyphen and space — arguments reach Conductor as an
argv list and are never shell-interpreted — so a path cannot be an input. A step that takes data
from outside resolves a *name* inside this directory and refuses anything that escapes it:

```bash
cp acyc-2026-04-10.json handoff/
run_workflow.py start r1 trading-port research-default mode=live packet_from=acyc-2026-04-10.json
```

Fixtures that belong to a workflow travel inside its package (`packages/<name>/fixtures/`). This
directory is for what a person or another system hands in for one run — a frozen packet, a dataset,
a file to work on. Its contents are not versioned.
