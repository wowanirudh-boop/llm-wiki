"""Local file upload route - simple multipart, no TUS.

Copies uploaded files directly into the workspace and indexes them.
"""

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from config import settings
from deps import get_user_id
from domain.local_index import (
    extension_for,
    folder_path_for,
    source_kind_for,
    title_for,
)
from domain.watcher import mark_written

router = APIRouter(tags=["upload"])

SIMPLE_TEXT_TYPES = {"md", "txt", "csv", "svg", "json", "xml"}
PROCESSING_TYPES = {
    "pdf", "pptx", "ppt", "docx", "doc", "xlsx", "xls", "html", "htm",
    "png", "jpg", "jpeg", "webp", "gif",
}


def _workspace_root() -> Path:
    return Path(settings.WORKSPACE_PATH).resolve()


def _safe_resolve(relative: str) -> Path:
    ws = _workspace_root()
    resolved = (ws / relative).resolve()
    if not resolved.is_relative_to(ws):
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    return resolved


def _relative_path(path: str, filename: str) -> str:
    normalized = "/" + path.replace("\\", "/").strip("/") + "/"
    if normalized == "//":
        normalized = "/"
    return (normalized.rstrip("/") + "/" + filename).lstrip("/")


async def _find_existing_id(db, relative: str) -> str | None:
    legacy = relative.replace("/", "\\")
    if legacy != relative:
        cursor = await db.execute(
            "SELECT id FROM documents WHERE relative_path IN (?, ?) LIMIT 1",
            (relative, legacy),
        )
    else:
        cursor = await db.execute(
            "SELECT id FROM documents WHERE relative_path = ? LIMIT 1",
            (relative,),
        )
    row = await cursor.fetchone()
    return row[0] if row else None


def _duplicate_detail(path: str, filename: str, relative: str, existing_id: str | None) -> dict:
    return {
        "code": "duplicate_path",
        "path": path,
        "filename": filename,
        "relative_path": relative,
        "existing_document_id": existing_id,
    }


async def _clear_extracted_state(db, doc_id: str) -> None:
    await db.execute("DELETE FROM document_pages WHERE document_id = ?", (doc_id,))
    await db.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))


@router.post("/v1/upload", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    path: str = Form(default="/"),
    on_conflict: str = Form(default="error"),
    user_id: str = Depends(get_user_id),
    request: Request = None,
):
    """Upload a file directly into the workspace and index it."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    if on_conflict not in {"error", "replace"}:
        raise HTTPException(status_code=400, detail="Invalid on_conflict")

    filename = file.filename
    relative = _relative_path(path, filename)
    dir_path = folder_path_for(relative)
    dest = _safe_resolve(relative)

    from infra.db.sqlite import SQLiteChunkRepository, SQLiteDocumentRepository
    db = request.app.state.sqlite_db
    doc_repo = SQLiteDocumentRepository(db)
    chunk_repo = SQLiteChunkRepository(db)

    existing_id = await _find_existing_id(db, relative)
    duplicate = existing_id is not None or dest.exists()
    if duplicate and on_conflict != "replace":
        raise HTTPException(
            status_code=409,
            detail=_duplicate_detail(dir_path, filename, relative, existing_id),
        )

    content_bytes = await file.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    mark_written(str(dest))
    dest.write_bytes(content_bytes)

    ext = extension_for(filename)
    title = title_for(filename)
    source_kind = source_kind_for(relative)
    content_hash = hashlib.sha256(content_bytes).hexdigest()

    text_content = None
    if ext in SIMPLE_TEXT_TYPES:
        try:
            text_content = content_bytes.decode("utf-8", errors="replace")
        except Exception:
            pass
    status = "ready" if text_content is not None else "pending"

    if existing_id:
        doc_id = existing_id
        await _clear_extracted_state(db, doc_id)
        await db.execute(
            "UPDATE documents SET user_id = ?, filename = ?, title = ?, path = ?, "
            "relative_path = ?, source_kind = ?, file_type = ?, file_size = ?, "
            "status = ?, content = ?, page_count = NULL, parser = NULL, "
            "error_message = NULL, highlights = '[]', version = version + 1, "
            "content_hash = ?, mtime_ns = ?, last_indexed_at = datetime('now'), "
            "updated_at = datetime('now') WHERE id = ?",
            (
                user_id, filename, title, dir_path, relative, source_kind,
                ext or "bin", len(content_bytes), status, text_content,
                content_hash, int(dest.stat().st_mtime_ns), doc_id,
            ),
        )
    else:
        doc_id = str(uuid.uuid4())
        cursor = await db.execute("SELECT COALESCE(MAX(document_number), 0) + 1 FROM documents")
        row = await cursor.fetchone()
        doc_number = row[0]

        await db.execute(
            "INSERT INTO documents (id, user_id, filename, title, path, relative_path, "
            "source_kind, file_type, file_size, status, content, tags, version, "
            "content_hash, mtime_ns, last_indexed_at, document_number) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 0, ?, ?, datetime('now'), ?)",
            (
                doc_id, user_id, filename, title, dir_path, relative, source_kind,
                ext or "bin", len(content_bytes), status, text_content,
                content_hash, int(dest.stat().st_mtime_ns), doc_number,
            ),
        )
    await db.commit()

    if text_content:
        from services.chunker import chunk_text
        ws_row = await db.execute("SELECT id FROM workspace LIMIT 1")
        ws = await ws_row.fetchone()
        kb_id = ws[0] if ws else ""
        chunks = chunk_text(text_content)
        await chunk_repo.store(doc_id, user_id, kb_id, chunks)
    elif status == "pending" and ext in PROCESSING_TYPES:
        import asyncio
        from domain.local_processor import process_document
        asyncio.create_task(process_document(db, doc_id, Path(settings.WORKSPACE_PATH).resolve()))

    doc = await doc_repo.get(doc_id)
    return doc
