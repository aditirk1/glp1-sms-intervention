# GoalPost¹

GoalPost¹ is an SMS-based check-in system for obesity and type 2 diabetes patients on GLP-1 therapy. A weekly text asks one question, and the reply is scored for 90-day dropout risk by an XGBoost model whose SHAP attribution identifies *which* barrier is driving the risk — a weight plateau, side effects, or cost. The system then routes the patient to the matching intervention, and a care team dashboard shows who is at risk and what fired.

The demo runs end to end with no paid services: no Twilio, no paid LLM API, and no cloud account requiring a credit card.

## Setup

Run these in order from the project root.

**a. Install dependencies**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**b. Configure environment**

```bash
cp .env.example .env
```

Add your `GROQ_API_KEY` to `.env`. Get one free at [console.groq.com](https://console.groq.com) — no credit card required. If you leave it blank everything still runs; the plateau branch falls back to a safe static message instead of a generated one.

**c. Generate the synthetic cohort**

```bash
python data/generate_synthetic.py
```

**d. Train the risk model**

```bash
python model/train_model.py
```

**e. Build the trial-evidence vectorstore**

```bash
python knowledge_base/build_vectorstore.py
```

This downloads the `all-MiniLM-L6-v2` embedding model (~90 MB) on first run and then works offline.

**f. Start the API**

```bash
uvicorn api.main:app --reload --port 8000
```

**g. Start the dashboard** (in a second terminal)

```bash
streamlit run dashboard/app.py --server.port 8501
```

### macOS note: OpenMP

XGBoost needs the OpenMP runtime, which macOS does not ship. If `import xgboost` fails with `Library not loaded: @rpath/libomp.dylib`, install it:

```bash
brew install libomp
```

If you then hit `OMP: Error #179` or a segfault when the API loads both XGBoost and `sentence-transformers`, two copies of OpenMP are being loaded into one process. Point XGBoost at the copy PyTorch already ships so both share one runtime:

```bash
SP=$(python -c "import site; print(site.getsitepackages()[0])")
install_name_tool -add_rpath "$SP/torch/lib" "$SP/xgboost/lib/libxgboost.dylib"
codesign -f -s - "$SP/xgboost/lib/libxgboost.dylib"
```

## Running the demo

1. Open the dashboard at http://localhost:8501
2. Enroll a patient with the **Enroll New Patient** form. Phone numbers must be E.164, for example `+15551234567`.
3. In **Patient Simulator**, select the patient, choose **3 - Not seeing results**, and click **Simulate Reply**.
4. Watch the risk score, risk tier, barrier type, and generated plateau message appear.
5. Click **Refresh Data** to see the patient table update with the new risk tier.

Replying `3` several times in a row raises `consecutive_reply_3`, which is a strong dropout predictor. Reply `2` routes to the side-effect branch instead, and `1` logs an acknowledgment.

Every outbound message is printed to the API console with a `[GoalPost¹ SMS]` prefix rather than sent, so you can watch the whole conversation without a carrier.

## Sharing a live demo URL

Install [ngrok](https://ngrok.com) (free, no credit card), then:

```bash
ngrok http 8501
```

Share the generated URL.

## Production deployment (no credit card required)

**Backend — [Render](https://render.com) free tier**

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
- Add `GROQ_API_KEY` in the Render environment variables

The build artefacts (`synthetic_patients.csv`, `model.joblib`, `chroma_db/`) are gitignored, so either commit them for deployment or append the three generation steps to the build command.

**Dashboard — [Hugging Face Spaces](https://huggingface.co/spaces)**

- Create a new Space and select the Streamlit SDK
- Upload `dashboard/app.py` as `app.py`
- Add an `API_BASE_URL` secret pointing at your Render backend URL

**Real SMS.** `services/sms_sender.py` is the only file that touches the transport. Replace the body of `send_sms()` with a Twilio call and point your Twilio number's inbound webhook at `POST /webhook/sms`; the route already accepts Twilio's `From` and `Body` form fields.

## Architecture

```
Patient reply
   |
   v
POST /webhook/sms
   |
   v
Risk Scorer (XGBoost + SHAP)
   |
   |--> barrier_type = plateau
   |        |
   |        v
   |    Vectorstore query (Chroma + sentence-transformers)
   |        |
   |        v
   |    Plateau Messenger (Groq llama3-8b-8192)
   |        |
   |        v
   |    Intervention message logged to DB
   |
   |--> barrier_type = side_effect --> static message logged
   |
   |--> reply = 1 --> acknowledgment logged
   |
   v
CheckIn record saved to SQLite
   |
   v
Streamlit Dashboard reads /patients
Simulator displays result in real time
```

### How risk becomes a barrier

`score_patient()` returns a dropout probability and the full per-feature SHAP vector. The barrier is read off the highest-magnitude SHAP feature among the *actionable* ones:

| Dominant feature | Barrier | Intervention |
| --- | --- | --- |
| `weight_change_slope`, `consecutive_reply_3` | `plateau` | Retrieval-grounded plateau message |
| `gi_event_flag` | `side_effect` | Side-effect guidance, care team notified |
| `income_quintile`, `prior_pa_denial`, `insurance_type_*` | `cost` | Flagged for coverage support |

Fixed patient attributes (`indication`, `weeks_on_therapy`, `baseline_bmi`) are excluded from that ranking. They frequently dominate the SHAP magnitudes but point at nothing the care team can act on; `top_shap_feature` still reports the true global maximum for transparency.

Risk tiers: `green` below 0.35, `amber` through 0.60, `red` above.

## Notes on the demo build

- **`weight_change_slope` is a proxy.** There is no scale integration, so the reply stands in for the weight trend (reply 1 = losing, 3 = stalled, 2 = roughly flat). Replace it with measured weights in production. See `_weight_change_slope_proxy()` in `api/routes/sms_webhook.py`.
- **Labels are synthetic and noisy by construction.** `discontinued_90d` is a Bernoulli draw from a per-patient probability, which caps how well *any* model can score: the Bayes-optimal AUC on this cohort is about 0.73. The shipped model reaches roughly 0.64 test AUC on 500 patients and closes to within ~0.02 of the ceiling at 2,000+. Raise `N_PATIENTS` in `data/generate_synthetic.py` if you want the tighter fit.
- **Graceful degradation everywhere.** A missing Groq key, an unbuilt vectorstore, or a missing model file each fall back rather than failing the request, and `/webhook/sms` always returns parseable JSON so the simulator never breaks.

## Data sources for the knowledge base

- **STEP 1** — Wilding JPH et al. *N Engl J Med.* 2021;384:989-1002
- **STEP 4** — Rubino D et al. *JAMA.* 2021;325(14):1414-1425
- **STEP 1 extension** — Rubino S et al. *Diabetes Obes Metab.* 2022
- **SURMOUNT-1** — Jastreboff AM et al. *N Engl J Med.* 2022;387:205-216
- **SURMOUNT-4** — Aronne LJ et al. *JAMA.* 2024;331(1):38-48
