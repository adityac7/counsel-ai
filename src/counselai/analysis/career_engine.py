"""
Career Aptitude Engine — 6-Stage Pipeline (Python)
===================================================
Pure Python. No LLM dependency. Takes 9 dimension scores,
returns ranked career matches with composite scores.

Stages:
  1. Weighted Fit (40%)         — raw skill alignment
  2. Profile Shape Match (25%)  — cosine similarity to ideal career profile
  3. Critical Dimension Gate    — penalty multiplier for missing foundations
  4. Synergy Detection (15%)    — bonus for evidence-backed dimension pairs
  5. Confidence Estimation      — multiplier based on evidence coverage
  6. Evidence Linking           — links match to specific transcript moment
"""

from __future__ import annotations

import math
from typing import Any, Optional

# ============================================================
# DIMENSION INDEX REFERENCE
# ============================================================
DIM_NAMES = [
    "Analytical Depth",      # 0
    "Critical Reasoning",    # 1
    "Decision Reasoning",    # 2
    "Perspective & Empathy", # 3
    "Ethical Compass",       # 4
    "Self-Reflection",       # 5
    "Resilience",            # 6
    "Communication",         # 7
    "Curiosity",             # 8
]

# ============================================================
# SYNERGY DEFINITIONS
# Evidence-backed dimension pairs that amplify career fit
# ============================================================
SYNERGIES = [
    {"dims": [0, 8], "name": "Research Aptitude",
     "desc": "Analytical depth + curiosity → investigative mindset"},
    {"dims": [3, 7], "name": "People Aptitude",
     "desc": "Empathy + communication → people-facing effectiveness"},
    {"dims": [2, 6], "name": "High-Stakes Aptitude",
     "desc": "Decision reasoning + resilience → pressure performance"},
    {"dims": [1, 4], "name": "Justice Aptitude",
     "desc": "Critical reasoning + ethical compass → governance & fairness"},
    {"dims": [5, 8], "name": "Growth Aptitude",
     "desc": "Self-reflection + curiosity → continuous learning"},
    {"dims": [0, 7], "name": "Advisory Aptitude",
     "desc": "Analytical depth + communication → consulting & advisory"},
]

