#!/bin/sh
# 静澜 Stillwave · QA 总入口（可重复运行）
# 用法: ./qa/run_all.sh --phase full --round 1
#       ./qa/run_all.sh --phase preflight --round 1
#       ./qa/run_all.sh --phase full --round 2 --only browser
set -u
PY="/opt/homebrew/opt/python@3.9/bin/python3.9"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3)"
fi
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$PY" "$HERE/run_all.py" "$@"
