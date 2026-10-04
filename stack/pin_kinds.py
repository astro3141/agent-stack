"""What each control pins: a behaviour, or the text of a source file.

usage: pin_kinds.py [--list] [stack/review_controls.py stack/trial_controls.py]

A control that reads a file of this repository — a module, a script, a page, a document — and
asks whether a phrase is in it pins a decision as text. Some decisions are only text (a button
that must not exist, a document that must say a thing); for a behaviour, a text pin stands in for
the check that would run it. The third review said so (OPERATIONS §82), and this is the count the
record keeps: `source-text` is the number to bring down, `absence` the kind that is right as text.

A check is counted as `source-text` when its condition reads a repository file: a variable bound
to `<WORK|HERE|/work/...>.read_text()` / `open("/work/...").read()`, or such a read inline. A file
the control wrote itself under a temporary directory is behaviour, not text.

A check is a `check(name, …)` call — the stack's own shape — or an `assert` statement, which is how
a package may write its controls (novel-v2's read `checks: 0` before this, §98); an assert's name
is its message when it has one, else its test. A controls file whose helper has another name says
so on a line of its own, and the tool reads that name like `check` (§99):

    # pin_kinds: check=ok            one or more names, comma-separated

Nothing is guessed from a call's shape: a helper the file does not declare is not a check to this
tool, and the count says `checks: 0`.
"""
import ast, json, re, sys
from collections import Counter
from pathlib import Path

SOURCE = re.compile(r'(WORK|HERE)\s*/|"/work/|/work/stack')
DECLARED = re.compile(r"^\s*#\s*pin_kinds:\s*check\s*=\s*([A-Za-z_][\w, ]*)", re.M)


def check_names(src):
    """`check`, plus whatever the file declares as its own helper (`# pin_kinds: check=ok,expect`)."""
    names = {"check"}
    for m in DECLARED.finditer(src):
        names |= {n.strip() for n in m.group(1).split(",") if n.strip()}
    return names


def classify(path):
    src = Path(path).read_text()
    tree = ast.parse(src)
    names = check_names(src)

    def text_vars_in(node):
        """Variables of this scope bound to a repository file's text."""
        out = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                seg = ast.get_source_segment(src, n.value) or ""
                if (".read_text()" in seg or seg.endswith(".read()")) and SOURCE.search(seg):
                    out.add(n.targets[0].id)
        return out

    rows = []

    def kind_of(cond, text_vars):
        inline = (".read_text()" in cond or ".read()" in cond) and bool(SOURCE.search(cond))
        byvar = any(re.search(rf"\b{v}\b", cond) for v in text_vars)
        if not (inline or byvar):
            return "behaviour"
        tests = re.findall(r"\b(not in|in)\b", cond)
        return "absence" if tests and all(t == "not in" for t in tests) else "source-text"

    def checks_in(node, text_vars):
        for n in ast.walk(node):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") in names and n.args and isinstance(n.args[0], ast.Constant):
                name = str(n.args[0].value)
                cond = ast.get_source_segment(src, n.args[1]) if len(n.args) > 1 else ""
            elif isinstance(n, ast.Assert):
                cond = ast.get_source_segment(src, n.test) or ""
                name = (str(n.msg.value) if isinstance(n.msg, ast.Constant) else cond)[:120]
            else:
                continue
            rows.append({"kind": kind_of(cond, text_vars), "name": name, "line": n.lineno})

    # scoped: a name like `c` or `doc` is a file's text only inside the function that read it
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    for fn in funcs:
        checks_in(fn, text_vars_in(fn))
    module_only = ast.Module(body=[n for n in tree.body if not isinstance(n, ast.FunctionDef)], type_ignores=[])
    checks_in(module_only, text_vars_in(module_only))
    rows.sort(key=lambda r: r["line"])
    return rows


def main(argv):
    files = [a for a in argv if not a.startswith("--")] or ["stack/review_controls.py", "stack/trial_controls.py"]
    out = {}
    for f in files:
        rows = classify(f)
        out[f] = {"checks": len(rows), **Counter(r["kind"] for r in rows)}
        if "--list" in argv:
            for r in rows:
                if r["kind"] != "behaviour":
                    print(f"{r['kind']:11} {f}:{r['line']}  {r['name']}")
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
