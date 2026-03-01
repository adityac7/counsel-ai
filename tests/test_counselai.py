"""CounselAI E2E Tests — rebuilt."""
import pytest, requests

BASE = "http://localhost:8501"

class TestAPI:
    def test_homepage(self):
        r = requests.get(f"{BASE}/")
        assert r.status_code == 200
        assert "CounselAI Live" in r.text

    def test_case_studies(self):
        r = requests.get(f"{BASE}/api/case-studies")
        assert len(r.json()["case_studies"]) == 16

    def test_sdp_handshake_works(self):
        """Real SDP offer gets valid SDP answer from OpenAI."""
        sdp = open("tests/real_offer.sdp").read()
        r = requests.post(f"{BASE}/api/rtc-connect", data=sdp, headers={"Content-Type":"application/sdp"})
        assert r.status_code in (200, 201), f"Got {r.status_code}: {r.text[:200]}"
        assert "m=audio" in r.text
        assert "ice-ufrag" in r.text

    def test_sdp_no_content_type_error(self):
        sdp = open("tests/real_offer.sdp").read()
        r = requests.post(f"{BASE}/api/rtc-connect", data=sdp, headers={"Content-Type":"application/sdp"})
        assert "Unsupported content type" not in r.text

    def test_analyze_graceful(self):
        files = {"video": ("t.webm", b"\x00"*100, "video/webm")}
        r = requests.post(f"{BASE}/api/analyze-session", files=files, data={"transcript":"[]","student_name":"T","student_class":"10"})
        assert r.status_code == 200

@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_context(permissions=[], ignore_https_errors=True).new_page()
        yield pg
        b.close()

class TestUI:
    def test_title(self, page):
        page.goto(BASE); assert page.title() == "CounselAI Live"

    def test_welcome_visible(self, page):
        page.goto(BASE)
        assert page.locator("#welcome").is_visible()

    def test_case_studies_loaded(self, page):
        page.goto(BASE); page.wait_for_timeout(1500)
        count = page.locator("#case-study option").count()
        assert count == 16, f"Got {count} options"

    def test_audio_element_in_dom(self, page):
        page.goto(BASE)
        assert page.locator("#ai-audio").count() == 1

    def test_ice_function_exists(self, page):
        page.goto(BASE)
        assert page.evaluate("typeof waitForIce === 'function'")

    def test_start_without_mic_graceful(self, page):
        page.goto(BASE); page.wait_for_timeout(1000)
        page.fill("#student-name", "Test")
        page.fill("#class-name", "10")
        page.click("#start-btn"); page.wait_for_timeout(2000)
        # Should show error toast or return to welcome — not crash
        assert page.locator("#welcome").is_visible() or page.locator("#live").is_visible()
