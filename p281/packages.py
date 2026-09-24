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
DECL = os.environ.get("P281_PACKAGES_YAML", "/work/config/packages.yaml")
# Declarations this instance adds and this repository does not carry: a package in a private
# repository, a client's workflow, anything a clone of this repository could not fetch. Same shape,
# git-ignored, merged over the tracked file — so the tracked one stays a declaration a stranger can
# actually run (docs/packages.md).
LOCAL_DECL = os.environ.get("P281_PACKAGES_LOCAL", "/work/config/packages.local.yaml")
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
    # A package carries one workflow (`entry`) or several (`workflows: {name: file}`). Several is
    # not a convenience: three trading workflows share one deterministic step, and splitting them
    # into three packages would mean three copies of it or a dependency between packages
    # (OPERATIONS §30).
    declared_wf = m.get("workflows") or {}
    if declared_wf:
        entries = {str(k): str(v) for k, v in declared_wf.items()}
    else:
        entries = {name: str(m.get("entry") or "workflow.yaml")}
    resolved = {}
    for wf_name, rel in entries.items():
        if not NAME.fullmatch(wf_name):
            out["why"] = f"workflow name {wf_name!r} is [a-z][a-z0-9-] of 2 to 40"
            return out
        path = os.path.normpath(os.path.join(directory, rel))
        if not path.startswith(os.path.normpath(directory) + os.sep):
            out["why"] = f"{wf_name}: the file points outside the package"
            return out
        if not os.path.isfile(path):
            out["why"] = f"{wf_name}: {rel!r} is not there"
            return out
        resolved[wf_name] = path
    out.update(usable=True, entry=resolved.get(name) or sorted(resolved.values())[0],
               entries=resolved, version=str(m.get("version") or ""),
               description=str(m.get("description") or ""),
               requires=(m.get("requires") or {}),
               principals_file=(os.path.join(directory, "principals.yaml")
                                if os.path.isfile(os.path.join(directory, "principals.yaml")) else ""))
    return out


def declared():
    """The package names this instance declares (config/packages.yaml).

    Installing a package is a decision to trust it: scripts/up.sh creates the principals it
    declares and mints their credentials (OPERATIONS §27). Until this was read here, that decision
    was made by a *directory existing* — anything dropped under packages/ was loaded, offered in
    the panel and given identities, and the declaration was a note the loader never read. Removing
    a package from config/packages.yaml did not remove it from the running stack.
    """
    out = set()
    for path in (DECL, LOCAL_DECL):
        try:
            out |= {str(k) for k in ((_yaml(path) or {}).get("packages") or {})}
        except Exception:
            pass              # unreadable or absent: it declares nothing, and every row says so
    return out


def installed():
    """Every package directory under the packages root, usable or not, by name."""
    if not os.path.isdir(ROOT):
        return {}
    known, out = declared(), {}
    for entry in sorted(os.listdir(ROOT)):
        d = os.path.join(ROOT, entry)
        if os.path.isdir(d) and not entry.startswith("."):
            row = _read(d)
            if entry not in known:
                # on disk and nobody asked for it: not loaded, and the reason is the answer
                row["usable"], row["declared"] = False, False
                row["why"] = ("not declared in config/packages.yaml — a package is loaded because "
                              "this instance asked for it, not because the directory is there "
                              "(scripts/packages.sh list)")
            else:
                row["declared"] = True
            out[entry] = row
    return out


def _carriers():
    """{workflow name: [(package, file), ...]} — who declares each name, across usable packages."""
    out = {}
    for name, p in sorted(installed().items()):
        if p["usable"]:
            for wf_name, path in (p.get("entries") or {}).items():
                out.setdefault(wf_name, []).append((p, path))
    return out


def workflows(with_conflicts=False):
    """{workflow name: path relative to /work} — every workflow exactly one usable package carries.

    A name two packages declare is carried by neither. It used to be resolved by accident of
    directory order — the file came from the package read last, the `requires` from the one read
    first — so a run could execute one package's workflow under another package's admission rules,
    and the caller had no way to see it had happened. Two packages wanting the same name is a
    thing to be told about, and the operator renames one (OPERATIONS §38).
    """
    out, conflicts = {}, []
    for wf_name, carriers in sorted(_carriers().items()):
        if len(carriers) > 1:
            conflicts.append({"workflow": wf_name,
                              "declared_by": [c[0]["name"] for c in carriers]})
            continue
        out[wf_name] = os.path.relpath(carriers[0][1], "/work")
    return (out, conflicts) if with_conflicts else out


def requires_of(workflow_name):
    """What the package carrying this workflow says it needs of the stack.

    A manifest that declares `requires.capabilities` and is read by nobody is a comment. The runner
    reads this and refuses a run the stack cannot govern the way that package expects — the same
    refusal a missing global capability gets (OPERATIONS §31).
    """
    carriers = _carriers().get(workflow_name) or []
    if len(carriers) != 1:         # unknown, or contested — workflows() offers neither
        return [], ""
    p = carriers[0][0]
    return list(((p.get("requires") or {}).get("capabilities")) or []), p["name"]


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
            wfs = ", ".join(sorted(p.get("entries") or {}))
            print(f"{name:<16} {p.get('version') or '-':<8} {wfs}"
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
    _, wf_conflicts = workflows(with_conflicts=True)
    if "--json" in a:
        who, conflicts = principals()
        print(json.dumps({"packages": rows, "principals": who,
                          "conflicts": conflicts + wf_conflicts}, ensure_ascii=False))
        sys.exit(0)
    _print(rows)
    _, conflicts = principals()
    for c in conflicts + wf_conflicts:
        print(f"  conflict: {json.dumps(c, ensure_ascii=False)}")
    sys.exit(0)
