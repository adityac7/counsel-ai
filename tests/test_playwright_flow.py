"""Additional Playwright flow coverage for start + summary screens."""
import pytest

BASE = "http://localhost:8501"


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            chromium_sandbox=False,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        pg = browser.new_context(permissions=[], ignore_https_errors=True).new_page()
        yield pg
        browser.close()


def test_start_session_no_mic_error(page):
    page.goto(BASE)
    page.wait_for_timeout(1000)
    page.fill("#student-name", "Test Student")
    page.fill("#student-class", "10")
    page.select_option("#case-study", index=1)
    page.click("#start-session")
    page.wait_for_timeout(2000)
    assert page.locator("#toast").is_visible()
    assert "Error" in page.locator("#toast").inner_text()


def test_summary_screen_with_injected_data(page):
    page.goto(BASE)
    page.evaluate(
        "()=>{"
        "document.getElementById('student-name').value='Injected';"
        "document.getElementById('student-class').value='11';"
        "transcriptEntries=[{role:'student',text:'Hello'},{role:'counsellor',text:'Hi'}];"
        "showSummary();"
        "}"
    )
    assert page.locator("#screen-summary").is_visible()
    assert page.locator("#summary-meta").inner_text().startswith("Session:")
    assert page.locator("#summary-transcript").inner_text().count("Student") == 1
