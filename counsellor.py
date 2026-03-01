"""GPT-5.2 powered counsellor session logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import os

from openai import OpenAI


SYSTEM_PROMPT = (
    "You are an experienced, warm Indian school counsellor speaking to a student (class 9-12). "
    "Be empathetic, non-judgmental, and culturally aware of Indian school and family dynamics. "
    "Ask open-ended questions, especially 'why' and 'how did that make you feel.' "
    "Gently challenge surface-level answers and invite deeper reflection. "
    "Quote the student's own words back to them when relevant. "
    "Refer to facial expressions and voice patterns when provided, and point out discrepancies "
    "(e.g., 'You said you are fine but looked tense'). "
    "Track consistency across rounds and probe hesitation points. "
    "Get progressively deeper with each round. "
    "Never diagnose or label; only observe and recommend. "
    "Keep your response concise, supportive, and focused on the student's lived experience."
)


@dataclass
class CounsellorSession:
    case_study: Dict[str, Any]
    student_info: Dict[str, Any]
    history: List[Dict[str, Any]] = field(default_factory=list)
    counsellor_notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=api_key)

    def add_response(
        self,
        round_num: int,
        transcription: str,
        face_data: Optional[Dict[str, Any]],
        voice_data: Optional[Dict[str, Any]],
    ) -> str:
        """
        Add a student response, send to GPT-5.2, and return the counsellor's follow-up.
        """
        entry = {
            "round_num": round_num,
            "transcription": transcription,
            "face_data": face_data or {},
            "voice_data": voice_data or {},
        }
        self.history.append(entry)

        # Build clean prompt
        case_title = self.case_study.get("title", "")
        case_text = self.case_study.get("scenario_text", "")[:500]
        student_name = self.student_info.get("name", "Student")
        
        prior_summary = ""
        for pr in self.history[:-1]:
            prior_summary += f"Round {pr['round_num']}: Student said: \"{pr['transcription']}\"\n"
        
        face_note = ""
        if face_data and face_data.get("summary", {}).get("dominant_emotion"):
            face_note = f"Facial expression: {face_data['summary']['dominant_emotion']}. "
        
        voice_note = ""
        if voice_data and voice_data.get("speech_rate", {}).get("words_per_minute"):
            voice_note = f"Speech rate: {voice_data['speech_rate']['words_per_minute']} WPM. "
        
        user_prompt = (
            f"Case study: {case_title}\n"
            f"Student: {student_name} (Class {self.student_info.get('class', '')})\n"
            f"Round: {round_num}/4\n\n"
        )
        if prior_summary:
            user_prompt += f"Previous rounds:\n{prior_summary}\n"
        user_prompt += (
            f"Current response (Round {round_num}): \"{transcription}\"\n"
            f"{face_note}{voice_note}\n"
            "Craft a warm, empathetic follow-up. Reference what the student said. "
            "Ask probing \'why\' questions. Go deeper than previous rounds."
        )

        try:
            response = self.client.chat.completions.create(
                model="gpt-5.2",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.6,
                max_completion_tokens=300,
            )
            counsellor_text = response.choices[0].message.content.strip()
            self.counsellor_notes.append(counsellor_text)
            return counsellor_text
        except Exception as exc:  # noqa: BLE001
            fallback = (
                "I hear you. Can you tell me more about why that felt that way for you, "
                "and what was going through your mind in that moment?"
            )
            self.counsellor_notes.append(
                f"API error: {type(exc).__name__}: {exc}. Fallback used."
            )
            return fallback

    def get_all_context(self) -> Dict[str, Any]:
        """Return all accumulated data for profile generation."""
        return {
            "case_study": self.case_study,
            "student_info": self.student_info,
            "rounds": self.history,
            "counsellor_notes": self.counsellor_notes,
        }
