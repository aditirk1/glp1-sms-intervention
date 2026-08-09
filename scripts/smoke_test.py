"""End-to-end smoke test against a throwaway database.

Boots the real FastAPI app with an in-memory-ish SQLite file, seeds a small
cohort, drives the scheduler and the webhook, and asserts the guardrails hold.

Run:  python -m scripts.smoke_test
"""

import os
import shutil
import tempfile

TEMP_DIR = tempfile.mkdtemp(prefix="goalpost-smoke-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP_DIR}/smoke.db"
# The background scheduler would race the assertions below.
os.environ["ENABLE_SCHEDULER"] = "false"


def main() -> None:
    from fastapi.testclient import TestClient

    from api.main import app
    from services import plateau_messenger, sms_sender

    sms_sender.set_quiet(True)
    plateau_messenger.set_offline(True)

    failures = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        status = "ok  " if condition else "FAIL"
        print(f"  [{status}] {label}{'  -> ' + detail if detail else ''}")
        if not condition:
            failures.append(label)

    with TestClient(app) as client:
        print("\nroot")
        root = client.get("/").json()
        check("API responds", root.get("status", "").startswith("GoaLPost"))

        print("\nenrollment")
        created = client.post(
            "/patients",
            json={
                "name": "Test Patient",
                "phone_number": "+15550001111",
                "indication": "AOM",
                "insurance_type": "medicaid",
                "income_quintile": 1,
                "baseline_bmi": 41.2,
            },
        )
        check("enroll returns 200", created.status_code == 200, created.text[:120])
        patient = created.json()
        check("therapy_start_date set", patient.get("therapy_start_date") is not None)
        check("enters loop unscheduled", patient.get("next_checkin_due") is None)

        print("\nscheduler")
        status = client.get("/scheduler/status").json()
        check("one patient due", status["due_now"] == 1, str(status["due_now"]))

        tick = client.post("/scheduler/tick").json()
        check("tick considered the patient", tick["considered"] == 1, str(tick))
        check("tick sent a prompt", tick["messaged"] == 1)
        check(
            "prompt came from the cadence rule",
            tick["by_rule"].get("scheduled_checkin") == 1,
            str(tick["by_rule"]),
        )

        after = client.get("/patients?limit=5").json()["items"][0]
        check("risk denormalized", after["risk_score"] is not None)
        check("rescheduled", after["next_checkin_due"] is not None)
        check("prompt recorded", after["last_prompt_at"] is not None)

        print("\nsecond tick is a no-op")
        again = client.post("/scheduler/tick").json()
        check("nobody due yet", again["considered"] == 0, str(again["considered"]))

        print("\ninbound reply")
        reply = client.post(
            "/webhook/sms", data={"From": "+15550001111", "Body": "3"}
        ).json()
        check("reply scored", "risk_score" in reply, str(reply)[:160])
        check("tier assigned", reply.get("risk_tier") in ("red", "amber", "green"))
        check("rule fired", reply.get("intervention_fired") != "none", str(reply.get("intervention_fired")))

        detail = client.get(f"/patients/{patient['id']}").json()
        check("check-in stored", len(detail["check_ins"]) == 1)
        check("outbound logged", len(detail["outbound_messages"]) >= 1)
        check("risk history has 2 points", len(detail["risk_history"]) == 2)
        check(
            "silence streak cleared by reply",
            detail["consecutive_no_reply"] == 0,
        )

        print("\nweekly send cap")
        # Force repeated manual sends; the cap must stop them.
        sent = 0
        for _ in range(5):
            body = client.post(f"/send-checkin/{patient['id']}").json()
            if body.get("sent"):
                sent += 1
        messages = client.get(f"/patients/{patient['id']}").json()["outbound_messages"]
        outreach = [m for m in messages if m.get("kind") != "acknowledgement"]
        check(
            "no more than 2 outreach messages in the week",
            len(outreach) <= 2,
            f"{len(outreach)} outreach / {len(messages)} total, {sent} manual sends accepted",
        )

        # Reply 1 must still get an acknowledgement even at the outreach cap.
        ack = client.post(
            "/webhook/sms", data={"From": "+15550001111", "Body": "1"}
        ).json()
        check(
            "acknowledgement bypasses weekly cap",
            ack.get("intervention_fired") == "doing_well"
            and bool(ack.get("intervention_message")),
            str(ack)[:160],
        )

        print("\nfilters and pagination")
        envelope = client.get("/patients?limit=1&offset=0").json()
        check("envelope has total", envelope.get("total") == 1)
        check("limit respected", len(envelope["items"]) == 1)
        tier_filtered = client.get("/patients?tier=red").json()
        check("tier filter works", isinstance(tier_filtered["total"], int))
        bad = client.get("/patients?tier=purple")
        check("invalid tier rejected", bad.status_code == 400)

        print("\nwork queue")
        queue = client.get("/tasks?status=open").json()
        check("queue responds", "items" in queue, str(queue)[:120])
        if queue["items"]:
            task_id = queue["items"][0]["id"]
            acked = client.post(f"/tasks/{task_id}/ack").json()
            check("ack works", acked["status"] == "acknowledged")
            resolved = client.post(f"/tasks/{task_id}/resolve").json()
            check("resolve works", resolved["status"] == "resolved")
            check("resolved_at set", resolved["resolved_at"] is not None)
        else:
            print("  [skip] no tasks raised for this patient")

        print("\ncohort metrics")
        metrics = client.get("/cohort/metrics").json()
        check("totals present", metrics["total_patients"] == 1)
        check("retention block present", "curve" in metrics["retention"])
        check(
            "response rate computed",
            metrics["engagement"]["prompts_sent"] >= 1,
            str(metrics["engagement"]),
        )

        print("\nsilence handling")
        # A patient who never replies must still age and accrue a streak.
        client.post(
            "/patients",
            json={
                "name": "Silent Patient",
                "phone_number": "+15550002222",
                "indication": "AOM",
                "insurance_type": "commercial",
                "income_quintile": 3,
                "baseline_bmi": 35.0,
            },
        )
        from datetime import datetime, timedelta

        from db.database import SessionLocal
        from db.models import Patient
        from services import scheduling

        db = SessionLocal()
        try:
            silent = (
                db.query(Patient)
                .filter(Patient.phone_number == "+15550002222")
                .first()
            )
            # Backdate therapy start so tenure can actually move.
            silent.therapy_start_date = datetime.utcnow() - timedelta(days=30)
            db.commit()

            now = datetime.utcnow()
            for week in range(8):
                scheduling.run_due_checkins(
                    now=now + timedelta(days=7 * week), db=db, arm="intervention"
                )
                db.commit()

            db.refresh(silent)
            check(
                "silent patient accrued no-reply streak",
                (silent.consecutive_no_reply or 0) >= 2,
                f"streak={silent.consecutive_no_reply}",
            )
            check(
                "silent patient is not stuck at week 0",
                (silent.weeks_on_therapy or 0) > 0,
                f"week={silent.weeks_on_therapy}",
            )
            check(
                "sustained silence discontinues",
                silent.status == "discontinued",
                f"status={silent.status}",
            )
        finally:
            db.close()

        queue_after = client.get("/tasks?status=all").json()
        kinds = {item["kind"] for item in queue_after["items"]}
        check(
            "silence produced an outreach task",
            "outreach_call" in kinds,
            str(sorted(kinds)),
        )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for name in failures:
            print(f"  - {name}")
        raise SystemExit(1)
    print("All smoke checks passed.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
