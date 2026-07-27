#!/bin/sh
set -eu

: "${GUNICORN_WORKERS:=2}"
: "${GUNICORN_THREADS:=8}"
: "${GUNICORN_TIMEOUT:=120}"
: "${GUNICORN_BIND:=0.0.0.0:5000}"
: "${GUNICORN_ACCESS_LOGFILE:=-}"
: "${SCHEDULER_STANDALONE:=true}"

require_positive_int() {
  name="$1"
  value="$2"
  case "$value" in
    ''|*[!0-9]*)
      echo "$name must be a positive integer, got: $value" >&2
      exit 1
      ;;
  esac
  if [ "$value" -lt 1 ]; then
    echo "$name must be a positive integer, got: $value" >&2
    exit 1
  fi
}

require_positive_int GUNICORN_WORKERS "$GUNICORN_WORKERS"
require_positive_int GUNICORN_THREADS "$GUNICORN_THREADS"
require_positive_int GUNICORN_TIMEOUT "$GUNICORN_TIMEOUT"

normalize_bool() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

SCHEDULER_PID=""
GUNICORN_PID=""

is_standalone_scheduler() {
  case "$(normalize_bool "${SCHEDULER_STANDALONE}")" in
    true|1|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

cleanup_children() {
  status=0
  if [ -n "${GUNICORN_PID}" ] && kill -0 "${GUNICORN_PID}" 2>/dev/null; then
    kill -TERM "${GUNICORN_PID}" 2>/dev/null || true
    wait "${GUNICORN_PID}" 2>/dev/null || status=$?
  fi
  if [ -n "${SCHEDULER_PID}" ] && kill -0 "${SCHEDULER_PID}" 2>/dev/null; then
    kill -TERM "${SCHEDULER_PID}" 2>/dev/null || true
    wait "${SCHEDULER_PID}" 2>/dev/null || true
  fi
  return "${status}"
}

handle_signal() {
  cleanup_children || true
  exit 143
}

# Default: standalone APScheduler sibling + 2 Gunicorn workers (Issue #69).
# Set SCHEDULER_STANDALONE=false and GUNICORN_WORKERS=1 to restore the old
# single-process layout. Threads let sync endpoints such as wait-message share
# the worker instead of blocking the entire site while waiting on mail APIs.
if is_standalone_scheduler; then
  export SCHEDULER_STANDALONE=true
  export SCHEDULER_AUTOSTART=false

  python scheduler_app.py &
  SCHEDULER_PID=$!
  echo "Started standalone scheduler PID=${SCHEDULER_PID}"

  trap handle_signal INT TERM
  trap 'cleanup_children || true' EXIT

  gunicorn \
    -w "$GUNICORN_WORKERS" \
    --threads "$GUNICORN_THREADS" \
    -b "$GUNICORN_BIND" \
    --timeout "$GUNICORN_TIMEOUT" \
    --access-logfile "$GUNICORN_ACCESS_LOGFILE" \
    web_outlook_app:app &
  GUNICORN_PID=$!

  set +e
  wait "${GUNICORN_PID}"
  GUNICORN_STATUS=$?
  set -e

  if [ -n "${SCHEDULER_PID}" ] && kill -0 "${SCHEDULER_PID}" 2>/dev/null; then
    kill -TERM "${SCHEDULER_PID}" 2>/dev/null || true
    wait "${SCHEDULER_PID}" 2>/dev/null || true
  fi

  # Clear EXIT trap to avoid double-kill after intentional shutdown.
  trap - EXIT INT TERM
  exit "${GUNICORN_STATUS}"
fi

exec gunicorn \
  -w "$GUNICORN_WORKERS" \
  --threads "$GUNICORN_THREADS" \
  -b "$GUNICORN_BIND" \
  --timeout "$GUNICORN_TIMEOUT" \
  --access-logfile "$GUNICORN_ACCESS_LOGFILE" \
  web_outlook_app:app
