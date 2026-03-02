import os
import shutil
import subprocess
from typing import List

from fpdf import FPDF


def _find_ffmpeg_binary() -> str:
    """Resolve ffmpeg binary from PATH, then common fallback locations."""
    candidates = [
        shutil.which("ffmpeg"),
        "/home/linuxbrew/.linuxbrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


def extract_audio_from_video(video_path: str) -> str:
    """Extract audio from a video file and return the new audio path."""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(video_path)
    if os.path.getsize(video_path) == 0:
        print(f"[utils] Warning: input video is empty: {video_path}")
        return ""

    ffmpeg_bin = _find_ffmpeg_binary()
    if not ffmpeg_bin:
        print("[utils] Warning: ffmpeg not found for audio extraction")
        return ""

    audio_path = os.path.splitext(video_path)[0] + ".wav"
    try:
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                video_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                audio_path,
            ],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode(errors="replace").strip()
        print(f"[utils] Warning: ffmpeg audio extraction failed: {stderr or exc}")
        return ""
    if not os.path.isfile(audio_path) or os.path.getsize(audio_path) == 0:
        print("[utils] Warning: ffmpeg produced empty audio file")
        return ""
    return audio_path


def save_frames_from_video(video_path: str, output_dir: str, interval: int = 2) -> List[str]:
    """Save frames from a video at a fixed interval (in seconds) using ffmpeg."""
    if not os.path.isfile(video_path):
        print(f"[utils] Warning: video file not found for frame extraction: {video_path}")
        return []
    if os.path.getsize(video_path) == 0:
        print(f"[utils] Warning: video file is empty for frame extraction: {video_path}")
        return []

    ffmpeg_bin = _find_ffmpeg_binary()
    if not ffmpeg_bin:
        print("[utils] Warning: ffmpeg not found for frame extraction")
        return []

    os.makedirs(output_dir, exist_ok=True)
    frame_interval = max(1, int(interval))
    try:
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                video_path,
                "-vf",
                f"fps=1/{frame_interval}",
                "-q:v",
                "2",
                os.path.join(output_dir, "frame_%04d.jpg"),
            ],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode(errors="replace").strip()
        print(f"[utils] Warning: ffmpeg frame extraction failed: {stderr or exc}")
        return []
    frames = sorted(
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.lower().endswith(".jpg")
    )
    if not frames:
        print("[utils] Warning: ffmpeg completed but extracted no frames")
    return frames


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
