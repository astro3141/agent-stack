"""Workflow packages: a workflow that arrives as a directory, not as an edit to this stack.

usage:
  packages.py list [--json]        what is installed, and whether each one is usable
  packages.py show <name>          one package's manifest, resolved

A workflow used to be three things at once: a file under `p281/workflows/`, steps and prompts
scattered through `p281/`, and its name written into a list inside `run_workflow.py` and another
inside `ops/server.py`. That meant a workflow could not be *given* to anyone: installing one was
editing the platform, which is the thing CONTRACT.md says a workflow must never have to do.

A package is a directory under `/work/packages/` (`workflows/` is the older probe
tree from #278 and is left alone):

    packages/<name>/
      manifest.yaml     name, version, entry, and what it needs of the stack
      workflow.yaml     the graph (its steps by absolute path, /work/packages/<name>/steps/…)
      steps/ prompts/ fixtures/ cases/
      principals.yaml   the identities its steps run as, in the shape of config/principals.yaml

Nothing here interprets the workflow. This module answers three questions and no others: what is
installed, where is its entry point, and what does it declare that the stack must set up. The
graph, the steps and the meaning stay the package's own.
"""
import json, os, re, sys

ROOT = os.environ.get("P281_PACKAGES", "/work/packages")
NAME = re.compile(r"[a-z][a-z0-9-]{1,39}")


def _yaml(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _read(directory):
    """One package, with the reason it is unusable rather than an exception."""
    name = os.path.basename(directory.rstrip("/"))
    out = {"name": name, "root": directory, "usable": False, "why": ""}
    manifest_path = os.path.join(directory, "manifest.yaml")
    if not os.path.isfile(manifest_path):
        out["why"] = "no manifest.yaml"
        return out
    try:
        m = _yaml(manifest_path)
    except Exception as e:
        out["why"] = f"manifest.yaml is not readable: {type(e).__name__}"
        return out
    declared = str(m.get("name") or "")
    if declared and declared != name:
        out["why"] = f"manifest says {declared!r} but the directory is {name!r}"
        return out
    if not NAME.fullmatch(name):
        out["why"] = "a package name is [a-z][a-z0-9-] of 2 to 40"
        return out
    entry = str(m.get("entry") or "workflow.yaml")
    entry_path = os.path.normpath(os.path.join(directory, entry))
    if not entry_path.startswith(os.path.normpath(directory) + os.sep):
        out["why"] = "entry points outside the package"
        return out
    if not os.path.isfile(entry_path):
        out["why"] = f"entry {entry!r} is not there"
        return out
    out.update(usable=True, entry=entry_path, version=str(m.get("version") or ""),
               description=str(m.get("description") or ""),
               requires=(m.get("requires") or {}),
               principals_file=(os.path.join(directory, "principals.yaml")
                                if os.path.isfile(os.path.join(directory, "principals.yaml")) else ""))
    return out


def installed():
    """Every package directory under the packages root, usable or not, by name."""
    if not os.path.isdir(ROOT):
        return {}
    out = {}
    for entry in sorted(os.listdir(ROOT)):
        d = os.path.join(ROOT, entry)
        if os.path.isdir(d) and not entry.startswith("."):
            out[entry] = _read(d)
    return out


def workflows():
    """{name: path relative to /work} for every usable package — what a runner may start."""
    return {n: os.path.relpath(p["entry"], "/work")
            for n, p in installed().items() if p["usable"]}


def principals():
    """Every principal the installed packages declare, with the package that declared it.

    A name declared twice, differently, is reported rather than merged: two workflows quietly
    sharing an identity is the kind of thing that is discovered later, as rights nobody meant.
    """
    out, conflicts = {}, []
    for name, p in sorted(installed().items()):
        if not (p["usable"] and p["principals_file"]):
            continue
        try:
            declared = (_yaml(p["principals_file"]) or {}).get("principals") or {}
        except Exception:
            conflicts.append({"package": name, "why": "principals.yaml is not readable"})
            continue
        for who, spec in declared.items():
            if who in out and out[who]["spec"] != spec:
                conflicts.append({"principal": who, "declared_by": [out[who]["package"], name]})
                continue
            out[who] = {"package": name, "spec": spec}
    return out, conflicts


def _print(rows):
    if not rows:
        print(f"no packages under {ROOT}")
        return
    for name, p in rows.items():
        if p["usable"]:
            print(f"{name:<20} {p.get('version') or '-':<8} {os.path.relpath(p['entry'], '/work')}"
                  + ("  + principals" if p["principals_file"] else ""))
        else:
            print(f"{name:<20} {'-':<8} UNUSABLE: {p['why']}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["show"] and len(a) > 1:
        print(json.dumps(installed().get(a[1], {"name": a[1], "usable": False,
                                                "why": "not installed"}), ensure_ascii=False))
        sys.exit(0)
    rows = installed()
    if "--json" in a:
        who, conflicts = principals()
        print(json.dumps({"packages": rows, "principals": who, "conflicts": conflicts},
                         ensure_ascii=False))
        sys.exit(0)
    _print(rows)
    _, conflicts = principals()
    for c in conflicts:
        print(f"  conflict: {json.dumps(c, ensure_ascii=False)}")
    sys.exit(0)
