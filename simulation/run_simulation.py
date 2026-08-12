"""Run a cohort through the real scheduler on a virtual clock.

Advances `now` one day at a time for N weeks, calling the same
run_due_checkins() the API calls hourly in production. Patients reply, or do
not, according to simulation/patient_behavior.py. Nothing here reimplements a
scheduling decision.

    python -m simulation.run_simulation --arm intervention --patients 1000 --weeks 26
    python -m simulation.run_simulation --arm control      --patients 1000 --weeks 26

The control arm still receives cadence prompts and is still scored; only the
interventions are suppressed. The comparison therefore isolates the effect of
acting on the risk signal, not the effect of being contacted at all.
"""

import argparse
import json
import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_ROOT / "simulation" / "results"

DEFAULT_PATIENTS = 1000
DEFAULT_WEEKS = 26
DEFAULT_SEED = 11

TICK_HOUR = 10
REPLY_HOUR = 15
WEEKLY_SEND_CAP = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a GoaLPost¹ cohort simulation.")
    parser.add_argument("--arm", choices=["control", "intervention"], required=True)
    parser.add_argument("--patients", type=int, default=DEFAULT_PATIENTS)
    parser.add_argument("--weeks", type=int, default=DEFAULT_WEEKS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite path for this arm. Defaults to a per-arm file under results/.",
    )
    parser.add_argument("--quiet", action="store_true", default=True)
    return parser.parse_args()


def _rolling_send_violations(messages_by_patient: dict, cap: int) -> tuple:
    """Largest number of messages any patient received in any 7-day window."""
    worst = 0
    violations = 0
    for timestamps in messages_by_patient.values():
        timestamps.sort()
        start = 0
        for end in range(len(timestamps)):
            while timestamps[end] - timestamps[start] >= timedelta(days=7):
                start += 1
            window = end - start + 1
            worst = max(worst, window)
            if window > cap:
                violations += 1
    return worst, violations


def _retention_series(weekly: list, key: str) -> list:
    return [round(row[key], 4) for row in weekly]


