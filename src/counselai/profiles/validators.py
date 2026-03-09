"""Validation layer for LLM-generated profile outputs.

Ensures every profile that reaches persistence or the API has been
schema-validated, evidence-checked, and safety-screened.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from counselai.profiles.schemas import (
    Construct,
    CounsellorProfileView,
    RedFlag,
    SchoolProfileView,
    SessionProfile,
    StudentProfileView,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Forbidden content patterns (student view safety)
# ---------------------------------------------------------------------------

_CLINICAL_TERMS = re.compile(
    r"\b(diagnos[ei]s|disorder|patholog|symptom|clinical|psychiatric|"
    r"psychopathol|abnormal|deficit|dysfunction|at[\s-]?risk|red[\s-]?flag|"
    r"risk[\s-]?score|anxiety[\s-]?disorder|depression|ADHD|OCD|PTSD|"
    r"suicid|self[\s-]?harm|bipolar|schizophren)\b",
    re.IGNORECASE,
)

_DIAGNOSTIC_PHRASES = re.compile(
    r"\b(exhibits signs of|consistent with|indicative of|"
    r"meets criteria for|suggestive of|presents with)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def extract_json_from_text(text: str) -> dict | None:
    """Best-effort JSON extraction from LLM output.

    Handles:
    - Pure JSON
    - JSON wrapped in ```json ... ``` blocks
    - JSON with leading/trailing text
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if md_match:
        try:
            return json.loads(md_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding the outermost { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Per-view validators
# ---------------------------------------------------------------------------

class ProfileValidator:
    """Validates LLM outputs against profile schemas and safety rules."""

    def validate_counsellor_view(
        self, raw_text: str
    ) -> tuple[CounsellorProfileView | None, list[str]]:
        """Parse and validate counsellor profile view from LLM output.

        Returns:
            (validated_view, list_of_errors)
        """
        errors: list[str] = []

        data = extract_json_from_text(raw_text)
        if data is None:
            errors.append("Failed to extract valid JSON from LLM output")
            return None, errors

        try:
            view = CounsellorProfileView.model_validate(data)
        except ValidationError as e:
            errors.append(f"Schema validation failed: {e}")
            return None, errors

        # Evidence grounding check: every construct should have refs
        for construct in view.constructs:
            if not construct.evidence_refs and construct.status != "weak":
                errors.append(
                    f"Construct '{construct.key}' has status={construct.status} "
                    f"but no evidence refs"
                )

        # Red flag grounding
        for flag in view.red_flags:
            if not flag.reason.strip():
                errors.append(f"Red flag '{flag.key}' has empty reason")

        if not view.summary.strip():
            errors.append("Counsellor summary is empty")

        return view, errors

    def validate_student_view(
        self, raw_text: str
    ) -> tuple[StudentProfileView | None, list[str]]:
        """Parse and validate student profile view with safety screening.

        Returns:
            (validated_view, list_of_errors)
        """
        errors: list[str] = []

        data = extract_json_from_text(raw_text)
        if data is None:
            errors.append("Failed to extract valid JSON from LLM output")
            return None, errors

        try:
            view = StudentProfileView.model_validate(data)
        except ValidationError as e:
            errors.append(f"Schema validation failed: {e}")
            return None, errors

        # Safety screening: no clinical language in student view
        all_text = " ".join([
            view.summary,
            view.encouragement,
            *view.strengths,
            *view.interests,
            *view.growth_areas,
            *view.suggested_next_steps,
        ])

        clinical_matches = _CLINICAL_TERMS.findall(all_text)
        if clinical_matches:
            errors.append(
                f"Student view contains clinical terms: {clinical_matches}"
            )

        diagnostic_matches = _DIAGNOSTIC_PHRASES.findall(all_text)
        if diagnostic_matches:
            errors.append(
                f"Student view contains diagnostic phrases: {diagnostic_matches}"
            )

        if not view.summary.strip():
            errors.append("Student summary is empty")

        if not view.encouragement.strip():
            errors.append("Student encouragement message is empty")

        return view, errors

    def validate_school_view(
        self, raw_text: str
    ) -> tuple[SchoolProfileView | None, list[str]]:
        """Parse and validate school profile view.

        Returns:
            (validated_view, list_of_errors)
        """
        errors: list[str] = []

        data = extract_json_from_text(raw_text)
        if data is None:
            errors.append("Failed to extract valid JSON from LLM output")
            return None, errors

        try:
            view = SchoolProfileView.model_validate(data)
        except ValidationError as e:
            errors.append(f"Schema validation failed: {e}")
            return None, errors

        if not view.summary.strip():
            errors.append("School summary is empty")

        return view, errors

    def validate_full_profile(
        self, profile: SessionProfile
    ) -> list[str]:
        """Run cross-view consistency checks on a complete profile.

        Returns list of warnings (non-blocking but logged).
        """
        warnings: list[str] = []

        # Check that red_flags on the profile match counsellor view
        counsellor_flag_keys = {rf.key for rf in profile.counsellor_view.red_flags}
        profile_flag_keys = {rf.key for rf in profile.red_flags}
        if counsellor_flag_keys != profile_flag_keys:
            warnings.append(
                f"Red flag mismatch: counsellor_view has {counsellor_flag_keys}, "
                f"profile has {profile_flag_keys}"
            )

        # Student view should not be empty if counsellor view has content
        if profile.counsellor_view.constructs and not (
            profile.student_view.strengths or profile.student_view.interests
        ):
            warnings.append(
                "Counsellor view has constructs but student view has no strengths/interests"
            )

        # School view topics should overlap with counsellor constructs
        counsellor_labels = {
            c.label.lower() for c in profile.counsellor_view.constructs
        }
        school_topics = {t.lower() for t in profile.school_view.primary_topics}
        if counsellor_labels and school_topics and not counsellor_labels & school_topics:
            warnings.append(
                "School topics and counsellor constructs have zero overlap — "
                "possible inconsistency"
            )

        return warnings

    def sanitize_student_view(self, view: StudentProfileView) -> StudentProfileView:
        """Remove any clinical/diagnostic language that slipped through.

        Returns a cleaned copy.
        """
        def _clean(text: str) -> str:
            text = _CLINICAL_TERMS.sub("[area of growth]", text)
            text = _DIAGNOSTIC_PHRASES.sub("shows patterns of", text)
            return text

        return StudentProfileView(
            strengths=[_clean(s) for s in view.strengths],
            interests=view.interests,  # unlikely to contain clinical terms
            growth_areas=[_clean(g) for g in view.growth_areas],
            suggested_next_steps=[_clean(s) for s in view.suggested_next_steps],
            summary=_clean(view.summary),
            encouragement=_clean(view.encouragement),
        )
