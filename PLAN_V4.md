# CounselAI v4 — SOTA Plan

## Root Causes Found
1. MediaRecorder.start() has no timeslice → chunks only on stop()
2. endSession() calls pc.close() BEFORE recorder.stop() → media stream dead → empty recording
3. EBML header parsing fails on upload → ffmpeg can't extract frames/audio
4. Profile DOES generate from transcript alone — frontend may not render it

## Fixes Required

### Fix 1: Recording Pipeline
- recorder.start(1000) — chunk every 1 second
- In endSession: FIRST stop recorder (await onstop), THEN close WebRTC
- Order: stop recorder → wait for blob → stop media tracks → close pc

### Fix 2: AI Neutrality (CRITICAL)
Current instructions bias the student:
- "Challenge surface-level answers" → BIASING
- "Interesting, but what if..." → LEADING
- "I sense hesitation" → INTERPRETING

New instruction philosophy:
- NEVER praise, critique, or interpret during session
- ONLY ask questions: "Can you tell me more?", "What makes you say that?", "What else comes to mind?"
- Be warm but completely neutral — like a mirror, not a judge
- All analysis/interpretation happens ONLY in the post-session report
- Think: Socratic method + motivational interviewing

### Fix 3: Comprehensive Report
Post-session report should include:
1. **Personality Snapshot** — traits observed, communication style, decision-making approach
2. **Cognitive Profile** — critical thinking score, perspective-taking, moral reasoning stage
3. **Emotional Profile** — EQ score, empathy level, stress response
4. **Behavioral Insights** — confidence, response patterns
5. **Key Moments** — specific quotes with analysis of what they reveal
6. **Cross-Validation** — MiniMax second opinion
7. **Recommendations** — actionable items for counsellor/parent

### Fix 4: Report UI
- Score cards in a grid (teal accent)
- Each section expandable
- Key quotes highlighted with reasoning
- "Why we scored this" explanation for each metric
- Download as PDF option (future)

## File Changes
1. templates/live.html — Fix recorder, fix endSession order, improve summary rendering
2. realtime_server.py — Rewrite counsellor instructions to be neutral
3. profile_generator.py — Verify report structure matches new UI expectations
