# 💊 Dawai Dost

A friendly medicine explainer for elderly patients, built with [Sarvam AI](https://sarvam.ai).

Upload a photo of a prescription, pick a language, and Dawai Dost will:

1. **Read** the prescription with Sarvam **Document AI (Extract)** and pull out the medicines as JSON
2. **Show** the medicines in a clean table
3. **Explain** them with **sarvam-105b** in simple, warm, spoken language — what each medicine is commonly for, when to take it, and before or after food — like a grandchild talking to a grandparent
4. **Speak** that explanation aloud with Sarvam **Bulbul TTS**

Dawai Dost never changes a dose. It only explains what is already written, and always ends by telling you to ask your doctor if in doubt.

## Languages

Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam, Punjabi, Odia and English.

Voice is available for all of these except **Malayalam** and **Odia**, which Bulbul does not have a speaker for yet — those two show the written explanation instead.

## Run it locally

```bash
pip install -r requirements.txt
Ha , Ha use your api key here 
streamlit run app.py
```

Tick **Use demo prescription** to try the whole flow without uploading anything.

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub.
2. Go to [share.streamlit.io](https://share.streamlit.io), pick the repo and set the main file to `app.py`.
3. Open **Advanced settings → Secrets** and paste:

   ```toml
   SARVAM_API_KEY = "your_key_here"
   ```

4. Deploy.

The app reads the key from the `SARVAM_API_KEY` environment variable and falls back to Streamlit secrets, so the same code works locally and when deployed.

> **Never commit your API key.** `.streamlit/secrets.toml` is gitignored — copy `.streamlit/secrets.toml.example` to it for local use.

## Disclaimer

Dawai Dost is an explanation aid, not medical advice. Always follow your doctor's advice.
