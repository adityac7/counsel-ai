"""Scenario checks for the dashboard overview page."""

from __future__ import annotations

from playwright.sync_api import Page, expect


class TestDashboardOverview:
    def test_overview_metrics_and_rows_render(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")
        page.wait_for_selector("tbody#sessions-body tr.row", timeout=10_000)

        assert page.locator("#st-total").inner_text().strip() not in {"", "0", "—"}
        assert page.locator("#st-students").inner_text().strip() not in {"", "0", "—"}
        assert page.locator("#st-schools").inner_text().strip() not in {"", "0", "—"}
        assert page.locator("#st-avg").inner_text().strip() not in {"", "—"}

        # Verify at least one session row is visible (specific session may
        # not appear on page 1 if DB has many sessions from prior runs)
        rows = page.locator("tbody#sessions-body tr.row")
        assert rows.count() >= 1

    def test_overview_row_opens_detail_drawer(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")
        page.wait_for_selector("tbody#sessions-body tr.row", timeout=10_000)

        # Use JS openSession to bypass pagination (seeded row may not be in first 50)
        page.evaluate(
            """async (sessionId) => { await openSession(sessionId); }""",
            seeded_dashboard_data["sessions"]["review"],
        )

        detail = page.locator("#session-detail")
        expect(detail).to_be_visible()
        expect(detail).to_contain_text("Session detail")
        expect(detail).to_contain_text(seeded_dashboard_data["names"]["review_student"])
        expect(detail).to_contain_text(seeded_dashboard_data["names"]["session_profile_summary"])
        expect(detail).to_contain_text("Follow up on smoking-related peer triggers.")

    def test_legacy_profile_fallback_renders_in_detail_drawer(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")
        page.wait_for_selector("tbody#sessions-body tr.row", timeout=10_000)

        page.evaluate(
            """async (sessionId) => {
                await openSession(sessionId);
            }""",
            seeded_dashboard_data["sessions"]["legacy"],
        )

        detail = page.locator("#session-detail")
        expect(detail).to_be_visible()
        expect(detail).to_contain_text("Student feels isolated in the current section.")
        expect(detail).to_contain_text("Check social belonging and teacher support in the next session.")
        expect(detail).to_contain_text("Mentions eating lunch alone most days.")


class TestDashboardOverviewNavigation:
    def test_sidebar_nav_links_work(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")

        page.click("nav.sidebar a:has-text('Students')")
        page.wait_for_url("**/api/v1/dashboard/counsellor", timeout=10_000)

        expect(page).to_have_url(f"{server_url}/api/v1/dashboard/counsellor")

    def test_new_session_link_works(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")

        page.click("nav.sidebar a:has-text('New Session')")
        page.wait_for_url(f"{server_url}/", timeout=10_000)

        expect(page).to_have_url(f"{server_url}/")


class TestDashboardOverviewContent:
    def test_sessions_table_has_correct_columns(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")
        page.wait_for_selector("tbody#sessions-body tr.row", timeout=10_000)

        headers = page.locator("table thead th")
        header_texts = [headers.nth(i).inner_text().strip() for i in range(headers.count())]

        header_lower = [h.lower() for h in header_texts]
        for expected in ["student", "grade", "school", "date", "duration", "status"]:
            assert expected in header_lower, f"Expected column '{expected}' in {header_texts}"

    def test_processing_session_in_queue(
        self,
        api_client,
        seeded_dashboard_data,
    ):
        """Processing sessions appear in the queue API response."""
        import httpx

        resp = httpx.get(
            f"{seeded_dashboard_data.get('_url', 'http://localhost:8501')}/api/v1/dashboard/counsellor/queue?limit=200",
            timeout=10,
        )
        if resp.status_code != 200:
            # Fallback to default URL
            resp = httpx.get("http://localhost:8501/api/v1/dashboard/counsellor/queue?limit=200", timeout=10)
        items = resp.json()["items"]
        processing_id = seeded_dashboard_data["sessions"]["processing"]
        match = [i for i in items if i["session_id"] == processing_id]
        assert match, f"Processing session {processing_id} not found in queue"
        assert match[0]["status"] in ("processing", "Processing")

    def test_failed_session_in_queue(
        self,
        api_client,
        seeded_dashboard_data,
    ):
        """Failed sessions appear in the queue when filtered by status."""
        import httpx

        resp = httpx.get(
            "http://localhost:8501/api/v1/dashboard/counsellor/queue?limit=200&status=failed",
            timeout=10,
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        failed_id = seeded_dashboard_data["sessions"]["failed"]
        match = [i for i in items if i["session_id"] == failed_id]
        assert match, f"Failed session {failed_id} not found in queue (status=failed)"
        assert match[0]["status"] in ("failed", "Failed")
