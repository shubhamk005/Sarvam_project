"""
Dawai Dost - a friendly medicine explainer for elderly patients.

Upload a prescription photo, pick a language, and the app reads the medicines,
explains them in warm spoken language, and reads the explanation out loud.

Powered by Sarvam AI (Document AI Extract + sarvam-105b chat + Bulbul TTS).
"""

import json
import os
import tempfile
import time

import pandas as pd
import streamlit as st
from sarvamai import SarvamAI
from sarvamai.play import save

# ---------------------------------------------------------------- config

# "sarvam-105b-conversations" answers in ~1s. The plain "sarvam-105b" is a reasoning
# model: it is ~30x slower here and sometimes spends its whole budget thinking and
# returns nothing, which is no good for a live demo.
CHAT_MODEL = "sarvam-105b-conversations"
CHAT_FALLBACK_MODEL = "sarvam-105b"
TTS_MODEL = "bulbul:v4-flash"
TTS_CHAR_LIMIT = 2000  # API rejects around 2500+

# language label -> (sarvam language code, TTS speaker)
# Malayalam and Odia have no Bulbul speaker yet, so they get text only.
LANGUAGES = {
    "Hindi": ("hi-IN", "ritu_hi_medical"),
    "Bengali": ("bn-IN", "roopa_bn_conversational"),
    "Tamil": ("ta-IN", "gokul_ta_narration"),
    "Telugu": ("te-IN", "kavitha_te_conversation"),
    "Marathi": ("mr-IN", "ritu_mr_narration"),
    "Gujarati": ("gu-IN", "pooja_gu_conversational"),
    "Kannada": ("kn-IN", "chaitra_kn_conversation"),
    "Malayalam": ("ml-IN", None),
    "Punjabi": ("pa-IN", "anand_pa_conversation"),
    "Odia": ("od-IN", None),
    "English": ("en-IN", "simran_en_customer"),
}

DEMO_MEDICINES = [
    {
        "name": "Tab. Metformin",
        "dose": "500mg",
        "frequency": "1-0-1",
        "timing": "after food",
        "duration": "30 days",
    },
    {
        "name": "Tab. Amlodipine",
        "dose": "5mg",
        "frequency": "1-0-0",
        "timing": "morning",
        "duration": "30 days",
    },
    {
        "name": "Cap. Vitamin D3",
        "dose": "60000 IU",
        "frequency": "once weekly",
        "timing": "after food",
        "duration": "8 weeks",
    },
    {
        "name": "Tab. Pantoprazole",
        "dose": "40mg",
        "frequency": "1-0-0",
        "timing": "before food",
        "duration": "15 days",
    },
]

EXTRACT_SCHEMA = {
    "type": "object",
    "description": "Medicines listed on a doctor's prescription",
    "properties": {
        "medicines": {
            "type": "array",
            "description": "List of every medicine written on the prescription",
            "items": {
                "type": "object",
                "description": "A single medicine entry",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the medicine exactly as written",
                    },
                    "dose": {
                        "type": "string",
                        "description": "Strength or dose, such as 500mg",
                    },
                    "frequency": {
                        "type": "string",
                        "description": "How often to take it, such as 1-0-1 or twice daily",
                    },
                    "timing": {
                        "type": "string",
                        "description": "Before food, after food, or another timing note",
                    },
                    "duration": {
                        "type": "string",
                        "description": "How long to take it, such as 30 days",
                    },
                },
            },
        }
    },
}


# ---------------------------------------------------------------- helpers


def get_api_key():
    """Read the key from the environment, falling back to Streamlit secrets."""
    key = os.environ.get("SARVAM_API_KEY")
    if key:
        return key.strip()
    try:
        return str(st.secrets["SARVAM_API_KEY"]).strip()
    except Exception:
        return None


@st.cache_resource
def get_client(api_key):
    return SarvamAI(api_subscription_key=api_key)


def clean_reply(text):
    """sarvam-105b can emit a reasoning block; keep only the final answer."""
    if not text:
        return ""
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return text.strip()


def extract_medicines(client, filename, file_bytes, mime):
    """Run Document AI Extract and return the list of medicine dicts."""
    job = client.doc_ai.extract(
        file=[(filename, file_bytes, mime)],
        schema=json.dumps(EXTRACT_SCHEMA),
        language="en-IN",
        output_format="json",
    )
    job_id = job.job_id

    deadline = time.time() + 120
    status = None
    while time.time() < deadline:
        status = client.doc_ai.get_status(job_id=job_id).status
        if status in ("completed", "partially_completed", "failed", "rejected"):
            break
        time.sleep(2)

    if status not in ("completed", "partially_completed"):
        raise RuntimeError(f"Document AI job ended as '{status}'")

    result = client.doc_ai.get_results(job_id=job_id).result
    if isinstance(result, str):
        result = json.loads(result)

    medicines = (result or {}).get("medicines") or []
    if not medicines:
        raise RuntimeError("No medicines were found on the prescription")
    return medicines


