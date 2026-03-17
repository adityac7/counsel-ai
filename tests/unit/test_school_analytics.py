"""Unit tests for school analytics service and API endpoints.

Tests use an in-memory SQLite database to validate aggregate queries
without requiring PostgreSQL. Some PostgreSQL-specific features
(ARRAY columns, date_trunc) are stubbed or skipped where necessary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, event, JSON, String
from sqlalchemy.orm import Session, sessionmaker

from counselai.storage.db import Base
from counselai.storage.models import (
    School,
    Student,
    SessionRecord,
    SessionStatus,
    Profile,
    Hypothesis,
    HypothesisStatus,
    SignalWindow,
)

@pytest.fixture
def db_engine():
    """In-memory SQLite engine with all tables created.

    Registers compile-time hooks so PostgreSQL-only types
    (JSONB, UUID, ARRAY) render as SQLite-compatible types.
    """
    from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY

    engine = create_engine("sqlite:///:memory:")

    # Patch PG types to render as SQLite equivalents
    from sqlalchemy.ext.compiler import compiles

    @compiles(JSONB, "sqlite")
    def _jsonb_sqlite(element, compiler, **kw):
        return "JSON"

    @compiles(UUID, "sqlite")
    def _uuid_sqlite(element, compiler, **kw):
        return "VARCHAR(36)"

    @compiles(ARRAY, "sqlite")
    def _array_sqlite(element, compiler, **kw):
        return "JSON"

    # Register date_trunc as a SQLite function
    @event.listens_for(engine, "connect")
    def _register_functions(dbapi_conn, connection_record):
        dbapi_conn.create_function("date_trunc", 2, lambda gran, dt: dt[:10] if dt else None)

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Yield a fresh DB session, rolled back after each test."""
    Session_ = sessionmaker(bind=db_engine)
    session = Session_()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def school(db_session):
    """Create a test school."""
    s = School(
        name="Delhi Public School",
        board="CBSE",
        city="Delhi",
    )
    db_session.add(s)
    db_session.flush()
    return s


@pytest.fixture
def students(db_session, school):
    """Create test students across grades."""
    result = []
    for i, (grade, section) in enumerate([
        ("9", "A"), ("9", "A"), ("9", "B"),
        ("10", "A"), ("10", "B"),
        ("11", "A"),
    ]):
        s = Student(
            full_name=f"Student {i+1}",
            grade=grade,
            section=section,
            school_id=school.id,
        )
        db_session.add(s)
        result.append(s)
    db_session.flush()
    return result


@pytest.fixture
def sessions(db_session, students):
    """Create test sessions for students."""
    result = []
    base_time = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    for i, student in enumerate(students):
        sess = SessionRecord(
            student_id=student.id,
            case_study_id=f"case-{i+1}",
            provider="gemini-live",
            status=SessionStatus.completed if i % 3 != 2 else SessionStatus.processing,
            started_at=base_time + timedelta(days=i * 7),
            ended_at=base_time + timedelta(days=i * 7, minutes=20),
            duration_seconds=1200,
        )
        db_session.add(sess)
        result.append(sess)
    db_session.flush()
    return result


@pytest.fixture
def profiles(db_session, sessions):
    """Create profiles with red flags for some sessions."""
    result = []
    for i, sess in enumerate(sessions):
        flags = []
        if i % 2 == 0:
            flags = [
                {"key": "high_external_pressure", "severity": "medium",
                 "reason": "Repeated deference to parental approval"},
            ]
        if i == 0:
            flags.append(
                {"key": "substance_exposure", "severity": "high",
                 "reason": "Mentioned smoking in peer context"},
            )

        p = Profile(
            session_id=sess.id,
            profile_version="v1",
            student_view_json={"summary": f"Student profile {i}"},
            counsellor_view_json={"summary": f"Counsellor profile {i}"},
            school_view_json={"summary": f"Aggregate view {i}"},
            red_flags_json=flags,
        )
        db_session.add(p)
        result.append(p)
    db_session.flush()
    return result


@pytest.fixture
def hypotheses(db_session, sessions):
    """Create hypotheses for sessions."""
    result = []
    constructs = [
        ("career_identity_clarity", "Career Identity Clarity", HypothesisStatus.supported, 0.73),
        ("self_agency", "Self Agency", HypothesisStatus.mixed, 0.45),
        ("peer_influence_resistance", "Peer Influence Resistance", HypothesisStatus.weak, 0.3),
    ]
    for sess in sessions:
        for key, label, status, score in constructs:
            h = Hypothesis(
                session_id=sess.id,
                construct_key=key,
                label=label,
                status=status,
                score=score,
                evidence_summary=f"Evidence for {key}",
                evidence_refs_json={},
            )
            db_session.add(h)
            result.append(h)
    db_session.flush()
    return result


# ---------------------------------------------------------------------------
# Service tests (using direct SQL queries, skipping PG-specific features)
# ---------------------------------------------------------------------------

