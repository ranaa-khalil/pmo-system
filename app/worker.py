"""Officer beat — the R1 scheduler runtime (ADR-02).

In-process APScheduler started from the FastAPI startup event; jobs wire the
EXISTING tested services (no rewrites): the rules sweep (evaluate_rules —
draft-producing only), the nightly digest + day-report beat, and the Friday
weekly digests. Every job:

- tenant-iterating with per-tenant try/except (one broken tenant never
  blocks the beat — log and continue),
- advisory-locked via pg_try_advisory_lock (one connection per job tick,
  key per job) so two replicas never double-run — the helper NO-OPs
  (returns True) on SQLite so the beat runs on localhost/tests,
- idempotent per window via the BeatRun (job, window_key) unique row —
  a restart never re-runs a window that already ran (catch-up-on-start
  reuses the same guard),
- registered once (start_scheduler is safe to call repeatedly).

Env: PMO_SCHEDULER_ENABLED (default enabled; set 0/false to disable —
tests run with it disabled so the suite never spawns threads).

Strangler exit: the same module runs standalone as
`python -m app.worker` when the worker splits from the web replica.
"""
import logging
import os
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, engine
from app.models.beat_run import BeatRun
from app.models.tenant import Tenant
from app.services.digest import run_daily_digests, run_weekly_exec_digests, run_weekly_pm_digests
from app.services.officer import ensure_rule_templates, publish_day_reports
from app.services.rules_engine import evaluate_rules

logger = logging.getLogger("app.worker")

# ---------------------------------------------------------------------------
# Job registry (module-level, in-memory mirror of BeatRun for the status API)
# ---------------------------------------------------------------------------
_LAST_RUN: dict[str, dict] = {}

NIGHTLY_HOUR = 23   # nightly beat: 23:00 local
WEEKLY_DAY = "fri"  # weekly digests: Friday 23:05 local


