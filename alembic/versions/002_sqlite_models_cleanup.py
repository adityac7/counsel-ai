"""SQLite models cleanup — add new fields, tables, indexes.

Revision ID: a1b2c3d4e5f6
Revises: eb85a8f3b3bb
Create Date: 2026-03-13 19:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "eb85a8f3b3bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- New table: student_profiles ----------------------------------------
    op.create_table(
        "student_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id"), nullable=False, unique=True),
        sa.Column("date_of_birth", sa.String(10)),
        sa.Column("gender", sa.String(20)),
        sa.Column("parent_contact", sa.String(100)),
        sa.Column("parent_name", sa.String(255)),
        sa.Column("address", sa.Text()),
        sa.Column("academic_year", sa.String(10)),
        sa.Column("stream", sa.String(50)),
        sa.Column("gpa", sa.Float()),
        sa.Column("attendance_pct", sa.Float()),
        sa.Column("extracurriculars", sa.Text()),  # JSON
        sa.Column("referral_reason", sa.Text()),
        sa.Column("previous_counselling", sa.Boolean(), default=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
    )

    # -- New table: session_feedback ----------------------------------------
    op.create_table(
        "session_feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("respondent", sa.String(20), nullable=False, server_default="student"),
        sa.Column("rating", sa.Integer()),
        sa.Column("helpful", sa.Boolean()),
        sa.Column("comments", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_session_feedback_session_id", "session_feedback", ["session_id"])

    # -- Add columns to sessions (batch mode for SQLite) --------------------
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("session_summary", sa.Text()))
        batch_op.add_column(sa.Column("risk_level", sa.String(20)))
        batch_op.add_column(sa.Column("follow_up_needed", sa.Boolean(), server_default=sa.text("0")))
        batch_op.add_column(sa.Column("topics_discussed", sa.Text()))  # JSON
        batch_op.add_column(sa.Column("student_mood_start", sa.String(50)))
        batch_op.add_column(sa.Column("student_mood_end", sa.String(50)))
        batch_op.add_column(sa.Column("turn_count", sa.Integer()))
        batch_op.add_column(sa.Column("created_at", sa.DateTime()))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime()))

    # -- Indexes on sessions ------------------------------------------------
    op.create_index("ix_sessions_student_id", "sessions", ["student_id"])
    op.create_index("ix_sessions_status", "sessions", ["status"])
    op.create_index("ix_sessions_started_at", "sessions", ["started_at"])
    op.create_index("ix_sessions_risk_level", "sessions", ["risk_level"])

    # -- Indexes on other tables --------------------------------------------
    op.create_index("ix_students_school_id", "students", ["school_id"])
    op.create_index("ix_students_external_ref", "students", ["external_ref"])
    op.create_index("ix_turns_session_id", "turns", ["session_id"])
    op.create_index("ix_artifacts_session_id", "artifacts", ["session_id"])
    op.create_index("ix_signal_windows_session_id", "signal_windows", ["session_id"])
    op.create_index("ix_signal_observations_session_id", "signal_observations", ["session_id"])
    op.create_index("ix_hypotheses_session_id", "hypotheses", ["session_id"])
    op.create_index("ix_profiles_session_id", "profiles", ["session_id"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_profiles_session_id", "profiles")
    op.drop_index("ix_hypotheses_session_id", "hypotheses")
    op.drop_index("ix_signal_observations_session_id", "signal_observations")
    op.drop_index("ix_signal_windows_session_id", "signal_windows")
    op.drop_index("ix_artifacts_session_id", "artifacts")
    op.drop_index("ix_turns_session_id", "turns")
    op.drop_index("ix_students_external_ref", "students")
    op.drop_index("ix_students_school_id", "students")
    op.drop_index("ix_sessions_risk_level", "sessions")
    op.drop_index("ix_sessions_started_at", "sessions")
    op.drop_index("ix_sessions_status", "sessions")
    op.drop_index("ix_sessions_student_id", "sessions")

    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")
        batch_op.drop_column("turn_count")
        batch_op.drop_column("student_mood_end")
        batch_op.drop_column("student_mood_start")
        batch_op.drop_column("topics_discussed")
        batch_op.drop_column("follow_up_needed")
        batch_op.drop_column("risk_level")
        batch_op.drop_column("session_summary")

    op.drop_index("ix_session_feedback_session_id", "session_feedback")
    op.drop_table("session_feedback")
    op.drop_table("student_profiles")