def run(
    args: argparse.Namespace,
    origin: datetime | None = None,
    write_json: bool = True,
) -> dict:
    # Imported here so DATABASE_URL is already pointed at this arm's file.
    from db.database import SessionLocal
    from db.models import (
        STATUS_ACTIVE,
        STATUS_DISCONTINUED,
        CheckIn,
        OutboundMessage,
        Patient,
        Task,
        PROMPT_KINDS,
        TASK_OPEN,
    )
    from services import plateau_messenger, rules, scheduling, sms_sender
    from simulation import patient_behavior, seed_cohort

    # Hundreds of thousands of log lines and LLM calls would dominate the run
    # and prove nothing about scheduling.
    sms_sender.set_quiet(args.quiet)
    plateau_messenger.set_offline(True)

    origin = origin or datetime(2025, 1, 6, TICK_HOUR, 0, 0)
    days = args.weeks * 7

    print(f"[{args.arm}] seeding {args.patients} patients...")
    seed_cohort.seed(
        n_patients=args.patients,
        reset=True,
        start_at=origin,
        seed_value=args.seed,
    )

    db = SessionLocal()
    rng = random.Random(args.seed)
    started = time.time()

    try:
        patients = db.query(Patient).order_by(Patient.id).all()
        cohort = patient_behavior.Cohort(patients, rng)

        def on_reply(patient, code: int, moment: datetime) -> None:
            scheduling.process_reply(
                db,
                patient,
                reply=code,
                raw_message=str(code),
                now=moment,
                arm=args.arm,
            )

        weekly: list = []
        total_replies = 0
        total_tasks_worked = 0
        peak_backlog = 0

        for day in range(days):
            midnight = origin + timedelta(days=day)
            tick_moment = midnight.replace(hour=TICK_HOUR)
            reply_moment = midnight.replace(hour=REPLY_HOUR)

            scheduling.run_due_checkins(now=tick_moment, db=db, arm=args.arm)
            day_result = cohort.step(db, reply_moment, patients, on_reply)
            total_replies += day_result.replies
            total_tasks_worked += day_result.tasks_worked

            db.commit()

            if (day + 1) % 7 == 0:
                week = (day + 1) // 7
                active = sum(1 for p in patients if p.status == STATUS_ACTIVE)
                truth = cohort.ground_truth()
                weekly.append(
                    {
                        "week": week,
                        "active": active,
                        "discontinued": args.patients - active,
                        "retention": active / args.patients,
                        "ground_truth_on_therapy": truth["on_therapy"],
                        "ground_truth_retention": truth["on_therapy"] / args.patients,
                        "red": sum(
                            1 for p in patients if p.current_risk_tier == "red"
                        ),
                        "amber": sum(
                            1 for p in patients if p.current_risk_tier == "amber"
                        ),
                        "green": sum(
                            1 for p in patients if p.current_risk_tier == "green"
                        ),
                        "mean_risk": round(
                            sum(p.current_risk_score or 0.0 for p in patients)
                            / max(len(patients), 1),
                            4,
                        ),
                        "open_tasks": db.query(Task)
                        .filter(Task.status == TASK_OPEN)
                        .count(),
                    }
                )
                peak_backlog = max(peak_backlog, weekly[-1]["open_tasks"])
                if week % 4 == 0 or week == args.weeks:
                    print(
                        f"[{args.arm}] week {week:>2}/{args.weeks}  "
                        f"active {active:>4}  "
                        f"on therapy {truth['on_therapy']:>4}  "
                        f"open tasks {weekly[-1]['open_tasks']:>3}"
                    )

        # ------------------------------------------------ post-run metrics

        messages = db.query(OutboundMessage).all()
        by_patient: dict = {}
        by_rule: dict = {}
        for message in messages:
            by_patient.setdefault(message.patient_id, []).append(message.sent_at)
            key = message.rule_id or "unknown"
            by_rule[key] = by_rule.get(key, 0) + 1

        worst_window, violations = _rolling_send_violations(by_patient, WEEKLY_SEND_CAP)

        prompts = [m for m in messages if m.kind in PROMPT_KINDS]
        answered = sum(1 for m in prompts if m.responded)

        out_of_window = sum(
            1
            for m in messages
            if not (
                rules.SEND_WINDOW_START_HOUR
                <= m.sent_at.hour
                < rules.SEND_WINDOW_END_HOUR
            )
        )

        tasks = db.query(Task).all()
        tasks_by_kind: dict = {}
        for task in tasks:
            tasks_by_kind[task.kind] = tasks_by_kind.get(task.kind, 0) + 1

        silent_patients = [p for p in patients if p.last_reply_at is None]
        max_no_reply = max((p.consecutive_no_reply or 0) for p in patients)
        stuck_at_week_zero = sum(
            1 for p in patients if (p.weeks_on_therapy or 0) == 0
        )

        truth = cohort.ground_truth()
        final_active = sum(1 for p in patients if p.status == STATUS_ACTIVE)

        summary = {
            "arm": args.arm,
            "patients": args.patients,
            "weeks": args.weeks,
            "seed": args.seed,
            "runtime_seconds": round(time.time() - started, 1),
            "weekly": weekly,
            "retention_curve": _retention_series(weekly, "retention"),
            "ground_truth_retention_curve": _retention_series(
                weekly, "ground_truth_retention"
            ),
            "totals": {
                "messages_sent": len(messages),
                "messages_per_patient": round(len(messages) / args.patients, 2),
                "prompts_sent": len(prompts),
                "prompts_answered": answered,
                "response_rate": round(answered / max(len(prompts), 1), 4),
                "replies_received": total_replies,
                "check_ins": db.query(CheckIn).count(),
                "tasks_created": len(tasks),
                "tasks_worked": total_tasks_worked,
                "tasks_per_patient": round(len(tasks) / args.patients, 2),
                # A policy that raises more work than a team can absorb is not
                # a working policy, so the backlog is a headline number.
                "peak_open_tasks": peak_backlog,
                "tasks_still_open": sum(1 for t in tasks if t.status == TASK_OPEN),
                "care_team_daily_capacity": (
                    patient_behavior.CARE_TEAM_DAILY_CAPACITY
                ),
                "tasks_by_kind": tasks_by_kind,
                "messages_by_rule": by_rule,
                "final_active": final_active,
                "final_retention": round(final_active / args.patients, 4),
                "discontinued": db.query(Patient)
                .filter(Patient.status == STATUS_DISCONTINUED)
                .count(),
            },
            "guardrails": {
                "weekly_send_cap": WEEKLY_SEND_CAP,
                "max_messages_in_any_7_days": worst_window,
                "cap_violations": violations,
                "messages_outside_send_window": out_of_window,
            },
            "silence": {
                "never_replied": len(silent_patients),
                "max_consecutive_no_reply": max_no_reply,
                "patients_stuck_at_week_zero": stuck_at_week_zero,
                "outreach_tasks": tasks_by_kind.get("outreach_call", 0),
            },
            "ground_truth": truth,
        }

        if write_json:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            out_path = RESULTS_DIR / f"{args.arm}.json"
            with open(out_path, "w", encoding="utf-8") as handle:
                json.dump(summary, handle, indent=2)
            print(f"[{args.arm}] wrote {out_path}")

        return summary
    finally:
        db.close()


def main() -> None:
    args = parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    db_path = args.db or str(RESULTS_DIR / f"sim_{args.arm}.db")
    # Each arm gets its own database so the two runs cannot contaminate each
    # other and the dashboard can point at either.
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    summary = run(args)

    totals = summary["totals"]
    guards = summary["guardrails"]
    print()
    print(f"=== {args.arm} arm ===")
    print(f"  final retention        {totals['final_retention']:.1%}")
    print(f"  ground truth on therapy {summary['ground_truth']['on_therapy']}")
    print(f"  messages / patient     {totals['messages_per_patient']}")
    print(f"  response rate          {totals['response_rate']:.1%}")
    print(
        f"  tasks created          {totals['tasks_created']} "
        f"({totals['tasks_per_patient']}/patient)"
    )
    print(
        f"  queue backlog          worked {totals['tasks_worked']}, "
        f"peak open {totals['peak_open_tasks']}, "
        f"still open {totals['tasks_still_open']}"
    )
    print(
        f"  max msgs in 7 days     {guards['max_messages_in_any_7_days']} "
        f"(cap {guards['weekly_send_cap']}, violations "
        f"{guards['cap_violations']})"
    )
    print(f"  runtime                {summary['runtime_seconds']}s")


if __name__ == "__main__":
    main()
