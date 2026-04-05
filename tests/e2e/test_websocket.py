"""Targeted websocket checks for the live session endpoint."""

from __future__ import annotations

import json

from playwright.sync_api import Page


def _ws_base(server_url: str) -> str:
    return server_url.replace("http://", "ws://").replace("https://", "wss://")


class TestWebSocketEndpoint:
    def test_gemini_ws_accepts_upgrade_with_required_params(self, page: Page, server_url: str):
        page.goto(server_url)
        result = page.evaluate(
            """(wsUrl) => {
                return new Promise((resolve) => {
                    let opened = false;
                    const timeout = setTimeout(() => resolve({opened, timed_out: true}), 5000);
                    const query = new URLSearchParams({
                        name: 'Ws Smoke Student',
                        grade: '10',
                        age: '15',
                        section: 'B',
                        school: 'Ws Smoke School',
                        scenario: 'A student is dealing with peer pressure.',
                        lang: 'hinglish',
                    }).toString();

                    const ws = new WebSocket(`${wsUrl}/api/gemini-ws?${query}`);
                    ws.onopen = () => {
                        opened = true;
                    };
                    ws.onmessage = (event) => {
                        clearTimeout(timeout);
                        ws.close();
                        resolve({opened, message: event.data});
                    };
                    ws.onclose = (event) => {
                        clearTimeout(timeout);
                        resolve({opened, closed: true, code: event.code});
                    };
                    ws.onerror = () => {};
                });
            }""",
            _ws_base(server_url),
        )

        assert result["opened"] is True
        if "message" in result:
            payload = json.loads(result["message"])
            assert payload["type"] in {"error", "session_started"}
        else:
            assert result.get("closed") is True

    def test_live_page_ws_url_contains_student_metadata(self, page: Page, server_url: str):
        page.add_init_script(
            """
            (() => {
              window.__wsUrls = [];
              window.WebSocket = class FakeWebSocket {
                constructor(url) {
                  this.url = url;
                  this.readyState = 0;
                  this.onopen = null;
                  this.onmessage = null;
                  this.onclose = null;
                  window.__wsUrls.push(url);
                  setTimeout(() => {
                    this.readyState = 1;
                    if (this.onopen) this.onopen(new Event('open'));
                  }, 10);
                  setTimeout(() => {
                    if (this.onmessage) this.onmessage({ data: JSON.stringify({ type: 'setup_complete' }) });
                  }, 20);
                  setTimeout(() => {
                    if (this.onmessage) this.onmessage({ data: JSON.stringify({ type: 'connection_active' }) });
                  }, 30);
                }
                send() {}
                close() {
                  this.readyState = 3;
                  if (this.onclose) this.onclose({ code: 1000 });
                }
              };
              window.WebSocket.CONNECTING = 0;
              window.WebSocket.OPEN = 1;
              window.WebSocket.CLOSING = 2;
              window.WebSocket.CLOSED = 3;
            })();
            """
        )
        page.goto(server_url, wait_until="networkidle")
        page.fill("#student-name", "Metadata Student")
        page.select_option("#class-name", "11")
        page.fill("#section-name", "C")
        page.fill("#school-name", "Metadata School")
        page.fill("#student-age", "16")
        page.check("#consent-cb")
        page.click("#start-btn")
        page.wait_for_function("() => Array.isArray(window.__wsUrls) && window.__wsUrls.length > 0")

        params = page.evaluate(
            """() => {
                const raw = window.__wsUrls[0];
                const parsed = new URL(raw);
                return {
                    grade: parsed.searchParams.get('grade'),
                    section: parsed.searchParams.get('section'),
                    school: parsed.searchParams.get('school'),
                    age: parsed.searchParams.get('age'),
                };
            }"""
        )
        assert params["grade"] == "11"
        assert params["section"] == "C"
        assert params["school"] == "Metadata School"
        assert params["age"] == "16"

    def test_invalid_ws_path_rejected(self, page: Page, server_url: str):
        page.goto(server_url)
        result = page.evaluate(
            """(wsUrl) => {
                return new Promise((resolve) => {
                    const timeout = setTimeout(() => resolve({opened: false, code: -1}), 3000);
                    const ws = new WebSocket(`${wsUrl}/api/nonexistent-ws`);
                    ws.onopen = () => {
                        clearTimeout(timeout);
                        ws.close();
                        resolve({opened: true, code: 0});
                    };
                    ws.onerror = () => {
                        clearTimeout(timeout);
                        resolve({opened: false, code: -1});
                    };
                    ws.onclose = (event) => {
                        clearTimeout(timeout);
                        resolve({opened: false, code: event.code});
                    };
                });
            }""",
            _ws_base(server_url),
        )
        assert result["opened"] is False
