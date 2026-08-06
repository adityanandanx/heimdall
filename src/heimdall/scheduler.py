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
        parsed = parse_cron(expr)
        if parsed is None:
            log.info("scheduled pipe %s disabled in config", pipe)
            continue
        scheduler.add_job(job, "cron", args=[pipe], **parsed, id=pipe)

    scheduler.start()
    return scheduler


def parse_cron(expr: str | None) -> dict | None:
    """APScheduler 'cron' trigger args from a 5-field cron expression, or None
    when the job is disabled (scheduler.day_recap: null, #73).

    APScheduler uses (second, minute, hour, day, month, day_of_week); a standard
    cron expression maps to (minute, hour, day, month, day_of_week).
    """
    if expr is None:
        return None
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


def apply_cron(state, job_id: str, expr: str | None) -> None:
    """Re-arm one scheduled pipe live (#73): remove the old job and add the new
    cron, or skip entirely when `expr` is None (disabled). Called by the
    /settings endpoint on scheduler.* writes with `app.state`; the daemon's
    dirty-marker poll does not own schedules (scheduler runs only in the API
    server process).
    """
    scheduler = state.scheduler
    try:
        scheduler.remove_job(job_id)
    except Exception as exc:  # noqa: BLE001 — job may already be gone (disabled)
        log.debug("scheduled pipe %s not running, skipping removal: %s", job_id, exc)
    parsed = parse_cron(expr)
    if parsed is None:
        log.info("scheduled pipe %s disabled", job_id)
        return
    config = state.config
    state.last_runs.pop(job_id, None)

    def job(name: str) -> None:
        log.info("scheduled pipe %s for %s", name, today_str())
        try:
            result = run_pipe(
                name,
                day=today_str(),
                config=config,
                db_path=state.db_path,
                llm=state.llm,
            )
            state.last_runs[name] = result["ts"]
            log.info("scheduled pipe %s ok in %sms", name, result["run_ms"])
        except Exception as exc:  # noqa: BLE001 — job must never kill the scheduler
            log.error("scheduled pipe %s failed: %s", name, exc)

    scheduler.add_job(job, "cron", args=[job_id], **parsed, id=job_id)