def medicines_to_text(medicines):
    lines = []
    for m in medicines:
        bits = [str(m.get("name") or "").strip()]
        for field in ("dose", "frequency", "timing", "duration"):
            value = m.get(field)
            if value:
                bits.append(str(value).strip())
        lines.append(" - ".join(b for b in bits if b))
    return "\n".join(lines)


def explain_medicines(client, medicines, language_label):
    """Ask sarvam-105b for one warm, short explanation covering every medicine."""
    system = (
        "You are a warm, caring grandchild explaining medicines to your elderly "
        "grandparent. Speak simply and kindly, the way people actually talk out loud. "
        "For each medicine say what it is commonly used for, when to take it, and "
        "whether it goes before or after food. "
        "NEVER change, question, suggest, or recalculate any dose, and never add or "
        "remove a medicine. Repeat the doses exactly as given. "
        "Do not use bullet points, numbers, headings, asterisks, or emoji, because this "
        "text will be read aloud. Keep the whole reply under 120 words. "
        "End by gently telling them to ask their doctor if they are in any doubt."
    )
    user = (
        f"Write the explanation in {language_label}, in simple everyday {language_label} "
        f"that an elderly person can follow easily.\n\n"
        f"Here are the medicines from the prescription:\n{medicines_to_text(medicines)}"
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    # Try the fast conversational model first, then fall back if it comes back empty.
    for model in (CHAT_MODEL, CHAT_FALLBACK_MODEL):
        try:
            response = client.chat.completions(
                model=model,
                messages=messages,
                reasoning_effort="low",
                max_tokens=8000,
                temperature=0.3,
            )
            reply = clean_reply(response.choices[0].message.content)
            if reply:
                return reply
        except Exception:
            continue

    raise RuntimeError("The model did not return an explanation, please try again")


def speak(client, text, language_code, speaker):
    """Convert text to speech and return the wav bytes."""
    audio = client.text_to_speech.convert(
        text=text[:TTS_CHAR_LIMIT],
        language_code=language_code,
        model=TTS_MODEL,
        speaker=speaker,
    )
    path = os.path.join(tempfile.gettempdir(), "dawai.wav")
    save(audio, path)
    with open(path, "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------- ui

st.set_page_config(page_title="Dawai Dost", page_icon="💊")

st.title("💊 Dawai Dost")
st.caption("Your prescription, explained simply and read out loud.")

api_key = get_api_key()
if not api_key:
    st.error(
        "SARVAM_API_KEY is not set. Set it and restart the app, or add it to "
        "`.streamlit/secrets.toml`."
    )
    st.stop()

client = get_client(api_key)

language_label = st.selectbox("Choose your language", list(LANGUAGES.keys()))
language_code, speaker = LANGUAGES[language_label]

use_demo = st.checkbox("Use demo prescription", value=True)

uploaded = None
if not use_demo:
    uploaded = st.file_uploader(
        "Upload a photo of your prescription", type=["png", "jpg", "jpeg", "pdf"]
    )
    if uploaded is not None and uploaded.type != "application/pdf":
        st.image(uploaded, caption="Your prescription", use_container_width=True)

ready = use_demo or uploaded is not None
if st.button("Explain my medicines", type="primary", disabled=not ready):

    # 1. get the medicines
    if use_demo:
        medicines = DEMO_MEDICINES
    else:
        try:
            with st.spinner("Reading your prescription..."):
                medicines = extract_medicines(
                    client,
                    uploaded.name,
                    uploaded.getvalue(),
                    uploaded.type or "image/png",
                )
        except Exception as exc:
            st.warning(
                f"Could not read the prescription ({exc}). Showing the demo "
                "prescription instead."
            )
            medicines = DEMO_MEDICINES

    # 2. show the table
    st.subheader("Your medicines")
    table = pd.DataFrame(medicines).fillna("-")
    table.columns = [c.replace("_", " ").title() for c in table.columns]
    st.dataframe(table, use_container_width=True, hide_index=True)

    # 3. explain them
    explanation = None
    try:
        with st.spinner(f"Writing a simple explanation in {language_label}..."):
            explanation = explain_medicines(client, medicines, language_label)
    except Exception as exc:
        st.error(f"Could not write the explanation: {exc}")

    if explanation:
        st.subheader("What this means")
        st.write(explanation)

        # 4. read it out loud
        if speaker is None:
            st.info(
                f"Voice is not available for {language_label} yet, so here is the "
                "explanation in writing."
            )
        else:
            try:
                with st.spinner("Getting the voice ready..."):
                    audio_bytes = speak(client, explanation, language_code, speaker)
                st.audio(audio_bytes, format="audio/wav")
            except Exception as exc:
                st.warning(f"Could not create the audio: {exc}")

st.divider()
st.caption(
    "Dawai Dost only explains what is already written on your prescription. "
    "It never changes a dose. Always follow your doctor's advice."
)