# ============================================================
# 55 CAREER TAXONOMY
# Weights per dimension: 0=Not relevant, 1=Helpful, 2=Important, 3=Critical
# Order: [AD, CR, DR, PE, EC, SR, RA, CP, EQ]
# ============================================================
CAREERS = [
    # Science & Research
    {"n": "Data Scientist",          "cat": "Science & Research",    "w": [3,3,1,0,0,1,1,1,3]},
    {"n": "Research Scientist",      "cat": "Science & Research",    "w": [3,3,0,0,0,2,1,1,3]},
    {"n": "Biotechnologist",         "cat": "Science & Research",    "w": [3,2,1,0,1,1,1,0,3]},
    {"n": "Environmental Scientist", "cat": "Science & Research",    "w": [2,2,1,2,2,1,1,1,2]},
    {"n": "Astrophysicist",          "cat": "Science & Research",    "w": [3,3,0,0,0,2,1,0,3]},
    {"n": "Statistician",            "cat": "Science & Research",    "w": [3,2,1,0,0,1,0,1,2]},
    # Healthcare
    {"n": "Doctor / Physician",      "cat": "Healthcare",            "w": [2,2,3,3,2,1,3,2,1]},
    {"n": "Surgeon",                 "cat": "Healthcare",            "w": [3,1,3,1,1,1,3,1,1]},
    {"n": "Psychologist",            "cat": "Healthcare",            "w": [2,1,1,3,2,3,2,3,2]},
    {"n": "Psychiatrist",            "cat": "Healthcare",            "w": [2,2,2,3,2,3,2,2,2]},
    {"n": "Public Health",           "cat": "Healthcare",            "w": [2,2,2,3,2,1,1,2,2]},
    {"n": "Nurse / Paramedic",       "cat": "Healthcare",            "w": [1,1,2,3,2,1,3,2,1]},
    {"n": "Pharmacist",              "cat": "Healthcare",            "w": [3,2,1,1,1,1,1,1,1]},
    # Engineering & Tech
    {"n": "Software Engineer",       "cat": "Engineering & Tech",    "w": [3,2,1,0,0,1,1,1,3]},
    {"n": "AI / ML Engineer",        "cat": "Engineering & Tech",    "w": [3,3,1,0,1,2,1,0,3]},
    {"n": "Cybersecurity Analyst",   "cat": "Engineering & Tech",    "w": [3,3,1,0,1,1,2,1,2]},
    {"n": "Product Manager",         "cat": "Engineering & Tech",    "w": [2,2,3,2,0,1,2,3,2]},
    {"n": "Civil Engineer",          "cat": "Engineering & Tech",    "w": [2,1,2,0,1,0,1,1,1]},
    {"n": "Mechanical Engineer",     "cat": "Engineering & Tech",    "w": [3,2,1,0,0,0,1,0,2]},
    {"n": "UX / UI Designer",        "cat": "Engineering & Tech",    "w": [1,1,1,3,0,2,1,1,3]},
    # Business & Finance
    {"n": "Management Consultant",   "cat": "Business & Finance",    "w": [3,3,2,1,0,1,2,3,2]},
    {"n": "Investment Banker",       "cat": "Business & Finance",    "w": [3,2,3,0,0,0,3,2,1]},
    {"n": "Chartered Accountant",    "cat": "Business & Finance",    "w": [3,2,1,0,1,1,1,1,1]},
    {"n": "Entrepreneur",            "cat": "Business & Finance",    "w": [2,1,3,1,1,2,3,2,3]},
    {"n": "Financial Analyst",       "cat": "Business & Finance",    "w": [3,3,2,0,0,1,1,1,1]},
    {"n": "Marketing Manager",       "cat": "Business & Finance",    "w": [1,1,2,2,0,1,1,3,2]},
    {"n": "HR Manager",              "cat": "Business & Finance",    "w": [1,1,2,3,1,2,1,3,1]},
    # Law & Governance
    {"n": "Lawyer / Advocate",       "cat": "Law & Governance",      "w": [2,3,2,2,3,1,2,3,1]},
    {"n": "Judge",                   "cat": "Law & Governance",      "w": [2,3,3,2,3,2,2,2,0]},
    {"n": "Policy Analyst",          "cat": "Law & Governance",      "w": [3,3,2,2,2,1,1,2,2]},
    {"n": "Civil Services (IAS)",    "cat": "Law & Governance",      "w": [2,2,3,2,3,1,3,2,1]},
    {"n": "Legal Researcher",        "cat": "Law & Governance",      "w": [3,3,1,1,2,1,0,1,2]},
    {"n": "Diplomat",                "cat": "Law & Governance",      "w": [1,2,3,3,2,2,2,3,1]},
    # Media & Communication
    {"n": "Journalist",              "cat": "Media & Communication",  "w": [2,3,1,2,2,1,2,3,3]},
    {"n": "Content Creator",         "cat": "Media & Communication",  "w": [0,0,1,1,0,1,1,3,3]},
    {"n": "Film Director",           "cat": "Media & Communication",  "w": [1,1,3,3,1,2,2,2,3]},
    {"n": "Public Relations",        "cat": "Media & Communication",  "w": [0,1,2,2,1,1,2,3,1]},
    {"n": "Advertising Creative",    "cat": "Media & Communication",  "w": [1,1,1,2,0,1,1,3,3]},
    # Education & Social
    {"n": "Teacher / Professor",     "cat": "Education & Social",    "w": [2,1,1,3,2,2,1,3,2]},
    {"n": "School Counsellor",       "cat": "Education & Social",    "w": [1,1,1,3,2,3,2,3,1]},
    {"n": "Social Worker",           "cat": "Education & Social",    "w": [0,1,2,3,3,2,2,2,1]},
    {"n": "NGO / Development",       "cat": "Education & Social",    "w": [1,1,2,3,3,1,2,2,2]},
    {"n": "Education Researcher",    "cat": "Education & Social",    "w": [3,2,0,2,1,2,0,1,3]},
    # Creative & Design
    {"n": "Architect",               "cat": "Creative & Design",     "w": [2,1,1,1,0,1,0,1,3]},
    {"n": "Visual Designer",         "cat": "Creative & Design",     "w": [0,0,1,1,0,1,0,1,3]},
    {"n": "Fashion Designer",        "cat": "Creative & Design",     "w": [0,0,1,2,0,1,1,1,3]},
    {"n": "Game Designer",           "cat": "Creative & Design",     "w": [2,1,1,2,0,1,1,0,3]},
    {"n": "Industrial Designer",     "cat": "Creative & Design",     "w": [2,1,1,1,0,1,0,0,3]},
    # Emerging & Future
    {"n": "AI Ethics Researcher",    "cat": "Emerging & Future",     "w": [2,3,1,2,3,2,0,1,3]},
    {"n": "Climate Tech",            "cat": "Emerging & Future",     "w": [2,2,2,1,2,1,1,1,3]},
    {"n": "Blockchain Developer",    "cat": "Emerging & Future",     "w": [3,2,1,0,0,1,1,0,2]},
    {"n": "Space Technologist",      "cat": "Emerging & Future",     "w": [3,2,1,0,0,1,2,0,3]},
    {"n": "Biotech Entrepreneur",    "cat": "Emerging & Future",     "w": [2,1,3,1,1,2,3,2,3]},
    {"n": "Sustainability Consult.", "cat": "Emerging & Future",     "w": [2,2,2,2,2,1,1,2,2]},
    {"n": "Digital Health Innovator","cat": "Emerging & Future",     "w": [2,1,2,3,1,1,2,1,3]},
    {"n": "Robotics Engineer",       "cat": "Emerging & Future",     "w": [3,2,1,0,0,1,1,0,3]},
]

