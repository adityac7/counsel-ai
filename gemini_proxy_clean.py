"""Clean Gemini Live API proxy implementation."""
from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types as gt
from typing import Optional
import os
import json

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyBzcUqlceO2SJoX9UIcg8tL0Gn7YKpgK1M")
GEMINI_MODEL = "models/gemini-2.5-flash-native-audio-latest"
COUNSELLOR_INSTRUCTIONS = """
You are an experienced Indian school counsellor for classes 9-12.
Your goal: make the STUDENT talk more, not you. You are evaluating them 360 degrees —
personality, emotions, cognitive traits, confidence levels.
"""

@app.websocket("/api/gemini-ws")
async def gemini_ws_proxy(ws: WebSocket):
    """WebSocket proxy: browser <-> Gemini Live API using official SDK."""
    await ws.accept()
    scenario = ws.query_params.get("scenario", "")
    student_name = ws.query_params.get("name", "Student")

    # Minimal config - only what Pydantic allows
    config = gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=gt.SpeechConfig(
            voice_config=gt.VoiceConfig(
                prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name="Zephyr")
            )
        ),
    )

    print(f"[gemini-ws] Config: response_modalities=AUDIO, voice=Zephyr")

    session = None
    try:
        async with genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1beta"}).aio.live.connect(model=GEMINI_MODEL, config=config) as session:
            print("[gemini-ws] Connected via SDK")
            await ws.send_json({"type": "setup_complete"})

            # Send initial greeting
            student_scenario = f"Counsellor: Greet {student_name} by name. Read case study aloud \\"in Hinglish, then ask your first probing question. Case study: {scenario}.\""
            await session.send(
                turns=gt.Content(parts=[gt.Part(text=student_scenario)]),
                turn_complete=True,
            )
            print("[gemini-ws] Initial greeting sent")

            # Bidirectional message loop
            try:
                while True:
                    msg = await session.receive()
                    
                    # Handle serverContent messages
                    if "serverContent" in msg:
                        sc = msg["serverContent"]
                            
                        # Model audio/text turn
                        if "modelTurn" in sc and "parts" in sc["modelTurn"]:
                            await ws.send_json({"serverContent": sc})
                            
                            # Turn complete
                            if "turnComplete" in sc:
                                await ws.send_json({"serverContent": sc})

                            # Input transcription (student speech)
                            if "inputTranscription" in sc and "text" in sc["inputTranscription"]:
                                student_text = sc["inputTranscription"]["text"].strip()
                                if student_text and student_text.lower() not in ["[empty]", "[silence]"]:
                                    await ws.send_json({"serverContent": sc})

                    except genai.errors.ApiError as api_err:
                        print(f"[gemini-ws] API error: {api_err}")
                        await ws.send_json({"type": "error", "message": str(api_err)})

    except Exception as e:
        print(f"[gemini-ws] Error: {e}")
        await ws.send_json({"type": "error", "message": str(e)})
    finally:
        await ws.close()
