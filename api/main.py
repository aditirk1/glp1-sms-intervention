"""GoalPost¹ API — autonomous check-in engine for GLP-1 retention."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import (
    cohort,
    patients,
    scheduler,
    send_checkin,
    sms_webhook,
    tasks,
)
from db.database import create_tables

load_dotenv()

# The in-process scheduler is convenient locally and unreliable on hosts that
# sleep idle instances, so it can be turned off in favour of external cron.
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "true").lower() in ("1", "true", "yes")
SCHEDULER_INTERVAL_MINUTES = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "60"))

_scheduler = None


def _run_tick() -> None:
    """APScheduler job: one scheduling pass on its own session."""
    from db.database import SessionLocal
    from services import scheduling

    db = SessionLocal()
    try:
        result = scheduling.tick(db)
        if result.get("considered"):
            print(
                f"[GoalPost¹ scheduler] considered {result['considered']}, "
                f"messaged {result['messaged']}, "
                f"tasks {result['tasks_created']}"
            )
    finally:
        db.close()


def _start_scheduler() -> None:
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler(timezone="UTC")
        _scheduler.add_job(
            _run_tick,
            "interval",
            minutes=SCHEDULER_INTERVAL_MINUTES,
            id="due_checkins",
            # A slow tick must never stack on top of the previous one.
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        print(
            f"[GoalPost¹] scheduler running every {SCHEDULER_INTERVAL_MINUTES} min"
        )
    except Exception as exc:
        # The API is still fully usable via POST /scheduler/tick.
        print(f"[GoalPost¹] scheduler unavailable ({exc}); use POST /scheduler/tick")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    print("[GoalPost¹] database tables ready")

    if ENABLE_SCHEDULER:
        _start_scheduler()
    else:
        print("[GoalPost¹] in-process scheduler disabled; expecting external cron")

    yield

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)


app = FastAPI(
    title="GoalPost¹ API",
    description="GLP-1 retention: risk-stratified SMS check-ins, a declarative "
    "intervention policy, and a care team work queue.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sms_webhook.router, prefix="")
app.include_router(patients.router, prefix="")
app.include_router(send_checkin.router, prefix="")
app.include_router(scheduler.router, prefix="")
app.include_router(tasks.router, prefix="")
app.include_router(cohort.router, prefix="")


@app.get("/")
def root():
    return {
        "status": "GoalPost¹ API running",
        "scheduler_enabled": ENABLE_SCHEDULER,
        "tick_endpoint": "POST /scheduler/tick",
    }
