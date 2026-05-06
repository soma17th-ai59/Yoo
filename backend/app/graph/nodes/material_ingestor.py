"""MaterialIngestor node — extract → mask_all → summarize for each uploaded file.

Invariant (CLAUDE.md §Hard rules rule 1):
    mask_all MUST be called before any Solar (summarize) call.
Zero LangGraph imports per module purity rules.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from backend.app.graph.state import GraphState, MaterialBundle
from backend.app.materials.extract import extract_text
from backend.app.materials.summarize import summarize
from backend.app.pii import mask_all, scan


def ingest_materials(
    state: GraphState,
    material_files: list[tuple[str, bytes]],
) -> dict:
    """Ingest new material files and append to state.materials.

    Args:
        state: current GraphState
        material_files: list of (filename, file_bytes) tuples

    Returns:
        {"materials": MaterialBundle} with all existing + new docs.
    """
    existing_docs = [dict(d) for d in state.materials.docs]
    new_docs: list[dict] = []

    for filename, file_bytes in material_files:
        suffix = Path(filename).suffix or ".tmp"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = Path(tmp.name)

        try:
            raw_text = extract_text(tmp_path)
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

        masked_text = mask_all(raw_text)
        summary = summarize(masked_text, filename)

        # Guard the summary against PII leaks before storing
        clean, _ = scan(summary)
        if not clean:
            summary = "[요약 생성 중 오류 - 확인 필요]"

        doc_id = hashlib.sha256(f"{filename}:{len(raw_text)}".encode()).hexdigest()[:12]

        new_docs.append(
            {
                "doc_id": doc_id,
                "filename": filename,
                "summary": summary,
                "masked_text": masked_text,
                "raw_len": len(raw_text),
            }
        )

    return {"materials": MaterialBundle(docs=existing_docs + new_docs)}
