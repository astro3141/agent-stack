"""The examples in docs/packages.md, run: a documented contract nobody executes is a comment (#23).

usage: doc_examples.py [docs/packages.md]      prints one line per example and exits 1 on a problem

What is checked, and why each:
  * every ```yaml block parses, and with **no duplicate keys** — YAML keeps the last of two
    `requires:` silently, which is how the manifest example lost its `capabilities` for a while
    (OPERATIONS §67);
  * the manifest example (the block that starts with `name:`) is written to a temporary package
    directory and read by the same reader the stack uses (`packages.py`): it must be usable, its
    `requires` keys known, and every capability it names one the stack has a probe for;
  * every ```python block compiles.
"""
import os, re, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CAPABILITIES = ("tool_rights", "approvals", "egress", "record", "admission")


class Duplicate(Exception):
    pass


def _no_dup_loader():
    import yaml

    class L(yaml.SafeLoader):
        pass

    def construct(loader, node, deep=False):
        seen = set()
        for k_node, _ in node.value:
            k = loader.construct_object(k_node, deep=deep)
            if k in seen:
                raise Duplicate(f"duplicate key {k!r} at line {k_node.start_mark.line + 1}")
            seen.add(k)
        return yaml.SafeLoader.construct_mapping(loader, node, deep)

    L.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct)
    return L


def blocks(text):
    """[(kind, line, body)] for every fenced yaml/python block."""
    return [(m.group(1), text[:m.start()].count("\n") + 1, m.group(2))
            for m in re.finditer(r"```(yaml|python)\n(.*?)```", text, re.S)]


def check(path):
    """[(line, kind, verdict)] — verdict "ok …" or "FAIL …"."""
    import yaml
    text = open(path, encoding="utf-8").read()
    out = []
    for kind, line, body in blocks(text):
        if kind == "python":
            try:
                compile(body, f"{path}:{line}", "exec")
                out.append((line, kind, "ok compiles"))
            except SyntaxError as e:
                out.append((line, kind, f"FAIL does not compile: {e}"))
            continue
        try:
            doc = yaml.load(body, Loader=_no_dup_loader())
        except Duplicate as e:
            out.append((line, kind, f"FAIL {e}")); continue
        except yaml.YAMLError as e:
            out.append((line, kind, f"FAIL not YAML: {str(e).splitlines()[0]}")); continue
        if isinstance(doc, dict) and "name" in doc and ("entry" in doc or "workflows" in doc):
            out.append((line, kind, manifest_verdict(body, doc)))
        else:
            out.append((line, kind, "ok parses, no duplicate keys"))
    return out


def manifest_verdict(body, doc):
    """The manifest example, read as a package by the stack's own reader."""
    import packages
    name = str(doc.get("name") or "")
    with tempfile.TemporaryDirectory(prefix="agentstack-doc-") as tmp:
        d = os.path.join(tmp, name)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "manifest.yaml"), "w", encoding="utf-8").write(body)
        for rel in list((doc.get("workflows") or {}).values()) or [doc.get("entry") or "workflow.yaml"]:
            fp = os.path.join(d, str(rel))
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, "w").write("name: example\nagents: []\n")
        if doc.get("runbook"):
            open(os.path.join(d, str(doc["runbook"])), "w").write("# runbook\n")
        r = packages._read(d)
    if not r.get("usable"):
        return f"FAIL the manifest example is not a usable package: {r.get('why')}"
    if r.get("unknown_requires"):
        return f"FAIL requires keys nothing reads: {r['unknown_requires']}"
    caps = (r.get("requires") or {}).get("capabilities") or []
    bad = [c for c in caps if c not in CAPABILITIES]
    if bad:
        return f"FAIL capabilities the stack has no probe for: {bad}"
    return f"ok a usable package ({name}), requires {sorted(r.get('requires') or {})}, capabilities {caps}"


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "docs", "packages.md")
    rows = check(path)
    for line, kind, v in rows:
        print(f"  {'FAIL' if v.startswith('FAIL') else 'ok  '}  {os.path.basename(path)}:{line} {kind}: {v[5:] if v.startswith('FAIL ') else v[3:]}")
    bad = [r for r in rows if r[2].startswith("FAIL")]
    print(f"{len(rows) - len(bad)}/{len(rows)} examples ok")
    sys.exit(1 if bad else 0)
