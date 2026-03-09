"""Contract tests for API request/response schemas.

Validates that all Pydantic models serialize/deserialize correctly,
enforce constraints, and maintain backward compatibility.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from counselai.api.schemas import (
    CohortStat,
    ConstructOut,
    CounsellorQueueResponse,
    InboundMediaChunk,
    JobPayload,
    OutboundTranscriptTurn,
    ProcessingStep,
    ProfileResponse,
    RedFlagOut,
    SchoolOverviewResponse,
    SessionCompleteResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionDetailResponse,
    SessionQueueItem,
    SessionStatus,
    Speaker,
    StudentDashboardResponse,
    StudentSessionSummary,
)


class TestSessionCreateContract:
    def test_valid_request(self):
        req = SessionCreateRequest(
            student_id=uuid.uuid4(),
            case_study_id="peer-pressure-01",
            provider="gemini-live",
        )
        data = json.loads(req.model_dump_json())
        assert "student_id" in data
        assert data["case_study_id"] == "peer-pressure-01"

    def test_default_provider(self):
        req = SessionCreateRequest(
            student_id=uuid.uuid4(),
            case_study_id="test",
        )
        assert req.provider == "gemini-live"

    def test_response_defaults(self):
        resp = SessionCreateResponse(session_id=uuid.uuid4())
        assert resp.status == SessionStatus.draft


class TestSessionDetailContract:
    def test_full_response(self):
        resp = SessionDetailResponse(
            session_id=uuid.uuid4(),
            student_id=uuid.uuid4(),
            case_study_id="peer-pressure-01",
            provider="gemini-live",
            status=SessionStatus.completed,
            started_at=datetime.now(timezone.utc),
            processing_version="v1",
        )
        data = json.loads(resp.model_dump_json())
        assert data["status"] == "completed"
        assert data["processing_version"] == "v1"

    def test_optional_fields_null(self):
        resp = SessionDetailResponse(
            session_id=uuid.uuid4(),
            student_id=uuid.uuid4(),
            case_study_id="test",
            provider="gemini-live",
            status=SessionStatus.draft,
            started_at=datetime.now(timezone.utc),
            processing_version="v1",
        )
        data = json.loads(resp.model_dump_json())
        assert data["ended_at"] is None
        assert data["duration_seconds"] is None


class TestSessionCompleteContract:
    def test_response_shape(self):
        resp = SessionCompleteResponse(
            session_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
        )
        assert resp.status == SessionStatus.processing


class TestWebSocketContracts:
    def test_inbound_media_chunk(self):
        chunk = InboundMediaChunk(
            timestamp_ms=12345,
            mime_type="audio/pcm",
            data_b64="SGVsbG8=",
        )
        assert chunk.type == "media_chunk"

    def test_outbound_transcript_turn(self):
        turn = OutboundTranscriptTurn(
            speaker=Speaker.student,
            turn_index=4,
            start_ms=11800,
            end_ms=16220,
            text="Mujhe lagta hai...",
        )
        data = json.loads(turn.model_dump_json())
        assert data["type"] == "transcript_turn"
        assert data["speaker"] == "student"


class TestProfileResponseContract:
    def test_full_profile(self):
        resp = ProfileResponse(
            session_id=uuid.uuid4(),
            summary="Student shows career confusion",
            constructs=[
                ConstructOut(
                    key="career_identity_clarity",
                    label="Career identity clarity",
                    status="supported",
                    score=0.73,
                    evidence_refs=["turn:7", "window:career_interest"],
                ),
            ],
            red_flags=[
                RedFlagOut(
                    key="high_external_pressure",
                    severity="medium",
                    reason="Repeated deference to parental approval",
                ),
            ],
        )
        data = json.loads(resp.model_dump_json())
        assert len(data["constructs"]) == 1
        assert data["constructs"][0]["score"] == 0.73
        assert len(data["red_flags"]) == 1

    def test_empty_profile(self):
        resp = ProfileResponse(
            session_id=uuid.uuid4(),
            summary="No data",
        )
        assert resp.constructs == []
        assert resp.red_flags == []


class TestDashboardContracts:
    def test_counsellor_queue_response(self):
        resp = CounsellorQueueResponse(
            items=[
                SessionQueueItem(
                    session_id=uuid.uuid4(),
                    student_name="Test Student",
                    status=SessionStatus.completed,
                    red_flag_count=2,
                    started_at=datetime.now(timezone.utc),
                ),
            ],
            total=1,
        )
        data = json.loads(resp.model_dump_json())
        assert data["total"] == 1
        assert data["items"][0]["red_flag_count"] == 2

    def test_school_overview_response(self):
        resp = SchoolOverviewResponse(
            school_id=uuid.uuid4(),
            name="Test School",
            total_sessions=42,
            total_students=15,
            cohort_stats=[
                CohortStat(label="Grade 10", count=8),
                CohortStat(label="Grade 11", count=7),
            ],
        )
        data = json.loads(resp.model_dump_json())
        assert data["total_sessions"] == 42
        assert len(data["cohort_stats"]) == 2

    def test_student_dashboard_response(self):
        sid = uuid.uuid4()
        resp = StudentDashboardResponse(
            student_id=uuid.uuid4(),
            full_name="Test Student",
            sessions=[
                StudentSessionSummary(
                    session_id=sid,
                    case_study_id="peer-pressure-01",
                    status=SessionStatus.completed,
                    started_at=datetime.now(timezone.utc),
                    summary="Good session",
                ),
            ],
        )
        data = json.loads(resp.model_dump_json())
        assert len(data["sessions"]) == 1


class TestJobPayloadContract:
    def test_default_steps(self):
        payload = JobPayload(session_id=uuid.uuid4())
        assert len(payload.steps) == len(ProcessingStep)
        assert ProcessingStep.content in payload.steps

    def test_selective_steps(self):
        payload = JobPayload(
            session_id=uuid.uuid4(),
            steps=[ProcessingStep.content, ProcessingStep.profile],
        )
        assert len(payload.steps) == 2

    def test_serialization_roundtrip(self):
        payload = JobPayload(
            session_id=uuid.uuid4(),
            processing_version="v2",
        )
        data = json.loads(payload.model_dump_json())
        restored = JobPayload(**data)
        assert restored.processing_version == "v2"
        assert len(restored.steps) == len(ProcessingStep)
