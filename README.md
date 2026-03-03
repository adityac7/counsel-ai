# CounselAI 🧠

AI-powered voice counselling platform for Indian school students (Class 9-12). Uses Google Gemini's Live API for real-time audio conversations with face + voice analysis.

## Features
- **Live voice counselling** via Gemini 2.5 Flash Native Audio
- **Real-time face analysis** — emotion detection, eye contact, facial tension
- **Voice analysis** — speech rate, pauses, pitch, confidence scoring
- **AI profile generation** — personality, cognitive, emotional profiles via GPT-5.2
- **16 case studies** covering ethics, peer pressure, academic stress, family conflicts
- **Dashboard** with session history and detailed reports

## Quick Start

```bash
# Clone
git clone https://github.com/adityac7/counsel-ai.git
cd counsel-ai

# Setup
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set API keys
export GEMINI_API_KEY="your-gemini-api-key"
export OPENAI_API_KEY="your-openai-api-key"  # for GPT-5.2 profile generation

# Run
python realtime_server.py
```

Open `http://localhost:8501` in your browser.

## HTTPS (required for mic/camera)

Browser requires HTTPS for mic/camera access. Options:

1. **Self-signed cert** (easiest for local):
```bash
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -keyout certs/key.pem -out certs/cert.pem -days 365 -nodes -subj '/CN=localhost'
```

2. **Cloudflare tunnel** (for remote access):
```bash
cloudflared tunnel --url http://localhost:8501
```

## Tech Stack
- **Backend:** FastAPI + Uvicorn
- **AI Voice:** Google Gemini Live API (bidiGenerateContent)
- **Face Analysis:** DeepFace + OpenCV
- **Voice Analysis:** Librosa + Parselmouth
- **Profile Generation:** OpenAI GPT-5.2
- **Database:** SQLite
- **Frontend:** Vanilla HTML/JS with Web Audio API

## API Keys Needed
- `GEMINI_API_KEY` — Google AI Studio key (for Gemini Live + transcription)
- `OPENAI_API_KEY` — OpenAI key (for profile generation)

## License
Private — not for redistribution.
