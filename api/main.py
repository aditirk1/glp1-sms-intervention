"""GoalPost¹ API — SMS check-in backbone for GLP-1 retention."""

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import patients, send_checkin, sms_webhook
from db.database import create_tables

load_dotenv()

app = FastAPI(
    title="GoalPost¹ API",
    description="GLP-1 retention monitoring: SMS check-ins, dropout risk scoring, "
    "barrier detection and intervention routing.",
    version="1.0.0",
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


@app.on_event("startup")
def on_startup() -> None:
    create_tables()
    print("[GoalPost¹] database tables ready")


@app.get("/")
def root():
    return {"status": "GoalPost¹ API running"}
