from __future__ import annotations

import json
import os
import time
from urllib.request import urlopen

import pytest
from playwright.sync_api import Page

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
pytestmark = [
    pytest.mark.provider_smoke,
    pytest.mark.skipif(
        not GEMINI_KEY,
        reason="Gemini provider smoke requires GEMINI_API_KEY",
    ),
]


def _build_ws_url(server_url: str) -> str:
    prefix = server_url.replace("http://", "ws://").replace("https://", "wss://")
    params = (
        "name=SmokeTester"
        "&grade=11"
        "&section=A"
        "&school=SmokeSchool"
        "&age=15"
        "&scenario=test-scenario"
        "&lang=hinglish"
    )
    return f"{prefix}/api/gemini-ws?{params}"


class TestLiveSessionProviderSmoke:
    def test_gemini_ws_persists_a_completed_session(self, page: Page, server_url: str) -> None:
        ws_url = _build_ws_url(server_url)

        result = page.evaluate(
            """async (wsUrl) => {
                return new Promise((resolve) => {
                    let sessionId = null;
                    let connectionActive = false;
                    const ws = new WebSocket(wsUrl);
                    const timeout = setTimeout(() => {
                        try { ws.close(4000, 'timeout'); } catch (_) {}
                        resolve({ type: 'timeout', session_id: sessionId, connection_active: connectionActive });
                    }, 25000);

                    ws.addEventListener('message', (event) => {
                        try {
                            const payload = JSON.parse(event.data);
                            if (payload.type === 'session_started') {
                                sessionId = payload.session_id;
                            }
                            if (payload.type === 'connection_active') {
                                connectionActive = true;
                                setTimeout(() => {
                                    try { ws.close(1000, 'smoke-complete'); } catch (_) {}
                                }, 1500);
                            }
                            if (payload.type === 'error' && payload.reconnect_failed) {
                                clearTimeout(timeout);
                                resolve({
                                    type: 'error',
                                    message: payload.message,
                                    session_id: sessionId,
                                    connection_active: connectionActive,
                                });
                            }
                        } catch (err) {
                            clearTimeout(timeout);
                            resolve({
                                type: 'parse_error',
                                message: err.message,
                                session_id: sessionId,
                                connection_active: connectionActive,
                            });
                        }
                    });

                    ws.addEventListener('open', () => {
                        ws.send(JSON.stringify({ stub: true }));
                    });

                    ws.addEventListener('error', (event) => {
                        clearTimeout(timeout);
                        resolve({
                            type: 'error',
                            message: event.message || 'ws error',
                            session_id: sessionId,
                            connection_active: connectionActive,
                        });
                    });

                    ws.addEventListener('close', (event) => {
                        clearTimeout(timeout);
                        resolve({
                            type: 'closed',
                            code: event.code,
                            session_id: sessionId,
                            connection_active: connectionActive,
                        });
                    });
                });
            }""",
            ws_url,
        )

        assert result["type"] == "closed", f"Expected clean close, got {result}"
        assert result.get("connection_active") is True, f"Live connection never became active: {result}"
        assert result.get("session_id"), "Provider session start did not emit session_id"

        session_id = result["session_id"]
        session_payload = None
        for _ in range(20):
            with urlopen(f"{server_url}/api/v1/sessions/{session_id}", timeout=10) as response:
                session_payload = json.loads(response.read().decode("utf-8"))
            if session_payload.get("ended_at") and session_payload.get("duration_seconds") not in (None, 0):
                break
            time.sleep(0.5)

        assert session_payload is not None
        assert session_payload["status"] == "completed"
        assert session_payload["ended_at"], "Provider session never finalized"
        assert session_payload["duration_seconds"] >= 1, session_payload

        with urlopen(
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{session_id}/review",
            timeout=10,
        ) as response:
            review_payload = json.loads(response.read().decode("utf-8"))

        assert review_payload["session"]["id"] == session_id
        assert review_payload["session"]["duration_seconds"] >= 1
