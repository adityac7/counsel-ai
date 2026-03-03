"""E2E Playwright tests for CounselAI — headless, no mic required."""
import pytest
import requests

BASE = "http://localhost:8501"


@pytest.fixture(scope="module")
def browser_context():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            chromium_sandbox=False,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        ctx = browser.new_context(
            
            ignore_https_errors=True,
        )
        yield ctx
        browser.close()


@pytest.fixture
def page(browser_context):
    pg = browser_context.new_page()
    yield pg
    pg.close()


class TestBackendAPIs:
    def test_homepage_loads(self):
        r = requests.get(f"{BASE}/")
        assert r.status_code == 200
        assert "CounselAI" in r.text

    def test_dashboard_loads(self):
        r = requests.get(f"{BASE}/dashboard")
        assert r.status_code == 200

    def test_case_studies_api(self):
        r = requests.get(f"{BASE}/api/case-studies")
        assert r.status_code == 200
        data = r.json()
        assert "case_studies" in data
        assert len(data["case_studies"]) > 0

    def test_sessions_api(self):
        r = requests.get(f"{BASE}/api/sessions")
        assert r.status_code == 200
        assert "sessions" in r.json()

    def test_session_detail_404(self):
        r = requests.get(f"{BASE}/api/sessions/99999")
        assert r.status_code == 404


class TestWelcomeScreen:
    def test_welcome_visible(self, page):
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        assert page.locator("#welcome").is_visible()

    def test_student_name_input(self, page):
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        name_input = page.locator("#student-name")
        assert name_input.is_visible()
        name_input.fill("Test Student")
        assert name_input.input_value() == "Test Student"

    def test_class_dropdown_has_grades(self, page):
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        class_select = page.locator("#class-name")
        assert class_select.is_visible()
        options = class_select.locator("option").all_text_contents()
        for grade in ["9", "10", "11", "12"]:
            assert grade in options, f"Class {grade} missing from dropdown"

    def test_case_study_dropdown_populated(self, page):
        page.goto(BASE)
        page.wait_for_timeout(1500)
        options = page.locator("#case-study option").count()
        assert options > 0, "Case study dropdown should have options"

    def test_start_without_mic_shows_error(self, page):
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        page.fill("#student-name", "Test")
        page.locator("#case-study").select_option(index=0)
        start_btn = page.locator("#start-session")
        if start_btn.count():
            start_btn.click()
        else:
            page.click("text=Start session")
        page.wait_for_timeout(2000)
        toast = page.locator("#toast")
        is_still_welcome = page.locator("#welcome").is_visible()
        assert toast.is_visible() or is_still_welcome


class TestLiveScreenElements:
    def test_live_screen_dom(self, page):
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        for sel in ["#live", "#transcript", "#orb", "#end-btn", "#ai-audio", "#enable-audio-btn", "#rtc-debug"]:
            assert page.locator(sel).count() == 1, f"Missing element: {sel}"

    def test_debug_strip(self, page):
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        assert "RTC" in page.locator("#rtc-debug").inner_text()


class TestDashboardPage:
    def test_dashboard_renders(self, page):
        page.goto(f"{BASE}/dashboard")
        page.wait_for_load_state("networkidle")
        assert page.locator("body").inner_text().strip() != ""


class TestModules:
    def test_profile_generator_import(self):
        import sys
        sys.path.insert(0, "/home/clawdbot/counsel-ai")
        import profile_generator
        assert hasattr(profile_generator, "generate_profile")

    def test_db_module(self):
        import sys
        sys.path.insert(0, "/home/clawdbot/counsel-ai")
        import db
        db.init_db()
        assert hasattr(db, "save_session")
        assert hasattr(db, "list_sessions")
        sessions = db.list_sessions()
        assert isinstance(sessions, list)
