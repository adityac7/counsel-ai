"""Scenario checks for the counsellor session review page."""

from __future__ import annotations

from playwright.sync_api import Page, expect


class TestCounsellorReview:
    def test_profile_tab_renders_seeded_profile(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        session_id = seeded_dashboard_data["sessions"]["review"]
        page.goto(
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{session_id}",
            wait_until="networkidle",
        )

        expect(page.locator("#tab-profile")).to_be_visible()
        expect(page.locator("#tab-profile")).to_contain_text(
            seeded_dashboard_data["names"]["session_profile_summary"]
        )
        expect(page.locator("#tab-profile")).to_contain_text("Red flags")
        expect(page.locator("#tab-profile")).to_contain_text("Follow-ups")

    def test_transcript_tab_shows_text_and_timing(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        session_id = seeded_dashboard_data["sessions"]["review"]
        page.goto(
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{session_id}",
            wait_until="networkidle",
        )

        page.click("[data-tab='transcript']")
        transcript = page.locator("#tab-transcript")
        expect(transcript).to_contain_text("They keep asking me to try smoking once.")
        expect(transcript).to_contain_text("What do you feel in that moment?")
        expect(transcript).to_contain_text("0:00")

    def test_evidence_and_signals_tabs_render_seeded_data(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        session_id = seeded_dashboard_data["sessions"]["review"]
        page.goto(
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{session_id}",
            wait_until="networkidle",
        )

        page.click("[data-tab='evidence']")
        page.wait_for_timeout(400)
        evidence = page.locator("#tab-evidence")
        expect(evidence).to_contain_text("peer_pressure")
        expect(evidence).to_contain_text("risk_language")

        page.click("[data-tab='signals']")
        signals = page.locator("#tab-signals")
        expect(signals).to_contain_text("Topic windows")
        expect(signals).to_contain_text("Hypotheses")
        expect(signals).to_contain_text("Observations")


# ---------------------------------------------------------------------------
# Deep 4-tab coverage
# ---------------------------------------------------------------------------

def _goto_review(page: Page, server_url: str, seeded_dashboard_data) -> None:
    """Navigate to the review session page."""
    session_id = seeded_dashboard_data["sessions"]["review"]
    page.goto(
        f"{server_url}/api/v1/dashboard/counsellor/sessions/{session_id}",
        wait_until="networkidle",
    )


class TestCounsellorReviewDeep:
    """Comprehensive per-tab assertions for the session review page."""

    # -- Profile tab deep tests -------------------------------------------

    def test_profile_constructs_show_scores(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        profile = page.locator("#tab-profile")
        # Template renders score as '%.0f' % (0.72 * 100) → "72"
        expect(profile).to_contain_text("72%")
        expect(profile).to_contain_text("Critical Thinking")

    def test_profile_red_flags_show_severity(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        profile = page.locator("#tab-profile")
        # Severity is rendered upper-cased via {{ (rf.severity)|upper }}
        expect(profile).to_contain_text("HIGH")
        expect(profile).to_contain_text("peer_pressure")

    def test_profile_cross_modal_notes_visible(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        profile = page.locator("#tab-profile")
        expect(profile).to_contain_text("Speech softens")

    def test_profile_follow_ups_listed(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        profile = page.locator("#tab-profile")
        expect(profile).to_contain_text("Follow up on smoking-related peer triggers.")
        expect(profile).to_contain_text("Role-play a refusal response.")

    # -- Transcript tab deep tests ----------------------------------------

    def test_transcript_has_three_turns(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        page.click("[data-tab='transcript']")
        transcript = page.locator("#tab-transcript")
        # Header shows "Transcript (3 turns)"
        expect(transcript).to_contain_text("3 turns")
        # Each turn is a .turn element inside the transcript container
        turns = transcript.locator(".turn")
        expect(turns).to_have_count(3)

    def test_transcript_speaker_labels(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        page.click("[data-tab='transcript']")
        transcript = page.locator("#tab-transcript")
        expect(transcript).to_contain_text("Student")
        expect(transcript).to_contain_text("Counsellor")

    def test_transcript_timestamps_formatted(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        page.click("[data-tab='transcript']")
        transcript = page.locator("#tab-transcript")
        # Turn 0: start_ms=0 → "0:00", Turn 1: start_ms=9200 → "0:09"
        expect(transcript).to_contain_text("0:00")
        expect(transcript).to_contain_text("0:09")
        # Verify MM:SS pattern exists (e.g. "0:15" for turn 2 start_ms=15000)
        expect(transcript).to_contain_text("0:15")

    # -- Evidence tab deep tests ------------------------------------------

    def test_evidence_loads_observations(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        page.click("[data-tab='evidence']")
        page.wait_for_timeout(500)
        evidence = page.locator("#tab-evidence")
        # Three observations: risk_language, hesitation, peer_pressure
        expect(evidence).to_contain_text("risk_language")
        expect(evidence).to_contain_text("hesitation")
        expect(evidence).to_contain_text("peer_pressure")

    def test_evidence_shows_hypothesis_links(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        page.click("[data-tab='evidence']")
        page.wait_for_timeout(500)
        evidence = page.locator("#tab-evidence")
        expect(evidence).to_contain_text("Peer Resistance")
        expect(evidence).to_contain_text("mixed")

    # -- Signals tab deep tests -------------------------------------------

    def test_signals_topic_windows_populated(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        page.click("[data-tab='signals']")
        signals = page.locator("#tab-signals")
        # segments_json topics: "Greeting and rapport", "Peer pressure and smoking"
        expect(signals).to_contain_text("Greeting and rapport")
        expect(signals).to_contain_text("Peer pressure and smoking")

    def test_signals_observations_by_modality(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        page.click("[data-tab='signals']")
        signals = page.locator("#tab-signals")
        # Observations grouped by modality: CONTENT, AUDIO, CROSS_MODAL
        expect(signals).to_contain_text("CONTENT")
        expect(signals).to_contain_text("AUDIO")
        expect(signals).to_contain_text("CROSS_MODAL")

    # -- Tab switching ----------------------------------------------------

    def test_tab_switching_hides_other_content(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        _goto_review(page, server_url, seeded_dashboard_data)
        profile = page.locator("#tab-profile")
        transcript = page.locator("#tab-transcript")

        # Profile is visible by default
        expect(profile).to_be_visible()
        expect(transcript).not_to_be_visible()

        # Click transcript tab — profile should hide
        page.click("[data-tab='transcript']")
        expect(transcript).to_be_visible()
        expect(profile).not_to_be_visible()

        # Click back to profile — profile visible again
        page.click("[data-tab='profile']")
        expect(profile).to_be_visible()
        expect(transcript).not_to_be_visible()

    # -- Legacy fallback --------------------------------------------------

    def test_legacy_session_json_review_available(
        self, page: Page, server_url: str, seeded_dashboard_data,
    ):
        """Legacy sessions (with raw report JSON, no Profile record) still
        return valid data via the JSON review endpoint."""
        import httpx

        session_id = seeded_dashboard_data["sessions"]["legacy"]
        resp = httpx.get(
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{session_id}/review",
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"]["id"] == session_id
        assert data["profile"] is not None
        # Legacy report populates profile from session.report JSON
        assert len(data["transcript"]) >= 2
        assert data["transcript"][0]["text"] == "I mostly sit alone at lunch."
