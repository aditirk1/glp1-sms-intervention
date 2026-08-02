"""SMS transport for GoalPost¹.

The demo build is a logging simulator: messages are printed rather than sent,
so the whole pipeline runs with no Twilio account and no carrier fees. Swapping
in a real transport means replacing the body of send_sms() only.
"""

import logging

logger = logging.getLogger("goalpost.sms")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def send_sms(to_number: str, message: str) -> str:
    """Deliver one message. Returns the message body that was sent."""
    try:
        logger.info(f"[GoalPost¹ SMS] To: {to_number} | {message}")
    except Exception as exc:
        print(f"[sms_sender] logging failed ({exc})")
    return message


def send_checkin(to_number: str, patient_name: str, week: int) -> str:
    """Send the weekly 1/2/3 check-in prompt. Returns the message body."""
    message = (
        f"Hi {patient_name}, week {week} check-in from GoalPost¹. "
        f"How is your GLP-1 journey going? "
        f"Reply 1 - Going well "
        f"Reply 2 - Having side effects "
        f"Reply 3 - Not seeing results"
    )
    send_sms(to_number, message)
    return message
