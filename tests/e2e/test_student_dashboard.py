"""Scenario checks for the student insights page."""

from __future__ import annotations

from playwright.sync_api import Page, expect


class TestStudentDashboard:
    def test_seeded_student_history_renders_growth(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        student_id = seeded_dashboard_data["students"]["history"]
        page.goto(
            f"{server_url}/api/v1/dashboard/students/{student_id}/insights",
            wait_until="networkidle",
        )

        expect(page.locator(".page-header h1")).to_contain_text(
            seeded_dashboard_data["names"]["history_student"]
        )
        expect(page.locator(".stats-row .stat-card")).to_have_count(4)
        expect(page.locator("text=Latest insights")).to_be_visible()
        expect(page.locator("text=Your strengths")).to_be_visible()
        expect(page.locator("text=Your interests")).to_be_visible()
        expect(page.locator("#growthChart")).to_be_visible()

    def test_student_dashboard_shows_latest_summary_and_next_steps(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        student_id = seeded_dashboard_data["students"]["history"]
        page.goto(
            f"{server_url}/api/v1/dashboard/students/{student_id}/insights",
            wait_until="networkidle",
        )

        expect(page.locator("body")).to_contain_text(
            "You are getting clearer about your own choices."
        )
        expect(page.locator("body")).to_contain_text(
            "Practice one refusal line before the next session"
        )


class TestStudentDashboardPrivacy:
    def test_no_risk_level_visible(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        student_id = seeded_dashboard_data["students"]["history"]
        page.goto(
            f"{server_url}/api/v1/dashboard/students/{student_id}/insights",
            wait_until="networkidle",
        )

        body_text = page.locator("body").inner_text().lower()
        assert "risk_level" not in body_text
        assert "high" not in body_text or "highlight" in body_text
        assert "critical" not in body_text
        assert "red flag" not in body_text

    def test_no_hypothesis_scores_visible(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        student_id = seeded_dashboard_data["students"]["history"]
        page.goto(
            f"{server_url}/api/v1/dashboard/students/{student_id}/insights",
            wait_until="networkidle",
        )

        body_text = page.locator("body").inner_text()
        assert "0.72" not in body_text, "Counsellor-only construct score 0.72 leaked to student view"
        assert "0.46" not in body_text, "Counsellor-only construct score 0.46 leaked to student view"
        assert "0.55" not in body_text, "Counsellor-only hypothesis score 0.55 leaked to student view"


class TestStudentDashboardEdgeCases:
    def test_next_steps_renders(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        student_id = seeded_dashboard_data["students"]["history"]
        page.goto(
            f"{server_url}/api/v1/dashboard/students/{student_id}/insights",
            wait_until="networkidle",
        )

        expect(page.locator("body")).to_contain_text("Practice one refusal line")

    def test_growth_areas_listed(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        student_id = seeded_dashboard_data["students"]["history"]
        page.goto(
            f"{server_url}/api/v1/dashboard/students/{student_id}/insights",
            wait_until="networkidle",
        )

        expect(page.locator("body")).to_contain_text("Consistency under pressure")
