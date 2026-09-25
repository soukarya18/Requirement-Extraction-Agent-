from __future__ import annotations

import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st


# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

UPLOADS_DIR = BASE_DIR / "data" / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
SUPPORTED_EXTENSIONS = ["pdf", "docx", "doc", "txt"]


# ---------------------------------------------------------------------------
# Streamlit configuration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="SDLC Assistant Portal",
    page_icon="◇",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    :root {
        --green: #0f7a45;
        --green-dark: #075c34;
        --green-soft: #eaf6ef;
        --page: #f4f7f5;
        --border: #dce6df;
        --text: #15221b;
        --muted: #6d7a73;
        --white: #ffffff;
    }

    .stApp {
        background: var(--page);
    }

    /* Keep the portal close to the top without letting Streamlit's fixed header
       paint an opaque layer over the page content. */
    .block-container {
        padding-top: 0.35rem;
    }

    /* Hide the fixed Streamlit header so its white backdrop cannot cover the
       portal title or create unnecessary vertical space. */
    [data-testid="stHeader"] {
        display: none !important;
    }

    .dashboard-cell-text {
        width: 100%;
        color: var(--text);
        font-size: 0.9rem;
        line-height: 1.25;
        overflow-wrap: anywhere;
    }

    /* Grid-style dashboard table: one bordered container per row (header +
       data) instead of a border around every single cell, so the table
       reads as a clean grid rather than a wall of nested boxes. */
    .grid-header-cell {
        background: var(--green-soft);
        color: var(--green-dark);
        font-weight: 700;
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        padding: 0.5rem 0.7rem;
        border-radius: 8px;
        text-align: left;
        white-space: nowrap;
    }

    .grid-cell {
        display: flex;
        align-items: center;
        min-height: 2.35rem;
        color: var(--text);
        font-size: 0.92rem;
        padding: 0 0.15rem;
    }

    .grid-cell-index {
        justify-content: center;
        color: var(--muted);
        font-weight: 650;
    }

    .grid-cell-title {
        font-weight: 620;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .grid-cell-empty {
        justify-content: center;
        color: var(--muted);
    }


    .portal-title {
        font-size: 1.8rem;
        font-weight: 700;
        color: var(--text);
        margin: 0;
    }

    .portal-subtitle {
        color: var(--muted);
        margin: 0.15rem 0 0.9rem 0;
        font-size: 0.92rem;
    }

    .panel-card {
        background: var(--white);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 1rem;
        box-shadow: 0 2px 10px rgba(30, 55, 42, 0.04);
    }

    .section-title {
        color: var(--text);
        font-size: 0.92rem;
        font-weight: 700;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        margin-bottom: 0.7rem;
    }

    .artifact-card {
        background: var(--white);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 0.8rem;
        margin-bottom: 0.65rem;
    }

    .artifact-name {
        font-weight: 650;
        color: var(--text);
        font-size: 0.92rem;
    }

    .artifact-status {
        color: var(--muted);
        font-size: 0.76rem;
        margin-top: 0.15rem;
        margin-bottom: 0.45rem;
    }

    .ready {
        color: var(--green);
        font-weight: 650;
    }

    .placeholder {
        color: var(--muted);
        background: #fafcfb;
        border: 1px dashed var(--border);
        border-radius: 12px;
        padding: 1rem;
        font-size: 0.88rem;
    }

    .nav-label {
        color: var(--muted);
        font-size: 0.76rem;
        margin-bottom: 0.55rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        font-weight: 700;
    }

    .module-caption {
        display: inline-block;
        color: var(--green);
        background: var(--green-soft);
        border-radius: 999px;
        padding: 0.25rem 0.55rem;
        font-size: 0.75rem;
        font-weight: 650;
        margin-bottom: 0.55rem;
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 16px;
    }

    div[data-testid="stChatMessage"] {
        border: 1px solid var(--border);
        border-radius: 14px;
        margin-bottom: 0.55rem;
    }

    .small-note {
        color: var(--muted);
        font-size: 0.76rem;
        line-height: 1.4;
    }

    /* Give each navigation column a sticky feel without touching Streamlit's
       built-in sidebar. The exact DOM can vary slightly between Streamlit
       versions, so the navigation card itself remains usable without this. */
    section[data-testid="stSidebar"] {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

# Long-running generation jobs must not write to Streamlit from worker
# threads. The registry itself is held in a Streamlit resource cache so it
# survives normal script reruns while remaining a plain Python data structure
# that workers can safely update under a lock.
@st.cache_resource(show_spinner=False)
def _get_job_registry() -> Tuple[threading.Lock, Dict[Tuple[str, str], Dict[str, Any]]]:
    """Create the process-wide thread-safe job registry once."""
    return threading.Lock(), {}


_JOB_LOCK, _JOB_RESULTS = _get_job_registry()

DEFAULT_STATE: Dict[str, Any] = {
    "active_module": "requirements",
    "uploaded_brd": None,
    "ingestion_result": None,
    "drs_result": None,
    "jira_result": None,
    "estimation_result": None,
    "drs_markdown": None,
    "jira_markdown": None,
    "estimation_markdown": None,
    "chat_history": [],
    "chat_kb_path": None,
    "session_uid": None,
    "ingestion_job_status": "idle",
    "drs_job_status": "idle",
    "jira_job_status": "idle",
    "estimation_job_status": "idle",
    "ingestion_job_error": None,
    "drs_job_error": None,
    "jira_job_error": None,
    "estimation_job_error": None,
}

for state_key, default_value in DEFAULT_STATE.items():
    if state_key not in st.session_state:
        st.session_state[state_key] = default_value

if not st.session_state["session_uid"]:
    st.session_state["session_uid"] = uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Background job helpers
# ---------------------------------------------------------------------------

def _publish_job_result(
    session_uid: str,
    job_name: str,
    *,
    status: str,
    result: Any = None,
    error: Optional[str] = None,
) -> None:
    """Publish a completed worker result without touching Streamlit APIs."""
    with _JOB_LOCK:
        _JOB_RESULTS[(session_uid, job_name)] = {
            "status": status,
            "result": result,
            "error": error,
        }


def _start_background_job(
    job_name: str,
    target: Any,
    kwargs: Dict[str, Any],
) -> bool:
    """Start a long-running job whose worker never touches Streamlit."""
    session_uid = str(st.session_state["session_uid"])
    status_key = f"{job_name}_job_status"

    if st.session_state.get(status_key) == "running":
        return False

    st.session_state[status_key] = "running"
    st.session_state[f"{job_name}_job_error"] = None

    def _runner() -> None:
        try:
            result = target(**kwargs)
            _publish_job_result(
                session_uid,
                job_name,
                status="done",
                result=result,
            )
        except Exception as exc:
            _publish_job_result(
                session_uid,
                job_name,
                status="error",
                error=str(exc),
            )

    worker = threading.Thread(
        target=_runner,
        name=f"sdlc_{job_name}_worker",
        daemon=True,
    )
    worker.start()
    return True


def _drain_job_results() -> None:
    """Apply completed worker results to session state in the current run."""
    session_uid = str(st.session_state["session_uid"])
    drained: List[Tuple[str, Dict[str, Any]]] = []

    with _JOB_LOCK:
        for (uid, job_name), payload in list(_JOB_RESULTS.items()):
            if uid != session_uid:
                continue
            drained.append((job_name, payload))
            del _JOB_RESULTS[(uid, job_name)]

    for job_name, payload in drained:
        status_key = f"{job_name}_job_status"
        error_key = f"{job_name}_job_error"
        st.session_state[status_key] = payload["status"]
        st.session_state[error_key] = payload.get("error")

        if payload["status"] != "done":
            continue

        result = payload.get("result")
        st.session_state[f"{job_name}_result"] = result

        if job_name in {"drs", "jira"}:
            word_path = _result_path(result)
            if word_path:
                _ensure_output_dir()
                markdown_path = word_path.parent / f"{word_path.stem}.md"
                st.session_state[f"{job_name}_markdown"] = str(
                    _docx_to_markdown(word_path, markdown_path)
                )
        elif job_name == "estimation":
            markdown_path = getattr(result, "generated_markdown", None)
            if markdown_path:
                st.session_state["estimation_markdown"] = str(markdown_path)


def _sync_persisted_generation_status() -> None:
    """Use persisted files as a safe fallback for generation completion."""
    uploaded_brd = st.session_state.get("uploaded_brd")
    if not uploaded_brd:
        return

    brs_folder = OUTPUT_DIR / Path(uploaded_brd).stem
    if not brs_folder.is_dir():
        return

    persisted_artifacts = {
        "drs": brs_folder / "generated_drs.docx",
        "jira": brs_folder / "generated_jira_user_stories.docx",
        "estimation": brs_folder / "generated_estimation.docx",
    }

    for job_name, artifact_path in persisted_artifacts.items():
        status_key = f"{job_name}_job_status"
        # Only use a persisted file as a recovery signal for a job that the
        # current session actually started. This avoids treating an older
        # document with the same BRS name as a newly completed generation.
        if (
            artifact_path.is_file()
            and st.session_state.get(status_key) == "running"
        ):
            st.session_state[status_key] = "done"


def _has_running_jobs() -> bool:
    """Return whether any background pipeline job is still running."""
    return any(
        st.session_state.get(f"{job_name}_job_status") == "running"
        for job_name in ("ingestion", "drs", "jira", "estimation")
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_uploaded_brd(uploaded_file: Any) -> Path:
    """Persist the uploaded BRD in the project's uploads directory."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    filename = Path(uploaded_file.name).name
    destination = UPLOADS_DIR / filename
    destination.write_bytes(uploaded_file.getbuffer())
    return destination


def _reset_generated_artifacts() -> None:
    """Clear generated artifacts for a new source document."""
    st.session_state["ingestion_result"] = None
    st.session_state["uploaded_brd"] = None
    st.session_state["drs_result"] = None
    st.session_state["jira_result"] = None
    st.session_state["estimation_result"] = None
    st.session_state["drs_markdown"] = None
    st.session_state["jira_markdown"] = None
    st.session_state["estimation_markdown"] = None
    st.session_state["chat_history"] = []
    st.session_state["chat_kb_path"] = None
    st.session_state["ingestion_job_status"] = "idle"
    st.session_state["drs_job_status"] = "idle"
    st.session_state["jira_job_status"] = "idle"
    st.session_state["estimation_job_status"] = "idle"
    st.session_state["ingestion_job_error"] = None
    st.session_state["drs_job_error"] = None
    st.session_state["jira_job_error"] = None
    st.session_state["estimation_job_error"] = None


def _docx_to_markdown(docx_path: Path, output_path: Path) -> Path:
    """Convert a generated DOCX into a readable Markdown artifact."""
    from docx import Document

    document = Document(str(docx_path))
    lines: List[str] = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue

        style_name = (paragraph.style.name or "").lower()
        if "title" in style_name:
            lines.append(f"# {text}")
        elif "heading 1" in style_name:
            lines.append(f"# {text}")
        elif "heading 2" in style_name:
            lines.append(f"## {text}")
        elif "heading 3" in style_name:
            lines.append(f"### {text}")
        elif text.startswith("• "):
            lines.append(f"- {text[2:]}")
        elif text.startswith("- "):
            lines.append(text)
        else:
            lines.append(text)

    for table in document.tables:
        if not table.rows:
            continue
        lines.append("")
        rows: List[List[str]] = []
        for row in table.rows:
            rows.append([cell.text.replace("\n", " ").strip() for cell in row.cells])
        if rows:
            lines.append("| " + " | ".join(rows[0]) + " |")
            lines.append("| " + " | ".join(["---"] * len(rows[0])) + " |")
            for row in rows[1:]:
                lines.append("| " + " | ".join(row) + " |")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n\n".join(lines).strip() + "\n", encoding="utf-8")
    return output_path


def _build_download(path: Optional[Path], label: str, mime: str) -> None:
    """Show a download button for a real file when it exists."""
    if not path or not path.is_file():
        st.caption("Not generated yet")
        return

    st.download_button(
        label=label,
        data=path.read_bytes(),
        file_name=path.name,
        mime=mime,
        use_container_width=True,
        key=f"download_{path.name}",
    )


def _result_path(result: Any) -> Optional[Path]:
    """Extract generated_document from a pipeline result."""
    value = getattr(result, "generated_document", None)
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_file() else None


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _load_active_kb(kb_path: Optional[str]) -> Any:
    """Load the current FAISS knowledge base for the chat workspace."""
    from modules.embeddings import get_embeddings
    from modules.knowledge_base import KnowledgeBase

    if not kb_path:
        raise RuntimeError("No active knowledge base is available.")

    embeddings = get_embeddings()
    knowledge_base = KnowledgeBase(kb_path, embeddings)
    knowledge_base.load()
    if knowledge_base.vector_store is None:
        raise RuntimeError("The active knowledge base could not be loaded.")
    return knowledge_base


def _answer_chat(question: str) -> str:
    """Answer a user question through the dedicated chatbot feature."""
    from chatbot_feature.chatbot_executor import ChatbotExecutor

    kb_path = st.session_state.get("chat_kb_path")
    executor = ChatbotExecutor(
        knowledge_base_path=kb_path,
        candidate_top_k=10,
        rerank_top_k=3,
    )
    return executor.answer(
        question=question,
        chat_history=st.session_state.get("chat_history", []),
    )


def _find_brs_source(brs_name: str) -> Optional[Path]:
    """Find the uploaded source document matching a persisted BRS folder."""
    if not UPLOADS_DIR.is_dir():
        return None

    for candidate in UPLOADS_DIR.iterdir():
        if not candidate.is_file():
            continue
        if candidate.stem != brs_name:
            continue
        if candidate.suffix.lower() not in {".docx"}:
            continue
        return candidate

    return None


def _find_estimation_artifact(folder: Path) -> Optional[Path]:
    """Find a persisted DOCX estimation artifact for a BRS workspace."""
    if not folder.is_dir():
        return None

    candidates = sorted(
        (
            path
            for path in folder.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".docx"
            and "estimation" in path.stem.lower()
        ),
        key=lambda path: path.name.lower(),
    )
    return candidates[0] if candidates else None


def _discover_dashboard_rows() -> List[Dict[str, Any]]:
    """Discover persisted BRS DOCX artifacts from the output directory."""
    rows: List[Dict[str, Any]] = []

    if not OUTPUT_DIR.is_dir():
        return rows

    for brs_folder in sorted(
        (path for path in OUTPUT_DIR.iterdir() if path.is_dir()),
        key=lambda path: path.name.lower(),
    ):
        brs_name = brs_folder.name
        brd_path = _find_brs_source(brs_name)
        drs_path = brs_folder / "generated_drs.docx"
        jira_path = brs_folder / "generated_jira_user_stories.docx"
        estimation_path = _find_estimation_artifact(brs_folder)

        if not any(
            path is not None and path.is_file()
            for path in (brd_path, drs_path, jira_path, estimation_path)
        ):
            continue

        rows.append(
            {
                "Title": brs_name,
                "BRD": brd_path,
                "DRS": drs_path,
                "Jira": jira_path,
                "Estimation": estimation_path,
            }
        )

    return rows


def _show_dashboard_workspace() -> None:
    """Render the persistent dashboard in a tabular layout."""
    st.markdown(
        '<div class="module-caption">Dashboard</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="portal-title">SDLC Dashboard</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="portal-subtitle">'
        "Persisted DOCX artefacts discovered from the output workspace."
        "</div>",
        unsafe_allow_html=True,
    )

    rows = _discover_dashboard_rows()
    if not rows:
        st.info(
            "No generated BRS DOCX artefacts found in the output directory yet."
        )
        return

    # Render a grid-style table with ONE bordered container per row (header
    # and each data row), rather than a border around every individual cell.
    # That keeps the table reading as a single clean grid instead of a wall
    # of small nested boxes, and leaves each column wide enough that the
    # "Download" buttons render on one line instead of wrapping letter by
    # letter.
    headers = (
        "Sl no",
        "Title",
        "BRD Link",
        "DRS Link",
        "Jira link",
        "Estimation",
    )
    column_spec = [0.6, 3.4, 1.3, 1.3, 1.3, 1.3]

    with st.container(border=True):
        header_columns = st.columns(column_spec, gap="medium")
        for column, heading in zip(header_columns, headers):
            with column:
                st.markdown(
                    f'<div class="grid-header-cell">{heading}</div>',
                    unsafe_allow_html=True,
                )

    docx_mime = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    for row_index, row in enumerate(rows, start=1):
        with st.container(border=True):
            columns = st.columns(column_spec, gap="medium")

            with columns[0]:
                st.markdown(
                    f'<div class="grid-cell grid-cell-index">{row_index}</div>',
                    unsafe_allow_html=True,
                )

            with columns[1]:
                title = row["Title"]
                st.markdown(
                    f'<div class="grid-cell grid-cell-title" title="{title}">'
                    f"{title}</div>",
                    unsafe_allow_html=True,
                )

            for column, key in zip(
                columns[2:],
                ("BRD", "DRS", "Jira", "Estimation"),
            ):
                path = row[key]
                with column:
                    if isinstance(path, Path) and path.is_file():
                        st.download_button(
                            label="Download",
                            data=path.read_bytes(),
                            file_name=path.name,
                            mime=docx_mime,
                            use_container_width=True,
                            key=f"dashboard_{row_index}_{key}",
                        )
                    else:
                        st.markdown(
                            '<div class="grid-cell grid-cell-empty">—</div>',
                            unsafe_allow_html=True,
                        )


def _show_nav() -> None:
    """Render left navigation controls."""
    st.markdown('<div class="nav-label">Workspace</div>', unsafe_allow_html=True)

    requirements_selected = st.session_state["active_module"] == "requirements"
    estimation_selected = st.session_state["active_module"] == "estimation"
    dashboard_selected = st.session_state["active_module"] == "dashboard"

    if st.button(
        "Dashboard",
        use_container_width=True,
        type="primary" if dashboard_selected else "secondary",
        key="nav_dashboard",
    ):
        st.session_state["active_module"] = "dashboard"
        st.rerun()

    if st.button(
        "Requirements\nGeneration",
        use_container_width=True,
        type="primary" if requirements_selected else "secondary",
        key="nav_requirements",
    ):
        st.session_state["active_module"] = "requirements"
        st.rerun()

    if st.button(
        "Estimation\nGeneration",
        use_container_width=True,
        type="primary" if estimation_selected else "secondary",
        key="nav_estimation",
    ):
        st.session_state["active_module"] = "estimation"
        st.rerun()

    st.markdown(
        '<div class="small-note" style="margin-top:1rem;">'
        "Estimation is currently a workspace channel only."
        "</div>",
        unsafe_allow_html=True,
    )


def _show_requirement_workspace() -> None:
    """Render the requirement-generation workspace."""
    st.markdown('<div class="module-caption">Requirement Generation</div>', unsafe_allow_html=True)
    st.markdown('<div class="portal-title">SDLC Lifecycle Assistant</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="portal-subtitle">Upload a BRD, generate DRS/Jira artifacts, and ask evidence-grounded questions.</div>',
        unsafe_allow_html=True,
    )

    uploaded_file = st.file_uploader(
        "BRD Upload",
        type=SUPPORTED_EXTENSIONS,
        key="brd_uploader",
        label_visibility="visible",
    )

    ingestion_status = st.session_state.get("ingestion_job_status", "idle")
    if uploaded_file is not None and st.button(
        "Process BRD",
        type="primary",
        use_container_width=True,
        key="process_brd",
        disabled=_has_running_jobs(),
    ):
        try:
            _reset_generated_artifacts()
            saved_path = _save_uploaded_brd(uploaded_file)
            from src.ingestion_pipeline import ingest_brd
            _start_background_job(
                "ingestion",
                ingest_brd,
                {"brd_path": saved_path},
            )
            st.session_state["uploaded_brd"] = str(saved_path)
            st.rerun()
        except Exception as exc:
            st.session_state["ingestion_job_status"] = "error"
            st.session_state["ingestion_job_error"] = str(exc)
            st.error(f"BRD processing failed to start: {exc}")

    _drain_job_results()
    _sync_persisted_generation_status()

    ingestion_status = st.session_state.get("ingestion_job_status", "idle")
    if ingestion_status == "running":
        st.info("Building the active knowledge base...")
    elif ingestion_status == "done":
        ingestion_ready = bool(st.session_state.get("ingestion_result"))
        if ingestion_ready:
            st.success("BRD processed successfully. You can now generate the required artifacts.")
        else:
            st.error("BRD processing completed, but the knowledge base result is unavailable in this session.")
    elif ingestion_status == "error":
        st.error(f"BRD processing failed: {st.session_state.get('ingestion_job_error') or 'Unknown error'}")

    ingestion_ready = bool(st.session_state.get("ingestion_result")) or ingestion_status == "done"

    if ingestion_ready:
        action1, action2 = st.columns(2)
        drs_status = st.session_state.get("drs_job_status", "idle")
        jira_status = st.session_state.get("jira_job_status", "idle")

        with action1:
            if st.button(
                "Generate DRS" if drs_status != "running" else "Generating DRS...",
                type="primary",
                use_container_width=True,
                key="generate_drs",
                disabled=drs_status == "running",
            ):
                try:
                    from src.fetch_drs_pipeline import generate_drs
                    _start_background_job(
                        "drs",
                        generate_drs,
                        {
                            "brs_name": Path(st.session_state["uploaded_brd"]).stem,
                        },
                    )
                    st.rerun()
                except Exception as exc:
                    st.session_state["drs_job_status"] = "error"
                    st.session_state["drs_job_error"] = str(exc)
                    st.error(f"DRS generation failed to start: {exc}")

        with action2:
            if st.button(
                "Generate Jira User Stories" if jira_status != "running" else "Generating Jira User Stories...",
                type="primary",
                use_container_width=True,
                key="generate_jira",
                disabled=jira_status == "running",
            ):
                try:
                    from src.fetch_jira_pipeline import generate_jira_document_pipeline
                    _start_background_job(
                        "jira",
                        generate_jira_document_pipeline,
                        {
                            "brs_name": Path(st.session_state["uploaded_brd"]).stem,
                        },
                    )
                    st.rerun()
                except Exception as exc:
                    st.session_state["jira_job_status"] = "error"
                    st.session_state["jira_job_error"] = str(exc)
                    st.error(f"Jira generation failed to start: {exc}")

        if drs_status == "done":
            st.success("DRS generation completed.")
        elif drs_status == "error":
            st.error(f"DRS generation failed: {st.session_state.get('drs_job_error') or 'Unknown error'}")

        if jira_status == "done":
            st.success("Jira generation completed.")
        elif jira_status == "error":
            st.error(f"Jira generation failed: {st.session_state.get('jira_job_error') or 'Unknown error'}")
    else:
        st.info("Upload and process a BRD to enable DRS and Jira generation.")

    st.divider()
    source_col, kb_col = st.columns(2)
    with source_col:
        if st.session_state.get("uploaded_brd"):
            st.caption(f"Source: {Path(st.session_state['uploaded_brd']).name}")
        else:
            st.caption("No BRD selected")
    with kb_col:
        st.caption("Knowledge base: Ready" if ingestion_ready else "Knowledge base: Not ready")

    st.divider()
    st.subheader("QA Chatbot")
    if not ingestion_ready:
        st.info("Process a BRD before asking questions.")
    elif not st.session_state.get("chat_history"):
        st.info("Ask a question about the uploaded BRD. Answers are grounded in the active knowledge base.")

    for message in st.session_state["chat_history"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    chatbot_disabled = (
        not ingestion_ready
        or _has_running_jobs()
    )

    if _has_running_jobs() and ingestion_ready:
        st.info("Chatbot is disabled while a BRD, DRS, or Jira process is running.")

    question = st.chat_input(
        "Ask about requirements, rules, processes, NFRs, or traceability...",
        key="qa_chat_input",
        disabled=chatbot_disabled,
    )
    if question and not chatbot_disabled:
        st.session_state["chat_history"].append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Searching the knowledge base..."):
                try:
                    answer = _answer_chat(question)
                except Exception as exc:
                    answer = f"I could not answer the question because: {exc}"
            st.markdown(answer)
        st.session_state["chat_history"].append({"role": "assistant", "content": answer})

def _show_estimation_workspace() -> None:
    """Render the BRD-only estimation generation workspace."""
    st.markdown('<div class="module-caption">Estimation Generation</div>', unsafe_allow_html=True)
    st.markdown('<div class="portal-title">SDLC Lifecycle Assistant</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="portal-subtitle">Generate an evidence-grounded complexity estimation from the processed BRD.</div>',
        unsafe_allow_html=True,
    )

    ingestion_ready = bool(st.session_state.get("ingestion_result")) or st.session_state.get("ingestion_job_status") == "done"
    status = st.session_state.get("estimation_job_status", "idle")
    if not ingestion_ready:
        st.info("Process a BRD in Requirement Generation before generating an estimation.")
        return
    if st.button(
        "Generate Estimation" if status != "running" else "Generating Estimation...",
        type="primary",
        use_container_width=True,
        key="generate_estimation",
        disabled=status == "running" or _has_running_jobs(),
    ):
        try:
            from estimation_generation.pipeline import generate_estimation
            _start_background_job("estimation", generate_estimation, {"brs_name": Path(st.session_state["uploaded_brd"]).stem})
            st.rerun()
        except Exception as exc:
            st.session_state["estimation_job_status"] = "error"
            st.session_state["estimation_job_error"] = str(exc)
            st.error(f"Estimation generation failed to start: {exc}")
    if status == "running":
        st.info("Extracting BRD evidence and calculating the weighted complexity score...")
    elif status == "done":
        result = st.session_state.get("estimation_result")
        score = getattr(result, "final_complexity_score", None)
        st.success(f"Estimation generation completed. Final complexity score: {score:.2f} / 5.00" if isinstance(score, (int, float)) else "Estimation generation completed.")
    elif status == "error":
        st.error(f"Estimation generation failed: {st.session_state.get('estimation_job_error') or 'Unknown error'}")


def _artifact_card(
    name: str,
    status: str,
    path: Optional[Path],
    mime: str,
    button_label: str = "Download",
) -> None:
    """Render one artifact in the right panel."""
    ready = bool(path and path.is_file())
    status_html = (
        '<span class="ready">Ready</span>' if ready else status
    )
    st.markdown(
        f'<div class="artifact-card">'
        f'<div class="artifact-name">{name}</div>'
        f'<div class="artifact-status">Status: {status_html}</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    _build_download(path, button_label, mime)


def _show_output_panel() -> None:
    """Render artifacts relevant to the selected module."""
    active_module = st.session_state.get("active_module")
    if active_module not in {"requirements", "estimation"}:
        return

    st.markdown('<div class="section-title">Output & Generated Artifacts</div>', unsafe_allow_html=True)

    if active_module == "requirements":
        st.markdown("**DRS Documents**")
        drs_result = st.session_state.get("drs_result")
        drs_word_path = _result_path(drs_result) if drs_result else None
        if drs_word_path is None and st.session_state.get("uploaded_brd"):
            candidate = OUTPUT_DIR / Path(st.session_state["uploaded_brd"]).stem / "generated_drs.docx"
            drs_word_path = candidate if candidate.is_file() else None
        drs_md_path = Path(st.session_state["drs_markdown"]) if st.session_state.get("drs_markdown") else None
        if drs_md_path is None and drs_word_path is not None:
            candidate = drs_word_path.parent / f"{drs_word_path.stem}.md"
            drs_md_path = candidate if candidate.is_file() else None
        _artifact_card(
            "DRS Word",
            "Not generated",
            drs_word_path,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "Download Word",
        )
        _artifact_card(
            "DRS Markdown",
            "Not generated",
            drs_md_path,
            "text/markdown",
            "Download Markdown",
        )

        st.markdown("**Jira User Stories**")
        jira_result = st.session_state.get("jira_result")
        jira_word_path = _result_path(jira_result) if jira_result else None
        if jira_word_path is None and st.session_state.get("uploaded_brd"):
            candidate = OUTPUT_DIR / Path(st.session_state["uploaded_brd"]).stem / "generated_jira_user_stories.docx"
            jira_word_path = candidate if candidate.is_file() else None
        jira_md_path = Path(st.session_state["jira_markdown"]) if st.session_state.get("jira_markdown") else None
        if jira_md_path is None and jira_word_path is not None:
            candidate = jira_word_path.parent / f"{jira_word_path.stem}.md"
            jira_md_path = candidate if candidate.is_file() else None
        _artifact_card(
            "Jira Stories Word",
            "Not generated",
            jira_word_path,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "Download Word",
        )
        _artifact_card(
            "Jira Stories Markdown",
            "Not generated",
            jira_md_path,
            "text/markdown",
            "Download Markdown",
        )
    else:
        st.markdown("**Estimation Documents**")
        estimation_result = st.session_state.get("estimation_result")
        estimation_word_path = _result_path(estimation_result) if estimation_result else None
        if estimation_word_path is None and st.session_state.get("uploaded_brd"):
            candidate = OUTPUT_DIR / Path(st.session_state["uploaded_brd"]).stem / "generated_estimation.docx"
            estimation_word_path = candidate if candidate.is_file() else None
        estimation_md_path = Path(st.session_state["estimation_markdown"]) if st.session_state.get("estimation_markdown") else None
        if estimation_md_path is None and estimation_word_path is not None:
            candidate = estimation_word_path.parent / "generated_estimation.md"
            estimation_md_path = candidate if candidate.is_file() else None
        _artifact_card("Estimation Word", "Not generated", estimation_word_path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Download Word")
        _artifact_card("Estimation Markdown", "Not generated", estimation_md_path, "text/markdown", "Download Markdown")


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

_drain_job_results()
_sync_persisted_generation_status()

st.markdown(
    '<div class="portal-title">SDLC Assistant Portal</div>'
    '<div class="portal-subtitle">AI-powered requirement generation and lifecycle assistance</div>',
    unsafe_allow_html=True,
)

active_module = st.session_state["active_module"]
dashboard_active = active_module == "dashboard"

# The right-hand output panel is only shown for the requirements/estimation
# tabs. Give the dashboard tab that reclaimed width instead of leaving it
# empty, so the grid has room to breathe rather than being squeezed into
# the same 6/10 center column used by the narrower workspaces.
if dashboard_active:
    left, center = st.columns([2, 10], gap="medium")
else:
    left, center, right = st.columns([2, 6, 2], gap="medium")

with left:
    with st.container(border=True):
        _show_nav()

with center:
    with st.container(border=True):
        if active_module == "requirements":
            _show_requirement_workspace()
        elif active_module == "estimation":
            _show_estimation_workspace()
        elif active_module == "dashboard":
            _show_dashboard_workspace()

if not dashboard_active:
    with right:
        with st.container(border=True):
            _show_output_panel()


# Keep the Requirements workspace responsive while a background job is active.
# Dashboard and Estimation intentionally do not participate in this polling loop,
# so navigating away from Requirements cannot cause the generation workspace or
# output panel to be re-rendered as part of a job refresh. The background worker
# continues independently, and its result is picked up on the next Streamlit run.
if (
    st.session_state.get("active_module") == "requirements"
    and _has_running_jobs()
):
    time.sleep(1.0)
    st.rerun()
