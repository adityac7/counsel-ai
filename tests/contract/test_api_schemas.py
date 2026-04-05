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
    BatchSummary,
    ClassInsights,
    ConstructAggregate,
    ConstructOut,
    CounsellorQueueResponse,
    GradeDistribution,
    HypothesisStatus,
    ProfileResponse,
    RedFlagOut,
    RedFlagSeverity,
    RedFlagSummary,
    SchoolOverviewResponse,
    SectionDistribution,
    SessionQueueItem,
    SessionStatus,
    Speaker,
    StudentDashboardResponse,
    StudentSessionSummary,
    TopicCluster,
    TopicCount,
    TrendPoint,
)


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
                    evidence_refs=["turn:7"],
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


class TestSchoolAnalyticsContracts:
    def test_school_overview_response_minimal(self):
        resp = SchoolOverviewResponse(
            school_id=uuid.uuid4(),
            name="Test School",
        )
        assert resp.total_sessions == 0
        assert resp.red_flag_summary.total_flags == 0

    def test_school_overview_response_full(self):
        resp = SchoolOverviewResponse(
            school_id=uuid.uuid4(),
            name="Test School",
            board="CBSE",
            city="Mumbai",
            total_students=100,
            total_sessions=250,
            completed_sessions=200,
            avg_duration_seconds=900.5,
            grade_distribution=[
                GradeDistribution(grade="9", student_count=30, session_count=75),
                GradeDistribution(grade="10", student_count=40, session_count=100),
            ],
            red_flag_summary=RedFlagSummary(
                total_flags=15,
                by_severity={"high": 3, "medium": 7, "low": 5},
                by_key={"high_external_pressure": 7, "substance_exposure": 3},
            ),
            topic_clusters=[
                TopicCluster(topic_key="peer_pressure", occurrences=45, avg_reliability=0.82),
            ],
            construct_distribution=[
                ConstructAggregate(
                    construct_key="self_agency",
                    label="Self Agency",
                    total=50, supported=20, mixed=20, weak=10,
                    avg_score=0.55,
                ),
            ],
            session_trend=[
                TrendPoint(period="2026-01-01T00:00:00", session_count=30, unique_students=20),
            ],
            batch_summary=BatchSummary(by_status={"completed": 200, "processing": 30, "failed": 20}),
        )
        assert resp.total_students == 100
        assert resp.grade_distribution[0].grade == "9"
        assert resp.red_flag_summary.by_severity["high"] == 3

    def test_class_insights_schema(self):
        ci = ClassInsights(
            grade="10",
            student_count=40,
            session_count=100,
            completed_sessions=85,
            red_flag_total=5,
            top_topics=[TopicCount(topic_key="career_interest", count=25)],
        )
        assert ci.grade == "10"
        assert ci.top_topics[0].count == 25

    def test_section_distribution(self):
        sd = SectionDistribution(
            grade="9",
            section="A",
            student_count=15,
            session_count=30,
        )
        assert sd.grade == "9"
        assert sd.section == "A"


class TestEnumContracts:
    def test_session_status_values(self):
        assert SessionStatus.draft == "draft"
        assert SessionStatus.completed == "completed"
        assert SessionStatus.failed == "failed"

    def test_speaker_values(self):
        assert Speaker.student == "student"
        assert Speaker.counsellor == "counsellor"

    def test_hypothesis_status_values(self):
        assert HypothesisStatus.supported == "supported"
        assert HypothesisStatus.mixed == "mixed"
        assert HypothesisStatus.weak == "weak"

    def test_red_flag_severity_values(self):
        assert RedFlagSeverity.low == "low"
        assert RedFlagSeverity.medium == "medium"
        assert RedFlagSeverity.high == "high"
