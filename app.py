import asyncio
import inspect
import os
import tempfile
import time
from datetime import datetime

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from utils import (
    create_pdf_report,
    extract_audio_from_video,
    format_duration,
    get_emotion_color,
    save_frames_from_video,
)

import counsellor
import face_analyzer
import voice_analyzer
import transcriber
import profile_generator
import case_studies

load_dotenv()

try:
    from streamlit_webrtc import WebRtcMode, webrtc_streamer

    WEBRTC_AVAILABLE = True
except Exception:
    WEBRTC_AVAILABLE = False


MAX_ROUNDS = 4


st.set_page_config(page_title="CounselAI", layout="wide")

CUSTOM_CSS = """
<style>
:root {
  --primary: #1e6f87;
  --secondary: #2e9b83;
  --soft: #e8f6f5;
  --text: #17323b;
  --muted: #5c7c86;
  --card: #ffffff;
}

.main {
  background: linear-gradient(135deg, #f2fbfa 0%, #f7fbff 45%, #edf6f9 100%);
}

.card {
  background: var(--card);
  border-radius: 16px;
  padding: 20px 24px;
  box-shadow: 0 10px 24px rgba(30, 111, 135, 0.08);
  border: 1px solid rgba(30, 111, 135, 0.08);
}

.card-title {
  font-weight: 700;
  font-size: 18px;
  color: var(--primary);
  margin-bottom: 12px;
}

.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: #ffffff;
}

.chat-bubble {
  background: #e9f7f4;
  padding: 14px 18px;
  border-radius: 16px;
  border-left: 6px solid var(--secondary);
  color: var(--text);
}

.section-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--primary);
  margin-bottom: 8px;
}
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def init_session_state():
    defaults = {
        "page": 1,
        "rounds": [],
        "current_round": 1,
        "student_info": {},
        "case_study": None,
        "start_time": None,
        "profile_data": None,
        "cross_validation": None,
        "counsellor_session": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def fetch_case_studies():
    if hasattr(case_studies, "get_case_studies"):
        return case_studies.get_case_studies()
    if hasattr(case_studies, "CASE_STUDIES"):
        return case_studies.CASE_STUDIES
    return []


def suggest_case_study(class_level, studies):
    if hasattr(case_studies, "get_case_study_for_class"):
        return case_studies.get_case_study_for_class(class_level)
    for study in studies:
        if class_level in study.get("class_levels", []):
            return study
    return studies[0] if studies else None


def reset_session():
    for key in list(st.session_state.keys()):
        if key not in {"page"}:
            st.session_state.pop(key, None)
    init_session_state()
    st.session_state.page = 1


def score_color(score: int) -> str:
    if score >= 75:
        return "#2ecc71"
    if score >= 55:
        return "#f1c40f"
    return "#e74c3c"


init_session_state()


def get_counsellor_session() -> counsellor.CounsellorSession:
    session = st.session_state.counsellor_session
    if session is None:
        session = counsellor.CounsellorSession(
            case_study=st.session_state.case_study or {},
            student_info=st.session_state.student_info or {},
        )
        st.session_state.counsellor_session = session
    return session

# Sidebar
with st.sidebar:
    st.markdown("### Session")
    round_display = st.session_state.current_round
    if st.session_state.page < 3:
        round_display = 0
    st.write(f"Progress: Round {round_display}/{MAX_ROUNDS}")

    if st.session_state.start_time:
        elapsed = int(time.time() - st.session_state.start_time)
        st.write(f"Timer: {format_duration(elapsed)}")
    else:
        st.write("Timer: 0m 0s")

    student_info = st.session_state.student_info or {}
    st.write(f"Student: {student_info.get('name', '—')}")
    class_label = student_info.get("class", "—")
    section_label = student_info.get("section", "")
    st.write(f"Class: {class_label} {section_label}")

    case_study = st.session_state.case_study or {}
    st.write(f"Case Study: {case_study.get('title', '—')}")


# Page routing
if st.session_state.page == 1:
    st.markdown("<div class='section-title'>Student Entry</div>", unsafe_allow_html=True)
    st.title("🧠 CounselAI — Student Counselling Platform")

    with st.container():
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        with st.form("student_entry"):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Name")
                class_level = st.selectbox("Class", [9, 10, 11, 12])
                section = st.text_input("Section")
            with col2:
                school = st.text_input("School Name")
                age = st.number_input("Age", min_value=10, max_value=20, step=1)
            start = st.form_submit_button("Start Session")

        st.markdown("</div>", unsafe_allow_html=True)

    if start:
        st.session_state.student_info = {
            "name": name,
            "class": class_level,
            "section": section,
            "school": school,
            "age": age,
        }
        st.session_state.start_time = time.time()
        st.session_state.current_round = 1
        st.session_state.rounds = []
        st.session_state.page = 2
        st.rerun()


elif st.session_state.page == 2:
    st.markdown("<div class='section-title'>Case Study</div>", unsafe_allow_html=True)
    studies = fetch_case_studies()
    class_level = st.session_state.student_info.get("class")
    suggested = suggest_case_study(class_level, studies)

    if not studies:
        st.warning("No case studies available.")
        if st.button("Back to Student Entry"):
            st.session_state.page = 1
            st.rerun()
        st.stop()

    titles = [study["title"] for study in studies]
    default_index = titles.index(suggested["title"]) if suggested in studies else 0

    selected_title = st.selectbox("Select a case study", titles, index=default_index)
    selected = next(study for study in studies if study["title"] == selected_title)
    st.session_state.case_study = selected

    summary_text = selected.get("summary") or selected.get("scenario_text", "")
    prompt_text = selected.get("prompt")
    if not prompt_text:
        angles = selected.get("probing_angles", [])
        prompt_text = "; ".join(angles) if angles else ""

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown(f"<div class='card-title'>{selected['title']}</div>", unsafe_allow_html=True)
    st.write(summary_text)
    if prompt_text:
        st.markdown(f"**Prompt:** {prompt_text}")
    st.markdown("</div>", unsafe_allow_html=True)

    if st.button("I am ready to respond"):
        st.session_state.page = 3
        st.rerun()


elif st.session_state.page == 3:
    round_index = st.session_state.current_round
    st.markdown(f"<div class='section-title'>Round {round_index}: Share your thoughts</div>", unsafe_allow_html=True)

    if round_index > 1 and st.session_state.rounds:
        prev_response = st.session_state.rounds[-1].get("counsellor_response", "")
        st.markdown("#### Counsellor's follow-up")
        st.markdown(f"<div class='chat-bubble'>{prev_response}</div>", unsafe_allow_html=True)

    capture_options = []
    if WEBRTC_AVAILABLE:
        capture_options.append("Live camera")
    capture_options.extend(["Upload files", "Text only"])

    capture_mode = st.radio("Response mode", capture_options, horizontal=True)

    transcription_text = ""
    uploaded_video = None
    uploaded_audio = None
    camera_image = None
    audio_capture = None

    if capture_mode == "Live camera":
        st.info("Live mode uses your webcam and mic. Upload a file if you want analysis recorded.")
        webrtc_streamer(
            key="counselai-webrtc",
            mode=WebRtcMode.SENDRECV,
            media_stream_constraints={"video": True, "audio": True},
        )
        uploaded_video = st.file_uploader("Optional video upload", type=["mp4", "mov", "webm"])
        uploaded_audio = st.file_uploader("Optional audio upload", type=["wav", "mp3", "m4a"])
        transcription_text = st.text_area("Optional text response")
    elif capture_mode == "Upload files":
        uploaded_video = st.file_uploader("Upload a video file", type=["mp4", "mov", "webm"])
        uploaded_audio = st.file_uploader("Or upload an audio file", type=["wav", "mp3", "m4a"])
        if hasattr(st, "camera_input") or hasattr(st, "audio_input"):
            with st.expander("Quick capture (optional)"):
                if hasattr(st, "camera_input"):
                    camera_image = st.camera_input("Take a quick snapshot")
                if hasattr(st, "audio_input"):
                    audio_capture = st.audio_input("Record audio")
        transcription_text = st.text_area("Optional text response")
    else:
        st.info("Text-only mode. Your typed response will be used for analysis.")
        transcription_text = st.text_area("Your response", height=140)

    st.markdown("---")
    col_submit, col_end = st.columns([1, 1])
    with col_submit:
        submit = st.button("Submit Response", type="primary")
    with col_end:
        end_session = st.button("End Session")

    if end_session:
        st.session_state.page = 4
        st.rerun()

    if submit:
        if not transcription_text and not uploaded_video and not uploaded_audio and not audio_capture:
            st.warning("Please provide a response via text or upload media.")
            st.stop()

        progress = st.progress(0)
        status = st.empty()

        def advance(text, value):
            status.info(text)
            progress.progress(value)
            time.sleep(0.4)

        advance("Transcribing audio...", 20)

        audio_path = None
        video_path = None
        frames_dir = None

        if uploaded_video:
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_video.name)[1]) as tmp:
                tmp.write(uploaded_video.read())
                video_path = tmp.name
            audio_path = extract_audio_from_video(video_path)
            frames_dir = tempfile.mkdtemp(prefix="frames_")
            save_frames_from_video(video_path, frames_dir, interval=2)
        elif uploaded_audio:
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_audio.name)[1]) as tmp:
                tmp.write(uploaded_audio.read())
                audio_path = tmp.name
        elif audio_capture:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp.write(audio_capture.read())
                audio_path = tmp.name

        if camera_image and not frames_dir:
            frames_dir = tempfile.mkdtemp(prefix="frames_")
            image_path = os.path.join(frames_dir, "snapshot.jpg")
            with open(image_path, "wb") as handle:
                handle.write(camera_image.read())

        transcription = transcription_text.strip()
        if not transcription and audio_path:
            transcription_result = transcriber.transcribe_audio(audio_path)
            if isinstance(transcription_result, dict):
                transcription = transcription_result.get("text", "").strip()
            else:
                transcription = str(transcription_result or "").strip()
        if not transcription:
            transcription = "(No transcription available)"

        advance("Analyzing facial expressions...", 45)
        face_data = face_analyzer.analyze_frames(frames_dir) if frames_dir else {}

        advance("Analyzing voice patterns...", 70)
        voice_data = voice_analyzer.analyze_audio(audio_path) if audio_path else {}

        advance("Counsellor is thinking...", 90)
        session = get_counsellor_session()
        response_text = session.add_response(round_index, transcription, face_data, voice_data)
        if inspect.iscoroutine(response_text):
            response_text = asyncio.run(response_text)
        advance("Done", 100)

        st.session_state.rounds.append(
            {
                "round": round_index,
                "transcription": transcription,
                "face_data": face_data,
                "voice_data": voice_data,
                "counsellor_response": response_text,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        st.markdown("#### Counsellor response")
        st.markdown(f"<div class='chat-bubble'>{response_text}</div>", unsafe_allow_html=True)

        if round_index >= MAX_ROUNDS:
            st.session_state.page = 4
        else:
            st.session_state.current_round += 1
        st.rerun()

    if st.session_state.rounds:
        st.markdown("### Session highlights")
        for item in st.session_state.rounds:
            st.markdown(
                f"**Round {item['round']}** - {item['transcription'][:120]}",
            )


elif st.session_state.page == 4:
    st.markdown("<div class='section-title'>Profile Report</div>", unsafe_allow_html=True)

    session = get_counsellor_session()
    session_data = session.get_all_context()

    if st.session_state.profile_data is None:
        with st.spinner("Generating comprehensive profile..."):
            profile_data = profile_generator.generate_profile(session_data)
            cross_val = profile_generator.cross_validate(session_data, profile_data)
            st.session_state.profile_data = profile_data
            st.session_state.cross_validation = cross_val

    profile_data = st.session_state.profile_data
    cross_val = st.session_state.cross_validation

    scores = profile_data.get("scores", {})
    if scores:
        st.markdown("### Core Scores")
        cols = st.columns(len(scores))
        for col, (label, value) in zip(cols, scores.items()):
            color = score_color(int(value))
            col.metric(label, value)
            col.markdown(f"<span class='badge' style='background:{color}'>Score</span>", unsafe_allow_html=True)

    st.markdown("### Summary")
    st.write(profile_data.get("summary", ""))

    st.markdown("### Highlights")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Key Traits")
        for trait in profile_data.get("traits", []):
            st.write(f"- {trait}")
    with col2:
        st.markdown("#### Key Quotes")
        for quote in profile_data.get("key_quotes", []):
            st.markdown(f"> {quote}")

    st.markdown("### Emotion Timeline")
    timeline = profile_data.get("emotion_timeline", [])
    if timeline:
        rounds = [item["round"] for item in timeline]
        intensities = [item["intensity"] for item in timeline]
        colors = [get_emotion_color(item["emotion"]) for item in timeline]
        fig = go.Figure(
            data=go.Scatter(
                x=rounds,
                y=intensities,
                mode="lines+markers",
                line=dict(color="#1e6f87"),
                marker=dict(size=10, color=colors),
            )
        )
        fig.update_layout(
            xaxis_title="Round",
            yaxis_title="Intensity",
            height=300,
            margin=dict(l=20, r=20, t=30, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Voice Metrics")
    voice_metrics = profile_data.get("voice_metrics", {})
    if voice_metrics:
        fig_voice = go.Figure(
            data=[
                go.Bar(
                    x=list(voice_metrics.keys()),
                    y=list(voice_metrics.values()),
                    marker_color="#2e9b83",
                )
            ]
        )
        fig_voice.update_layout(height=280, margin=dict(l=20, r=20, t=30, b=20))
        st.plotly_chart(fig_voice, use_container_width=True)

    with st.expander("Cross-validation"):
        st.write(f"Alignment: {cross_val.get('alignment', 'N/A')}")
        st.write(f"Confidence: {cross_val.get('confidence', 'N/A')}%")
        st.write(cross_val.get("notes", ""))

    with st.expander("Recommendations"):
        for rec in profile_data.get("recommendations", []):
            st.write(f"- {rec}")

    pdf_bytes = create_pdf_report(profile_data, st.session_state.student_info)
    st.download_button(
        "Download PDF Report",
        data=pdf_bytes,
        file_name="counselai_report.pdf",
        mime="application/pdf",
    )

    if st.button("Start New Session"):
        reset_session()
        st.rerun()
