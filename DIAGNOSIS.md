# CounselAI Transcript Bug Diagnosis

Date: 2026-03-01

## Summary of Findings
- The transcript is rendered during the session via DOM elements created in `addEntry()` in `templates/live.html`.
- The analysis request at session end builds the transcript by querying `transcriptEl.querySelectorAll('.entry')` and serializing the `.body` text.
- Server logs show `transcript entries received: 0`, which means the client sent an empty transcript array. This aligns with `querySelectorAll('.entry')` returning zero nodes at end-session.

## Data Flow Trace (per `templates/live.html`)
- **Where `.entry` elements are created**: `addEntry(role, text)` creates `<div class="entry {role}">` with a `.tag` and `.body`, then appends to `#transcript`.
- **What calls `addEntry`**: `handleEventMessage`:
  - `response.audio_transcript.delta` → creates/updates AI entry.
  - `conversation.item.input_audio_transcription.completed` → adds student entry.
- **Data-channel events required**:
  - AI transcript events (`response.audio_transcript.delta` / `.done`).
  - Student transcript event (`conversation.item.input_audio_transcription.completed`).
- **Does `#transcript` contain `.entry` children?**
  - It should during the live session (the user sees transcript). However, end-session extraction reports 0 entries.

## Checks
- **Class name mismatch**: `addEntry` uses `className = 'entry ${role}'` and extraction uses `.entry` → class names match.
- **`transcriptEl` reference**: Bound once to `#transcript` and never re-assigned. Not obviously wrong.
- **`showScreen('summary')` side effects**: Only toggles `.hidden`; should not detach or clear DOM.

## Most Likely Root Cause
The DOM-based extraction is brittle. In the failing environment, `querySelectorAll('.entry')` returns 0 even though text is visible. This suggests either:
- The visible transcript isn’t actually built from `.entry` nodes in that environment (e.g., a different rendering path or DOM replacement), or
- The live transcript is present but the query is performed against an emptied/rehydrated container.

Given the evidence, the safest fix is to **decouple transcript capture from DOM queries** by maintaining an in-memory transcript array as entries are added and using that for both analysis and summary rendering. This guarantees the transcript payload even if DOM querying fails.

## Additional Requirements Noted
- Update counsellor instructions to ask one question at a time.
- Ensure transcript shows both AI and student in real-time (already via `addEntry`, will reinforce by centralizing transcript writes).
- Summary page must show the full transcript (will render from the in-memory transcript array).
