"""Which of the stack's servers started before the code they run changed (§103, #91).

usage: stale_servers.py <stack dir>  < lines of "<container> <StartedAt>"     → the stale ones, one per line

The broker and the profile runners run /work/stack/*.py as long-lived processes; a bring-up that
rebuilt no image leaves them on the code they started with — devflow measured half the path on
§102 and half before it, a brokered call COMPLETED with no schema. A server whose process started
before the newest Python file under the stack directory is stale: scripts/up.sh restarts it and
`up.sh --check` names it. StartedAt is docker's RFC 3339 with nanoseconds, read to the second.
"""
import calendar, os, sys, time


def newest(root):
    m = 0.0
    for d, _, files in os.walk(root):
        for f in files:
            if f.endswith(".py"):
                try:
                    m = max(m, os.stat(os.path.join(d, f)).st_mtime)
                except OSError:
                    pass
    return m


def started(s):
    try:
        return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def stale(root, lines):
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
    names = stale(sys.argv[1], sys.stdin.read().splitlines())
    if names:
        print("\n".join(names))
