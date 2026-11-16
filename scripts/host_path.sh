# A bind source as Docker Desktop reports it, turned back into the host's path (OPERATIONS §94,
# §118 — one copy, sourced by release.sh, backup.sh and restore.sh; three copies drifted: the
# macOS form reached release.sh on the first Mac host and never the other two, and every backup
# after an update on a Mac failed with every host path MISSING, #113).
#
#   Windows Docker Desktop   /run/desktop/mnt/host/d/Work/x  or  /host_mnt/d/Work/x   →  D:/Work/x
#   macOS Docker Desktop     /host_mnt/Users/astro/x                                  →  /Users/astro/x
#   Linux, or a host path    /home/user/x  or  D:/Work/x                               →  as it is
norm_host() {
  case "$1" in
    /run/desktop/mnt/host/?/*|/host_mnt/?/*)
      p="${1#/run/desktop/mnt/host/}"; p="${p#/host_mnt/}"
      d="${p%%/*}"; printf '%s:/%s' "$(printf '%s' "$d" | tr 'a-z' 'A-Z')" "${p#*/}";;
    /host_mnt/*) printf '/%s' "${1#/host_mnt/}";;
    *) printf '%s' "$1";;
  esac
}
