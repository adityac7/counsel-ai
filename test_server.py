"""Test server with detailed logging."""
import asyncio
import json
import os
import traceback
from datetime import datetime
from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect
from google import genai
from google.genai import types as gt

app = FastAPI()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyBzcUqlceO2SJoX9UIcg8tL0Gn7YKpgK1M")
GEMINI_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
GEMINI_MODEL = "models/gemini-2.5-flash-native-audio-latest"

print(f"[init] Using GEMINI_API_KEY: {GEMINI_API_KEY[:20]}...")
print(f"[init] GEMINI_MODEL: {GEMINI_MODEL}")

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options={"api_version": "v1beta"}
)
print("[init] Gemini client initialized")

COUNSELLOR_INSTRUCTIONS = (
    "You are an experienced Indian school counsellor for classes 9-12. "
    "Your goal: make the STUDENT talk more, not you. You are evaluating them 360 degrees — "
    "emotional intelligence, decision-making, values, peer dynamics, self-awareness.\n\n"
    "RULES:\n"
    "- Keep your responses SHORT: 1-2 sentences max. Your job is to LISTEN and PROBE.\n"
    "- Ask ONE precise question per turn. Make it count.\n"
    "- Do NOT mirror or repeat what the student said. No paraphrasing back.\n"
    "- Only repeat if you genuinely need clarification on something unclear.\n"
    "- Do NOT be overly warm or verbose. No \"wah\", \"bahut accha\", \"kya baat hai\". "
    "Be natural, not theatrical.\n"
    "- Use casual Hinglish naturally: beta, accha, hmm, aur, theek hai.\n"
    "- Your questions should dig deeper each time — move from surface to values to feelings.\n"
    "- Cover multiple angles: what they think, what they feel, what they would do, "
    "what they fear, what matters most to them.\n"
    "- End the session after 8-10 exchanges. Wrap up naturally: \"Accha beta, bahut acchi "
    "baat ki tumne. Thank you.\"\n"
    "- For the first response: briefly greet by name, read the case study concisely in "
    "Hinglish, then immediately ask the first probing question.\n"
    "- Do NOT lecture. Do NOT give advice. Do NOT analyze during the session.\n\n"
)


@app.websocket("/api/gemini-ws")
async def gemini_ws_proxy(ws: WebSocket):
    """WebSocket proxy: browser <-> Gemini Live API using official SDK."""
    print(f"[{datetime.now()}] WebSocket connection attempt")
    await ws.accept()
    scenario = ws.query_params.get("scenario", "")
    student_name = ws.query_params.get("name", "Student")

    print(f"[{datetime.now()}] Connection accepted: student={student_name}, scenario_len={len(scenario)}")

    config = gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=gt.SpeechConfig(
            voice_config=gt.VoiceConfig(
                prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name="Zephyr")
            )
        ),
        system_instruction=gt.Content(
            parts=[gt.Part(text=COUNSELLOR_INSTRUCTIONS + scenario)]
        ),
    )

    print(f"[{datetime.now()}] Config prepared, connecting to Gemini...")

    session = None
    try:
        print(f"[{datetime.now()}] Starting live.connect()...")
        async with gemini_client.aio.live.connect(model=GEMINI_MODEL, config=config) as session:
            print(f"[{datetime.now()}] Connected to Gemini successfully")
            await ws.send_json({"type": "setup_complete"})

            # Send trigger audio
            import struct
            sample_rate = 24000
            duration_ms = 100
            num_samples = int(sample_rate * duration_ms / 1000)
            silent_audio = struct.pack('<' + 'h' * num_samples, *([0] * num_samples))
            await session.send_realtime_input(
                audio=gt.Blob(data=silent_audio, mime_type="audio/pcm")
            )
            await session.send_realtime_input(audio_stream_end=True)
            print(f"[{datetime.now()}] Trigger audio sent")

            # Receive loop
            msg_count = 0
            try:
                async for response in session.receive():
                    msg_count += 1
                    print(f"[{datetime.now()}] Received Gemini message #{msg_count}: text={bool(response.text)}, audio={bool(response.data)}")

                    # Forward to browser
                    if response.text or response.data:
                        import base64
                        out = {"serverContent": {}}
                        sc = out["serverContent"]
                        if response.data:
                            sc["modelTurn"] = {"parts": [{"inlineData": {"data": base64.b64encode(response.data).decode(), "mimeType": "audio/pcm"}}]}
                        if response.text:
                            if "modelTurn" not in sc:
                                sc["modelTurn"] = {"parts": []}
                            sc["modelTurn"]["parts"].append({"text": response.text})

                        if response.server_content and response.server_content.turn_complete:
                            sc["turnComplete"] = True

                        await ws.send_json(out)
                        print(f"[{datetime.now()}] Sent to browser")

                    if msg_count >= 10:  # Limit for testing
                        break

            except Exception as e:
                print(f"[{datetime.now()}] Error in receive loop: {e}")
                traceback.print_exc()

            print(f"[{datetime.now()}] Test completed, closing connection")

    except Exception as e:
        print(f"[{datetime.now()}] Error: {e}")
        traceback.print_exc()
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        print(f"[{datetime.now()}] Closing WebSocket")
        try:
            await ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8502)
