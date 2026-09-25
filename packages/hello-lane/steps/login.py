"""The example package's official login — a device flow with nothing behind it.

This is not a credential for anything. It exists so the mechanism in OPERATIONS §44 is measured
rather than described: a package declares `login:`, the panel drives it exactly the way it drives a
provider's login, and the credential is written **by this step**, into the login directory the
platform points it at, which the panel never reads.

What a real one does instead of printing its own code: ask the service to start a device flow, print
the verification URL and the user code the service returned, poll until the operator authorises, and
write whatever the service mints. The shape the platform needs is the same either way —

  print a URL and a code, ask for the code back, write the file the manifest names.

What a repeat of this step does (OPERATIONS §17): "guarded" — a login directory that already holds
the file is reported as connected and the flow is not started again.
"""
REPEATABLE = "guarded"
import json
import os
import sys
import time

HOME = os.environ.get("HELLO_LOGIN_DIR") or ""
TOKEN = "token.json"


def main():
    if not HOME:
        print("HELLO_LOGIN_DIR is not set: the platform points it at this login's directory")
        return 2
    path = os.path.join(HOME, TOKEN)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        print("already logged in")
        return 0
    code = "HELO-" + str(int(time.time()))[-4:]
    # what a service would have returned. The panel reads these two lines off the terminal, the same
    # way it reads a provider's.
    print("Open https://example.invalid/device to authorize this stack")
    print(f"Your code: {code}")
    print("Paste the code here to finish: ", end="", flush=True)
    got = (sys.stdin.readline() or "").strip()
    if got != code:
        print(f"\nthat code does not match the one issued")
        return 1
    with open(path, "w", encoding="utf-8", newline=chr(10)) as f:
        json.dump({"kind": "example", "issued_at": time.time()}, f)
    os.chmod(path, 0o600)
    print(f"\nsuccessfully logged in")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
