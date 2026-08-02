"""Generate the plateau intervention message.

Retrieves trial evidence for the patient's week of therapy, then asks Groq's
llama3-8b-8192 to reframe the plateau as a measurable metabolic result. If the
model or the API is unavailable the caller still gets a safe, evidence-based
message.
"""

import os

from dotenv import load_dotenv

from services import vectorstore

load_dotenv()

GROQ_MODEL = "llama3-8b-8192"

FALLBACK_MESSAGE = (
    "The scale can stall while your body keeps changing. Blood pressure and "
    "inflammation markers often continue improving even during weight plateaus. "
    "Try logging one non-scale measurement today, like your waist or blood "
    "pressure."
)

# Offline messages, keyed by the week the plateau shows up. A cohort simulation
# fires tens of thousands of plateau branches; retrieval and an LLM call on each
# would take hours and cost money to prove a scheduling point.
OFFLINE_MESSAGES = [
    (
        8,
        "The scale can stall in the first weeks while your body is still "
        "adjusting to the dose. In STEP 1, blood pressure had already dropped "
        "an average of 6 points by this stage. Take your blood pressure today "
        "and write it down.",
    ),
    (
        20,
        "A stall around this point is expected, not a setback. Trial data "
        "shows waist circumference kept shrinking through months 4 to 6 even "
        "when weight held flat. Measure your waist today and compare it to "
        "where you started.",
    ),
    (
        99,
        "Later in treatment the scale moves slowly while metabolic markers "
        "keep improving. SURMOUNT-1 participants continued lowering HbA1c and "
        "inflammation well past the point weight levelled off. Ask your care "
        "team for your latest HbA1c at your next visit.",
    ),
]

_offline = False


def set_offline(offline: bool) -> None:
    """Serve templated messages instead of calling retrieval and the LLM."""
    global _offline
    _offline = offline


def offline_message(weeks_on_therapy: int) -> str:
    for threshold, message in OFFLINE_MESSAGES:
        if weeks_on_therapy <= threshold:
            return message
    return FALLBACK_MESSAGE

SYSTEM = """
You are a supportive health coach assistant for a patient on a GLP-1
weight loss medication. Your job is to reframe a weight loss plateau
as a metabolic victory using evidence from published clinical trials.

Rules:
- Write at 8th grade reading level
- Maximum 3 sentences total
- Never say the words "medication" or "drug" - say "your treatment"
- Do not tell the patient their medication is working - show it with data
- Cite one specific non-scale metric from the trial data provided
  that improves during plateaus (blood pressure, waist, CRP, HbA1c,
  insulin sensitivity)
- End with one simple action the patient can take today
- Do not recommend dose changes or give medical advice
- Tone: warm, direct, grounded in evidence
"""


def generate_plateau_message(
    patient_dict: dict,
    weeks_on_therapy: int,
    consecutive_reply_3: int,
) -> str:
    """Return a 3-sentence plateau SMS grounded in retrieved trial data."""
    if _offline:
        return offline_message(weeks_on_therapy)

    try:
        trial_context = vectorstore.query_trial_data(weeks_on_therapy, "plateau")

        user_message = f"""
Patient is on GLP-1 therapy for {patient_dict.get('indication', 'obesity')},
week {weeks_on_therapy} of treatment.
They have replied "not seeing results" for {consecutive_reply_3} consecutive weeks.

Clinical trial context:
{trial_context}

Write a 3-sentence SMS message that:
1. Validates that the scale can stall while the body keeps changing
2. Names one specific measurable improvement likely happening right now
   based on their week of therapy and the trial data above
3. Gives one concrete action for today
"""

        from groq import Groq

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_message},
            ],
            max_tokens=200,
            temperature=0.7,
        )
        message = response.choices[0].message.content.strip()
        return message or FALLBACK_MESSAGE
    except Exception as exc:
        print(f"[plateau_messenger] generation failed ({exc}); using fallback message.")
        return FALLBACK_MESSAGE