# Stream → Career Category mapping
STREAM_MAP = {
    "Science":    ["Science & Research", "Engineering & Tech", "Healthcare"],
    "Commerce":   ["Business & Finance"],
    "Humanities": ["Education & Social", "Law & Governance", "Media & Communication"],
}


# ============================================================
# STAGE FUNCTIONS
# ============================================================

def stage1_weighted_fit(scores: list, weights: list) -> float:
    num = sum(s * w for s, w in zip(scores, weights))
    den = sum(10 * w for w in weights)
    return num / den if den > 0 else 0


def stage2_cosine_similarity(scores: list, weights: list) -> float:
    ideal = [w * 8.5 for w in weights]
    student = [w * s for w, s in zip(weights, scores)]
    dot = sum(a * b for a, b in zip(student, ideal))
    mag_a = math.sqrt(sum(x**2 for x in student))
    mag_b = math.sqrt(sum(x**2 for x in ideal))
    return dot / (mag_a * mag_b) if mag_a > 0 and mag_b > 0 else 0


def stage3_gate_check(scores: list, weights: list) -> float:
    penalty = 1.0
    for s, w in zip(scores, weights):
        if w == 3:
            if s < 4:
                penalty *= 0.70
            elif s < 6:
                penalty *= 0.90
    return penalty


def stage4_synergy(scores: list, weights: list) -> float:
    bonus = 0.0
    for syn in SYNERGIES:
        d1, d2 = syn["dims"]
        if scores[d1] >= 7 and scores[d2] >= 7 and (weights[d1] >= 1 or weights[d2] >= 1):
            relevance = max(weights[d1], weights[d2]) / 3
            bonus += relevance * 0.15
    return min(bonus, 0.45)


def stage5_confidence(scores: list, weights: list, evidence_flags: list,
                      session_depth: str = "Deep") -> float:
    depth_mult = {"Deep": 1.0, "Moderate": 0.85, "Surface": 0.6}.get(session_depth, 0.85)
    crit_dims = [i for i, w in enumerate(weights) if w >= 2]
    if not crit_dims:
        return depth_mult
    assessed = sum(1 for i in crit_dims if evidence_flags[i] and evidence_flags[i][0])
    coverage = assessed / len(crit_dims)
    return max(0.6, coverage * depth_mult)


def stage6_evidence(weights: list, key_moments: list) -> Optional[dict]:
    crit_dims = [i for i, w in enumerate(weights) if w >= 2]
    best, best_n = None, 0
    for m in key_moments:
        overlap = len(set(m.get("dims", [])) & set(crit_dims))
        if overlap > best_n:
            best_n = overlap
            best = m
    return best


