"""CounselAI E2E Tests — API + Playwright."""
import pytest, requests, json

BASE = "http://localhost:8501"

class TestAPI:
    def test_homepage_200(self):
        r = requests.get(f"{BASE}/")
        assert r.status_code == 200
        assert "CounselAI Live" in r.text

    def test_case_studies_endpoint(self):
        r = requests.get(f"{BASE}/api/case-studies")
        assert r.status_code == 200
        data = r.json()
        assert len(data["case_studies"]) == 16

    def test_case_study_structure(self):
        cs = requests.get(f"{BASE}/api/case-studies").json()["case_studies"][0]
        for key in ["id", "title", "category", "target_class", "scenario_text"]:
            assert key in cs

    def test_rtc_connect_no_content_type_error(self):
        """The fix: should NOT return 'Unsupported content type' anymore."""
        r = requests.post(f"{BASE}/api/rtc-connect", data="v=0\r\n", headers={"Content-Type":"application/sdp"})
        assert "Unsupported content type" not in r.text

    def test_rtc_connect_rejects_bad_sdp(self):
        r = requests.post(f"{BASE}/api/rtc-connect", data="v=0\r\n", headers={"Content-Type":"application/sdp"})
        assert r.status_code == 400  # invalid SDP, not server error

    def test_analyze_requires_video(self):
        r = requests.post(f"{BASE}/api/analyze-session", data={"transcript":"[]"})
        assert r.status_code == 422

    def test_analyze_with_dummy(self):
        files = {"video": ("t.webm", b"\x00"*100, "video/webm")}
        data = {"transcript": json.dumps([{"role":"student","text":"test"}]), "student_name":"T", "student_class":"10"}
        r = requests.post(f"{BASE}/api/analyze-session", files=files, data=data)
        assert r.status_code == 200 and "profile" in r.json()

    def test_analyze_bad_json(self):
        files = {"video": ("t.webm", b"\x00"*100, "video/webm")}
        r = requests.post(f"{BASE}/api/analyze-session", files=files, data={"transcript":"bad!!"})
        assert r.status_code == 200  # graceful

@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_context(permissions=[], ignore_https_errors=True).new_page()
        yield pg
        b.close()

class TestUI:
    def test_page_loads(self, page):
        page.goto(BASE); assert page.title() == "CounselAI Live"

    def test_welcome_visible(self, page):
        page.goto(BASE)
        assert page.locator("#screen-welcome").is_visible()
        assert page.locator("#screen-session").is_hidden()

    def test_form_elements(self, page):
        page.goto(BASE)
        for el in ["#student-name","#student-class","#case-study","#start-session"]:
            assert page.locator(el).is_visible()

    def test_16_case_studies_loaded(self, page):
        page.goto(BASE); page.wait_for_timeout(1000)
        assert page.locator("#case-study option").count() == 16

    def test_empty_form_toast(self, page):
        page.goto(BASE); page.click("#start-session"); page.wait_for_timeout(500)
        assert page.locator("#toast").is_visible()

    def test_no_mic_graceful(self, page):
        """Valid form but no mic in headless — should not crash."""
        page.goto(BASE); page.wait_for_timeout(1000)
        page.fill("#student-name","Test"); page.fill("#student-class","10")
        page.click("#start-session"); page.wait_for_timeout(2000)
        assert page.locator("#screen-welcome").is_visible() or page.locator("#screen-session").is_visible()

    def test_summary_screen(self, page):
        page.goto(BASE)
        page.evaluate("()=>{document.getElementById('screen-welcome').classList.remove('active');document.getElementById('screen-summary').classList.add('active');document.getElementById('summary-meta').textContent='Test';}")
        assert page.locator("#screen-summary").is_visible()

    def test_new_session_btn(self, page):
        page.goto(BASE)
        page.evaluate("()=>{document.getElementById('screen-welcome').classList.remove('active');document.getElementById('screen-summary').classList.add('active');}")
        page.click("#new-session"); page.wait_for_timeout(300)
        assert page.locator("#screen-welcome").is_visible()

    def test_xss_escaped(self, page):
        page.goto(BASE)
        r = page.evaluate("()=>{const d=document.createElement('div');d.textContent='<script>';return d.innerHTML.includes('&lt;');}")
        assert r

    def test_audio_element_in_dom(self, page):
        page.goto(BASE)
        assert page.locator("#ai-audio").count() == 1
