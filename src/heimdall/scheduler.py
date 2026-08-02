"""In-process APScheduler wiring: nightly day-recap + time-breakdown.

Jobs share the pipe runner with on-demand runs. Only runs while `serve` is up.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from heimdall.pipes.core import run_pipe
from heimdall.timeutil import today_str

log = logging.getLogger("heimdall.scheduler")

_PIPES = {"day-recap": "day_recap", "time-breakdown": "time_breakdown"}


def start_scheduler(app) -> BackgroundScheduler:
    config = app.state.config
    scheduler = BackgroundScheduler()
    app.state.scheduler = scheduler

    def job(name: str) -> None:
        log.info("scheduled pipe %s for %s", name, today_str())
        try:
            result = run_pipe(
                name,
                day=today_str(),
                config=config,
                db_path=app.state.db_path,
                llm=app.state.llm,
            )
            app.state.last_runs[name] = result["ts"]
            log.info("scheduled pipe %s ok in %sms", name, result["run_ms"])
        except Exception as exc:  # noqa: BLE001 — job must never kill the scheduler
            log.error("scheduled pipe %s failed: %s", name, exc)

    for pipe, cron in _PIPES.items():
        expr = getattr(config.scheduler, cron)
        scheduler.add_job(job, "cron", args=[pipe], **parse_cron(expr), id=pipe)

    scheduler.start()
    return scheduler


def parse_cron(expr: str) -> dict:
    """APScheduler 'cron' trigger args from a 5-field cron expression.

    APScheduler uses (second, minute, hour, day, month, day_of_week); a standard
    cron expression maps to (minute, hour, day, month, day_of_week).
    """
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"invalid cron expression {expr!r}")
    minute, hour, day, month, dow = fields
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": dow,
    }
