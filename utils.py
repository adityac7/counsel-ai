import os
from typing import List

import cv2
import numpy as np
from fpdf import FPDF
from pydub import AudioSegment


def extract_audio_from_video(video_path: str) -> str:
    """Extract audio from a video file and return the new audio path."""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)

    audio_path = os.path.splitext(video_path)[0] + ".wav"
    try:
        video_audio = AudioSegment.from_file(video_path)
        video_audio.export(audio_path, format="wav")
    except Exception:
        # Best-effort fallback; return original if extraction fails
        return video_path
    return audio_path


def save_frames_from_video(video_path: str, output_dir: str, interval: int = 2) -> List[str]:
    """Save frames from a video at a fixed interval (in seconds)."""
    os.makedirs(output_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frame_interval = int(fps * interval)
    frame_paths = []
    frame_idx = 0
    saved_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_interval == 0:
            frame_path = os.path.join(output_dir, f"frame_{saved_idx:04d}.jpg")
            cv2.imwrite(frame_path, frame)
            frame_paths.append(frame_path)
            saved_idx += 1
        frame_idx += 1

    cap.release()
    return frame_paths


def format_duration(seconds: int) -> str:
    minutes = seconds // 60
    rem = seconds % 60
    return f"{minutes}m {rem}s"


def create_pdf_report(profile_data: dict, student_info: dict) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.set_font("Helvetica", style="B", size=16)
    pdf.cell(0, 10, "CounselAI - Student Profile Report", ln=True)

    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, f"Student: {student_info.get('name', 'N/A')}", ln=True)
    pdf.cell(0, 8, f"Class: {student_info.get('class', 'N/A')} {student_info.get('section', '')}", ln=True)
    pdf.cell(0, 8, f"School: {student_info.get('school', 'N/A')}", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", style="B", size=12)
    pdf.cell(0, 8, "Profile Summary", ln=True)
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, profile_data.get("summary", "No summary available."))

    scores = profile_data.get("scores", {})
    if scores:
        pdf.ln(2)
        pdf.set_font("Helvetica", style="B", size=12)
        pdf.cell(0, 8, "Scores", ln=True)
        pdf.set_font("Helvetica", size=11)
        for key, value in scores.items():
            pdf.cell(0, 6, f"{key}: {value}", ln=True)

    traits = profile_data.get("traits", [])
    if traits:
        pdf.ln(2)
        pdf.set_font("Helvetica", style="B", size=12)
        pdf.cell(0, 8, "Key Traits", ln=True)
        pdf.set_font("Helvetica", size=11)
        for trait in traits:
            pdf.cell(0, 6, f"- {trait}", ln=True)

    return pdf.output(dest="S").encode("latin-1")


def get_emotion_color(emotion: str) -> str:
    palette = {
        "happy": "#2ecc71",
        "neutral": "#3498db",
        "sad": "#f1c40f",
        "angry": "#e74c3c",
        "fear": "#9b59b6",
        "surprise": "#1abc9c",
        "disgust": "#e67e22",
    }
    return palette.get(emotion.lower(), "#95a5a6")
