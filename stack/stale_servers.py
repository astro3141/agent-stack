"""Which of the stack's servers started before the code they run changed (§103, #91; §117).
usage: stale_servers.py <stack dir> [--record FILE]  < lines of "<container> <StartedAt>"   → the stale ones, one per line
       stale_servers.py <stack dir> --write FILE     < the same lines                        → records what the servers run now
The broker and the profile runners run /work/stack/*.py as long-lived processes; a bring-up that
rebuilt no image leaves them on the code they started with — devflow measured half the path on
§102 and half before it, a brokered call COMPLETED with no schema. A server whose process started
before the newest Python file under the stack directory is stale: scripts/up.sh restarts it and
`up.sh --check` names it. StartedAt is docker's RFC 3339 with nanoseconds, read to the second.

The clock is a proxy for the content, and it lies once (§117): a `git checkout` of a revision
with the same files, a fast-forward, a copy — the content the servers run is the content in the
tree, and every file is newer than every server. So up.sh records a fingerprint of the files when
it starts or restarts the servers (`--write`), and a check that finds the tree's fingerprint equal
to the record (`--record`) names nobody, whatever the clocks say. Without a record, or with the
content changed, the clock rule is what there is.
"""
import calendar, hashlib, json, os, sys, time


def py_files(root):
    out = []
    for d, _, files in os.walk(root):
        for f in files:
            if f.endswith(".py"):
                out.append(os.path.join(d, f))
    return sorted(out)


def newest(root):
    m = 0.0
    for p in py_files(root):
        try:
            m = max(m, os.stat(p).st_mtime)
        except OSError:
            pass
    return m


def fingerprint(root):
    """One digest of every .py under root: relative path and bytes, in path order. Two trees with
    the same files have the same fingerprint whatever their modification times."""
    h = hashlib.sha256()
    for p in py_files(root):
        try:
            data = open(p, "rb").read()
        except OSError:
            continue
        rel = os.path.relpath(p, root).replace(os.sep, "/")
        h.update(rel.encode() + b"\0" + data + b"\0")
    return h.hexdigest()


def read_record(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("fingerprint"), str) else None
    except (OSError, ValueError):
        return None


def write_record(path, root, lines, now=None):
    names = [l.split()[0] for l in lines if l.split()]
    d = {"fingerprint": fingerprint(root), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now or time.time())),
         "servers": names}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, path)
    return d


def started(s):
    try:
        return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def stale(root, lines, record=None):
    """The stale servers. `record` is what up.sh wrote when it last started them (read_record):
    when its fingerprint is the tree's, nothing is stale — the content is the same, the clocks
    are not the question. Otherwise, or without one, a server that started before the newest
    .py is stale."""
    if record and record.get("fingerprint") == fingerprint(root):
        return []
    m = newest(root)
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        t = started(parts[1])
        if t is not None and t < m:
            out.append(parts[0])
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    root = a[0]
    lines = sys.stdin.read().splitlines()
    if "--write" in a:
        write_record(a[a.index("--write") + 1], root, lines)
        sys.exit(0)
    rec = read_record(a[a.index("--record") + 1]) if "--record" in a else None
    names = stale(root, lines, rec)
    if names:
        print("\n".join(names))
