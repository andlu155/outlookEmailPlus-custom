#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone BackgroundScheduler process for multi-worker Gunicorn deployments.

When SCHEDULER_STANDALONE=true, the Docker start script launches this process
alongside Gunicorn so only one APScheduler instance runs, while web workers
keep SCHEDULER_AUTOSTART=false.

See docs/DEV/2026-05-22-Issue69-Scheduler拆分设计方案.md.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    # Standalone process always owns the scheduler; never inherit web autostart.
    os.environ["SCHEDULER_STANDALONE"] = "true"
    os.environ["SCHEDULER_AUTOSTART"] = "false"
    # Marks this OS process as the scheduler owner (web workers omit this).
    os.environ["SCHEDULER_PROCESS"] = "true"

    from outlook_web.app import create_app
    from outlook_web.services import graph as graph_service
    from outlook_web.services import scheduler as scheduler_service

    app = create_app(autostart_scheduler=False)
    scheduler = scheduler_service.init_scheduler(
        app,
        graph_service.test_refresh_token_with_rotation,
    )
    if scheduler is None:
        print("Scheduler standalone failed to start (APScheduler missing or init error)", file=sys.stderr)
        return 1

    stop_event = threading.Event()

    def _request_stop(signum, _frame) -> None:
        print(f"Scheduler standalone received signal {signum}, shutting down…")
        stop_event.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    print(f"Scheduler standalone running. PID={os.getpid()}")
    while not stop_event.is_set():
        # Keep the process alive; BackgroundScheduler runs jobs on its own threads.
        stop_event.wait(1.0)

    try:
        instance = scheduler_service.get_scheduler_instance()
        if instance is not None:
            instance.shutdown(wait=False)
            print("Scheduler standalone stopped")
    except Exception as exc:
        print(f"Scheduler standalone shutdown warning: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # Small settle delay is unnecessary; exit code propagates to the supervisor shell.
    raise SystemExit(main())
