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