class TestSchoolAnalyticsService:
    """Test the SchoolAnalyticsService aggregate queries."""

    def test_get_school(self, db_session, school):
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.get_school(school.id)
        assert result is not None
        assert result.name == "Delhi Public School"

    def test_get_school_not_found(self, db_session):
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.get_school(uuid.uuid4())
        assert result is None

    def test_overview(self, db_session, school, students, sessions):
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.overview(school.id)
        assert result["name"] == "Delhi Public School"
        assert result["total_students"] == 6
        assert result["total_sessions"] == 6

    def test_overview_not_found(self, db_session):
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.overview(uuid.uuid4())
        assert result == {}

    def test_grade_distribution(self, db_session, school, students, sessions):
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.grade_distribution(school.id)
        assert len(result) == 3  # grades 9, 10, 11
        grade_9 = next(g for g in result if g["grade"] == "9")
        assert grade_9["student_count"] == 3
        assert grade_9["session_count"] == 3

    def test_section_distribution(self, db_session, school, students, sessions):
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.section_distribution(school.id)
        assert len(result) >= 4  # 9A, 9B, 10A, 10B, 11A

    def test_red_flag_summary(self, db_session, school, students, sessions, profiles):
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.red_flag_summary(school.id)
        assert result["total_flags"] > 0
        assert "medium" in result["by_severity"] or "high" in result["by_severity"]
        assert "high_external_pressure" in result["by_key"]

    def test_red_flag_summary_empty(self, db_session, school, students, sessions):
        """No profiles = no flags."""
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.red_flag_summary(school.id)
        assert result["total_flags"] == 0

    def test_construct_distribution(self, db_session, school, students, sessions, hypotheses):
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.construct_distribution(school.id)
        assert len(result) == 3
        career = next(c for c in result if c["construct_key"] == "career_identity_clarity")
        assert career["supported"] == 6  # all 6 sessions have this as supported
        assert career["total"] == 6

    def test_profile_fallbacks_fill_constructs_and_topics(
        self, db_session, school, students, sessions
    ):
        from counselai.dashboard.school import SchoolAnalyticsService

        profile = Profile(
            session_id=sessions[0].id,
            profile_version="analyze-session-v1",
            counsellor_view_json={
                "constructs": [
                    {
                        "key": "critical_thinking",
                        "label": "Critical Thinking",
                        "status": "supported",
                        "score": 0.78,
                        "evidence_summary": "Student weighs options before answering.",
                    }
                ]
            },
            school_view_json={"themes": ["peer_pressure", "self_agency"]},
            red_flags_json=[],
        )
        db_session.add(profile)
        db_session.flush()

        svc = SchoolAnalyticsService(db_session)
        result = svc.full_analytics(school.id)

        assert result["topic_clusters"][0]["topic_key"] == "peer_pressure"
        assert result["topic_clusters"][0]["occurrences"] == 1
        assert result["construct_distribution"][0]["construct_key"] == "critical_thinking"
        assert result["construct_distribution"][0]["supported"] == 1

    def test_class_insights(self, db_session, school, students, sessions, profiles):
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.class_insights(school.id, "9")
        assert result["grade"] == "9"
        assert result["student_count"] == 3
        assert result["session_count"] == 3

    def test_batch_summary(self, db_session, school, students, sessions):
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        result = svc.batch_summary(school.id)
        assert "completed" in result["by_status"] or "processing" in result["by_status"]

    def test_privacy_no_student_names(self, db_session, school, students, sessions, profiles, hypotheses):
        """Verify full_analytics output contains NO individual student identifiers."""
        from counselai.dashboard.school import SchoolAnalyticsService
        svc = SchoolAnalyticsService(db_session)
        data = svc.full_analytics(school.id)

        # Convert entire response to string and check no student names appear
        import json
        data_str = json.dumps(data, default=str)
        for student in students:
            assert student.full_name not in data_str, (
                f"Student name '{student.full_name}' leaked into school analytics!"
            )
            assert str(student.id) not in data_str, (
                f"Student ID '{student.id}' leaked into school analytics!"
            )


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestSchoolSchemas:
    """Test Pydantic schema validation for school analytics responses."""

    def test_school_overview_response_minimal(self):
        from counselai.api.schemas import SchoolOverviewResponse
        resp = SchoolOverviewResponse(
            school_id=uuid.uuid4(),
            name="Test School",
        )
        assert resp.total_sessions == 0
        assert resp.red_flag_summary.total_flags == 0

    def test_school_overview_response_full(self):
        from counselai.api.schemas import (
            SchoolOverviewResponse,
            GradeDistribution,
            RedFlagSummary,
            TopicCluster,
            ConstructAggregate,
            TrendPoint,
            BatchSummary,
        )
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
        from counselai.api.schemas import ClassInsights, TopicCount
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
