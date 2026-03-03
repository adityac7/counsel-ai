"""Clean Gemini Live WebSocket proxy - replacement for broken function."""
from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types as gt
import os
import json
import base64

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyBzcUqlceO2SJoX9UIcg8tL0Gn7YKpgK1M")
GEMINI_MODEL = "models/gemini-2.5-flash-native-audio-latest"

@app.websocket("/api/gemini-ws")
async def gemini_ws_proxy(ws: WebSocket):
    """WebSocket proxy: browser <-> Gemini Live API using official SDK."""
    await ws.accept()
    scenario = ws.query_params.get("scenario", "")
    student_name = ws.query_params.get("name", "Student")

    # Minimal config - only response_modalities, speech_config
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
        async with genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1beta"}).aio.live.connect(
            model=GEMINI_MODEL, config=config
        ) as session:
            print("[gemini-ws] Connected via SDK")
            await ws.send_json({"type": "setup_complete"})

            # Send initial greeting
            greeting = f"Counsellor: Greet {student_name} by name, read the case study aloud \"in Hinglish, then ask: 'Iss situation mein tum kya karte?' Tell me what comes to your mind first. Case study: {scenario}\""
            await session.send(
                turns=gt.Content(parts=[gt.Part(text=greeting)])
            )
            print("[gemini-ws] Initial greeting sent")

            # Main message loop
            async for response in session.receive():
                # Forward to browser
                await ws.send_json({"serverContent": response.model_dump()})
