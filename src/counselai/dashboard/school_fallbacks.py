"""Fallback aggregations for school analytics when richer signal tables are empty."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from counselai.storage.models import Profile, SessionRecord, Student


def profile_topic_clusters(db: Session, school_id: uuid.UUID) -> list[dict[str, Any]]:
    """Aggregate school themes from profile rows when signal windows are unavailable."""
    rows = (
        db.query(Profile.school_view_json)
        .join(SessionRecord, Profile.session_id == SessionRecord.id)
        .join(Student, SessionRecord.student_id == Student.id)
        .filter(Student.school_id == school_id)
        .all()
    )

    counts: Counter[str] = Counter()
    for (school_view,) in rows:
        themes = school_view.get("themes", []) if isinstance(school_view, dict) else []
        for theme in themes:
            text = str(theme or "").strip()
            if text:
                counts[text] += 1

    return [
        {"topic_key": key, "occurrences": count, "avg_reliability": None}
        for key, count in counts.most_common(20)
    ]


def profile_construct_distribution(
    db: Session, school_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Aggregate constructs from counsellor profile views when hypotheses are unavailable."""
    rows = (
        db.query(Profile.counsellor_view_json)
        .join(SessionRecord, Profile.session_id == SessionRecord.id)
        .join(Student, SessionRecord.student_id == Student.id)
        .filter(Student.school_id == school_id)
        .all()
    )

    totals: dict[str, dict[str, Any]] = {}
    for (view_json,) in rows:
        constructs = view_json.get("constructs", []) if isinstance(view_json, dict) else []
        for construct in constructs:
            if not isinstance(construct, dict):
                continue

            construct_key = str(construct.get("key") or "").strip()
            label = str(construct.get("label") or "").strip()
            if not construct_key or not label:
                continue

            bucket = totals.setdefault(
                construct_key,
                {
                    "construct_key": construct_key,
                    "label": label,
                    "total": 0,
                    "supported": 0,
                    "mixed": 0,
                    "weak": 0,
                    "score_sum": 0.0,
                    "score_count": 0,
                },
            )
            bucket["total"] += 1

            status = str(construct.get("status") or "mixed").lower()
            if status in ("supported", "mixed", "weak"):
                bucket[status] += 1

            score = construct.get("score")
            if isinstance(score, (int, float)):
                bucket["score_sum"] += float(score)
                bucket["score_count"] += 1

    results: list[dict[str, Any]] = []
    for bucket in totals.values():
        score_count = bucket.pop("score_count")
        score_sum = bucket.pop("score_sum")
        bucket["avg_score"] = (
            round(score_sum / score_count, 3) if score_count else None
        )
        results.append(bucket)

    return sorted(results, key=lambda item: item["total"], reverse=True)[:20]