def detect_active_synergies(scores: list) -> list:
    return [
        {"name": syn["name"], "desc": syn["desc"], "dims": syn["dims"], "active": True}
        for syn in SYNERGIES
        if scores[syn["dims"][0]] >= 7 and scores[syn["dims"][1]] >= 7
    ]


def compute_session_depth(turn_count: int, duration_sec: int, engagement: float) -> str:
    if turn_count < 8 or duration_sec < 180 or engagement < 40:
        return "Surface"
    elif turn_count >= 15 and duration_sec >= 300 and engagement >= 70:
        return "Deep"
    else:
        return "Moderate"


def score_to_band(score: int) -> str:
    if score >= 9:
        return "Advanced"
    elif score >= 7:
        return "Proficient"
    elif score >= 4:
        return "Developing"
    else:
        return "Emerging"


def seconds_to_display(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}m {s:02d}s"


# ============================================================
# MAIN: RUN FULL 6-STAGE PIPELINE
# ============================================================

def score_all_careers(
    dimension_scores: list[int],
    evidence_flags: list[list[bool]],
    key_moments: list[dict],
    session_depth: str = "Deep",
) -> dict[str, Any]:
    """Run the full 6-stage pipeline on all 55 careers.

    Returns dict with ranked, top_matches, synergies, streams, active_synergy_names.
    """
    S = dimension_scores
    active_syn = detect_active_synergies(S)
    active_syn_names = [s["name"] for s in active_syn]

    results = []
    for career in CAREERS:
        w = career["w"]
        fit     = stage1_weighted_fit(S, w)
        shape   = stage2_cosine_similarity(S, w)
        gate    = stage3_gate_check(S, w)
        syn_val = stage4_synergy(S, w)
        conf    = stage5_confidence(S, w, evidence_flags, session_depth)
        ev      = stage6_evidence(w, key_moments)

        raw = (0.40 * fit) + (0.25 * shape) + (0.15 * syn_val) + (0.20 * fit * gate)
        composite = round(raw * conf * 100)

        dim_contrib = [(i, w[i], w[i] * S[i]) for i in range(9) if w[i] >= 2]
        dim_contrib.sort(key=lambda x: -x[2])
        strong_dims = [DIM_NAMES[d[0]] for d in dim_contrib[:3]]

        gaps = [(i, w[i] * (10 - S[i])) for i in range(9) if w[i] >= 2 and S[i] < 7]
        gaps.sort(key=lambda x: -x[1])
        gap_dim = DIM_NAMES[gaps[0][0]] if gaps else None

        career_syns = [
            s["name"] for s in SYNERGIES
            if S[s["dims"][0]] >= 7 and S[s["dims"][1]] >= 7
            and (w[s["dims"][0]] >= 1 or w[s["dims"][1]] >= 1)
        ]

        conf_label = "High" if conf >= 0.9 else "Med" if conf >= 0.75 else "Low"

        results.append({
            "name": career["n"],
            "category": career["cat"],
            "composite": composite,
            "fit": round(fit * 100),
            "shape": round(shape * 100),
            "confidence_label": conf_label,
            "strong_dims": strong_dims,
            "gap_dim": gap_dim,
            "career_synergies": career_syns,
            "evidence": ev,
        })

    results.sort(key=lambda x: -x["composite"])

    all_synergies = []
    for syn in SYNERGIES:
        active = S[syn["dims"][0]] >= 7 and S[syn["dims"][1]] >= 7
        all_synergies.append({
            "name": syn["name"],
            "desc": syn["desc"],
            "dims": syn["dims"],
            "active": active,
        })

    streams = []
    for stream_name, cats in STREAM_MAP.items():
        matching = [r for r in results if r["category"] in cats][:5]
        avg = sum(r["composite"] for r in matching) / len(matching) if matching else 0
        label = "Strong" if avg >= 70 else "Viable" if avg >= 60 else "Possible"
        streams.append({"stream": stream_name, "label": label, "score": round(avg)})
    streams.sort(key=lambda x: -x["score"])

    return {
        "ranked": results,
        "top_matches": results[:8],
        "synergies": all_synergies,
        "streams": streams,
        "active_synergy_names": ", ".join(active_syn_names) or "None detected",
    }
