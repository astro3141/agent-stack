"""The parent's run id beside the one its child's step saw (stack/cases/child-run.yaml, #13).

usage: report_child.py <child's reported path> <waited_seconds>

hello-lane's step writes <workspace_root>/<run id>/hello.txt, so the directory above the file is
the run id the child ran under. Reported, not judged: whether the two ids should be the same is
the measurement this fixture exists to take, and the answer goes in docs/packages.md.
"""
REPEATABLE = "yes"   # reads two arguments and says what they are
import os
import sys

sys.path.insert(0, "/work/stack/steps")
import step


def main():
    child_path = sys.argv[1] if len(sys.argv) > 1 else ""
    waited = sys.argv[2] if len(sys.argv) > 2 else ""
    parent = step.run_id()
    child = os.path.basename(os.path.dirname(child_path)) if child_path else ""
    step.out(parent_run=parent, child_run=child, same_run="yes" if parent == child else "no",
             waited_seconds=waited)


step.main(main, parent_run="", child_run="", same_run="", waited_seconds="")