def _scheduler_enabled() -> bool:
    return os.environ.get("PMO_SCHEDULER_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


# ---------------------------------------------------------------------------
# Advisory lock (PG) with a SQLite no-op so the beat runs on localhost
# ---------------------------------------------------------------------------
def _acquire_beat_lock(conn, job: str) -> bool:
    """pg_try_advisory_lock keyed per job. SQLite (dev/tests) always wins."""
    if engine.dialect.name == "sqlite":
        return True
    key = abs(hash(f"pmo-beat:{job}")) % (2 ** 31 - 1)
    got = conn.execute(
        __import__("sqlalchemy").text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
    ).scalar()
    return bool(got)


def _release_beat_lock(conn, job: str) -> None:
    if engine.dialect.name == "sqlite":
        return
    key = abs(hash(f"pmo-beat:{job}")) % (2 ** 31 - 1)
    conn.execute(
        __import__("sqlalchemy").text("SELECT pg_advisory_unlock(:key)"), {"key": key}
    )


# ---------------------------------------------------------------------------
# Per-tenant job bodies (each = the existing tested services)
# ---------------------------------------------------------------------------
def _tenant_rules_sweep(db, tenant, tenant_config=None) -> dict:
    ensure_rule_templates(db, tenant)
    return evaluate_rules(db, tenant)


def _tenant_nightly(db, tenant, tenant_config=None) -> dict:
    day = publish_day_reports(db, tenant)
    digests = run_daily_digests(db, tenant, tenant_config=tenant_config)
    return {"day_reports": day, "daily_digests": digests}


def _tenant_weekly(db, tenant, tenant_config=None) -> dict:
    pm = run_weekly_pm_digests(db, tenant, tenant_config=tenant_config)
    ex = run_weekly_exec_digests(db, tenant, tenant_config=tenant_config)
    return {"weekly_pm": pm, "weekly_exec": ex}


# job → module-level function name (resolved at call time via globals() so
# tests can monkeypatch the per-tenant bodies)
JOBS = {
    "rules_sweep": {"fn": "_tenant_rules_sweep", "every": "hourly"},
    "nightly": {"fn": "_tenant_nightly", "every": "daily"},
    "weekly": {"fn": "_tenant_weekly", "every": "weekly"},
}


# ---------------------------------------------------------------------------
# The beat wrapper: lock → iterate tenants (per-tenant try/except) → BeatRun
# ---------------------------------------------------------------------------
def _window_key(job: str, now: datetime | None = None) -> str:
    now = now or datetime.utcnow()
    if job == "weekly":
        monday = now.date() - timedelta(days=now.weekday())
        friday = monday + timedelta(days=4)
        return friday.isoformat()
    return now.strftime("%Y-%m-%d")


def _mark_ran(db, job: str, window: str, result: dict) -> bool:
    """Persist the window run; returns False if it already ran (idempotent)."""
    try:
        db.add(BeatRun(job=job, window_key=window, tenant_id=None, result=result))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _window_already_ran(db, job: str, window: str) -> bool:
    return (
        db.query(BeatRun)
        .filter(BeatRun.job == job, BeatRun.window_key == window)
        .first()
        is not None
    )


def run_beat(job: str, window: str | None = None) -> dict:
    """Run one beat across all tenants: advisory lock → BeatRun guard →
    per-tenant iteration with try/except. Returns the run summary."""
    spec = JOBS.get(job)
    if not spec:
        return {"error": f"unknown job {job}"}
    window = window or _window_key(job)
    per_tenant = globals()[spec["fn"]]

    conn = engine.connect()
    try:
        if not _acquire_beat_lock(conn, job):
            logger.info("Beat %s skipped — another replica holds the lock", job)
            return {"job": job, "skipped": "locked"}
        db = SessionLocal()
        try:
            if _window_already_ran(db, job, window):
                return {"job": job, "skipped": "already_ran", "window": window}
            results: dict = {}
            tenants = db.query(Tenant).all()
            for tenant in tenants:
                try:
                    results[str(tenant.id)] = per_tenant(db, tenant)
                except Exception as exc:  # noqa: BLE001 — one broken tenant never blocks the beat
                    db.rollback()
                    logger.exception("Beat %s failed for tenant %s", job, tenant.id)
                    results[str(tenant.id)] = {"error": str(exc)[:200]}
            _mark_ran(db, job, window, {"tenants": len(results)})
            _LAST_RUN[job] = {
                "window": window,
                "ran_at": datetime.utcnow().isoformat(),
                "tenants": len(results),
                "result": results,
            }
            return {"job": job, "window": window, "tenants": results}
        finally:
            db.close()
    finally:
        _release_beat_lock(conn, job)
        conn.close()


def run_catchup(now: datetime | None = None) -> dict:
    """Catch-up-on-start: run any due-but-missed window once, bounded."""
    now = now or datetime.utcnow()
    ran = {}
    if now.hour >= NIGHTLY_HOUR:
        ran["nightly"] = run_beat("nightly", window=_window_key("nightly", now))
    if now.weekday() == 4 and now.hour >= NIGHTLY_HOUR:  # Friday
        ran["weekly"] = run_beat("weekly", window=_window_key("weekly", now))
    return ran or {"catchup": "nothing_due"}


# ---------------------------------------------------------------------------
# Scheduler lifecycle (idempotent; called from the FastAPI startup event)
# ---------------------------------------------------------------------------
_scheduler = None


def start_scheduler():
    """Start the beat scheduler once. Safe to call repeatedly."""
    global _scheduler
    if not _scheduler_enabled():
        logger.info("PMO_SCHEDULER_ENABLED is off — beat scheduler not started")
        return None
    if _scheduler is not None:
        return _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
        timezone="UTC",
    )
    sched.add_job(lambda: run_beat("rules_sweep"), "cron", minute=0, id="rules_sweep")
    sched.add_job(lambda: run_beat("nightly"), "cron", hour=NIGHTLY_HOUR, minute=0, id="nightly")
    sched.add_job(lambda: run_beat("weekly"), "cron", day_of_week=WEEKLY_DAY, hour=NIGHTLY_HOUR, minute=5, id="weekly")
    sched.add_job(run_catchup, "date", id="catchup")  # fires immediately after start
    sched.start()
    _scheduler = sched
    logger.info("Officer beat scheduler started (3 cron jobs + catch-up)")
    return sched


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001 — shutdown must never raise at exit
            pass
        _scheduler = None


def scheduler_status() -> dict:
    """Status for GET /api/officer/status."""
    jobs = {}
    if _scheduler is not None:
        for j in _scheduler.get_jobs():
            jobs[j.id] = {"next_run": str(j.next_run_time) if j.next_run_time else None}
    for job, info in _LAST_RUN.items():
        jobs.setdefault(job, {})["last_run"] = {
            "window": info["window"], "ran_at": info["ran_at"], "tenants": info["tenants"],
        }
    return {"enabled": _scheduler_enabled(), "running": _scheduler is not None, "jobs": jobs}


if __name__ == "__main__":
    # Strangler exit: standalone worker (same module, separate replica)
    logging.basicConfig(level=logging.INFO)
    sched = start_scheduler()
    if sched is None:
        raise SystemExit("PMO_SCHEDULER_ENABLED is off — nothing to run")
    try:
        import time

        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        shutdown_scheduler()
