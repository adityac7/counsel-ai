"""Post-session analysis prompt.

Used after a counselling session ends to generate a structured
analysis of the conversation — themes, emotional state, risk flags,
and recommended follow-up.
"""

POST_SESSION_ANALYSIS_PROMPT = """
You are analyzing a completed counselling session with an Indian school student (class 9-12, age 14-18).

Review the full transcript and produce a structured analysis in JSON format.

## Output Schema

```json
{
  "key_themes": [
    {
      "theme": "string — one-line theme label",
      "evidence": "string — direct quotes or specific moments from the session",
      "severity": "low | medium | high"
    }
  ],
  "emotional_state": {
    "primary_emotion": "string — dominant emotion observed (e.g., anxious, frustrated, sad, confused, hopeful)",
    "secondary_emotions": ["string — other emotions present"],
    "emotional_trajectory": "string — how their emotional state shifted during the session (e.g., 'Started guarded, opened up mid-session, became reflective by end')",
    "emotional_vocabulary": "limited | developing | articulate — how well they can name their feelings"
  },
  "behavioural_observations": {
    "engagement_level": "low | moderate | high — how actively they participated",
    "self_awareness": "low | moderate | high — can they reflect on their own patterns?",
    "decision_making_style": "impulsive | avoidant | deliberate | dependent — how they approach choices",
    "relationship_patterns": "string — how they describe and relate to others",
    "coping_strategies_mentioned": ["string — what they currently do to cope"]
  },
  "risk_assessment": {
    "risk_level": "none | low | moderate | high | critical",
    "risk_flags": ["string — specific concerns identified"],
    "protective_factors": ["string — strengths and supports they have"],
    "immediate_safety_concern": false
  },
  "indian_context_factors": {
    "academic_pressure_level": "none | mild | moderate | severe",
    "family_dynamics_concern": "none | mild | moderate | severe",
    "peer_relationship_issues": "none | mild | moderate | severe",
    "career_confusion": "none | mild | moderate | severe",
    "cultural_pressure_notes": "string — specific cultural factors at play (board exams, coaching, family expectations, etc.)"
  },
  "follow_up": {
    "recommended_actions": ["string — what should happen next"],
    "topics_for_next_session": ["string — threads worth picking up"],
    "referral_needed": false,
    "referral_type": "none | school_counsellor | psychologist | psychiatrist | helpline",
    "urgency": "routine | soon | urgent | immediate"
  },
  "session_quality": {
    "rapport_established": true,
    "student_opened_up": true,
    "key_insight_reached": "string or null — the 'aha' moment if there was one",
    "session_summary": "string — 3-4 sentence summary of what happened in the session"
  }
}
```

## Rules

- Base EVERYTHING on what was actually said in the transcript. Don't infer things that aren't there.
- Quote the student directly when citing evidence.
- Risk assessment is the most critical section. When in doubt, err on the side of caution.
- If the student mentioned self-harm, suicide, abuse, or substance use, risk_level must be at least "moderate."
- Keep the summary free of jargon. A teacher or parent should be able to read it and understand.
- Cultural context matters — what looks like "low engagement" might be a student who was taught
  not to share feelings with adults. Note this if relevant.
- Never diagnose. Say "shows signs consistent with" not "has depression/anxiety."
- The follow_up section should be actionable — not vague "continue monitoring" unless that's genuinely all that's needed.

## Transcript to Analyze
"""
