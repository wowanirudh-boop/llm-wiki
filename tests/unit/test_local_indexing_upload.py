from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from domain.watcher import _index_file
from infra.db.sqlite import create_pool


USER_ID = "local-user"


@pytest.fixture
async def sqlite_db(tmp_path):
    db = await create_pool(str(tmp_path / "index.db"))
    await db.execute(
        "INSERT INTO workspace (id, name, user_id) VALUES ('w1', 'Test', ?)",
        (USER_ID,),
    )
    await db.commit()
    try:
        yield db
    finally:
        await db.close()


async def test_existing_pdf_indexes_pending_with_posix_path(sqlite_db, tmp_path):
    workspace = tmp_path / "workspace"
    source_dir = workspace / "folder"
    source_dir.mkdir(parents=True)
    pdf_path = source_dir / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nbody")

    await _index_file(sqlite_db, workspace, pdf_path, schedule_processing=False)

    cursor = await sqlite_db.execute(
        "SELECT status, content, relative_path, path, file_type "
        "FROM documents WHERE filename = 'report.pdf'",
    )
    row = await cursor.fetchone()

    assert row == ("pending", None, "folder/report.pdf", "/folder/", "pdf")


async def test_existing_office_files_index_pending(sqlite_db, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    docx_path = workspace / "paper.docx"
    pptx_path = workspace / "deck.pptx"
    docx_path.write_bytes(b"PK\x03\x04docx")
    pptx_path.write_bytes(b"PK\x03\x04pptx")

    await _index_file(sqlite_db, workspace, docx_path, schedule_processing=False)
    await _index_file(sqlite_db, workspace, pptx_path, schedule_processing=False)

    cursor = await sqlite_db.execute(
        "SELECT filename, status, content FROM documents ORDER BY filename",
    )
    rows = await cursor.fetchall()

    assert rows == [
        ("deck.pptx", "pending", None),
        ("paper.docx", "pending", None),
    ]


async def test_modified_ready_pdf_resets_to_pending_and_clears_extracted_rows(sqlite_db, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    pdf_path = workspace / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nnew")

    await sqlite_db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, "
        "source_kind, file_type, file_size, status, page_count, content, parser, "
        "content_hash, document_number, highlights) "
        "VALUES ('doc-existing', ?, 'report.pdf', 'Report', '/', 'report.pdf', "
        "'source', 'pdf', 3, 'ready', 1, 'old extracted text', 'opendataloader', "
        "'old-hash', 7, '[{\"id\":\"h1\"}]')",
        (USER_ID,),
    )
    await sqlite_db.execute(
        "INSERT INTO document_pages (id, document_id, page, content) "
        "VALUES ('page-1', 'doc-existing', 1, 'old page')",
    )
    await sqlite_db.execute(
        "INSERT INTO document_chunks (id, document_id, chunk_index, content, "
        "source_content, token_count) "
        "VALUES ('chunk-1', 'doc-existing', 0, 'old chunk', 'old chunk', 2)",
    )
    await sqlite_db.commit()

    await _index_file(sqlite_db, workspace, pdf_path, schedule_processing=False)

    cursor = await sqlite_db.execute(
        "SELECT status, content, page_count, parser, relative_path "
        "FROM documents WHERE id = 'doc-existing'",
    )
    row = await cursor.fetchone()
    page_count = await sqlite_db.execute_fetchall(
        "SELECT COUNT(*) FROM document_pages WHERE document_id = 'doc-existing'",
    )
    chunk_count = await sqlite_db.execute_fetchall(
        "SELECT COUNT(*) FROM document_chunks WHERE document_id = 'doc-existing'",
    )

    assert row == ("pending", None, None, None, "report.pdf")
    assert page_count[0][0] == 0
    assert chunk_count[0][0] == 0


def test_cli_existing_office_and_pdf_index_pending(tmp_path):
    module = _load_llmwiki_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "report.pdf").write_bytes(b"%PDF-1.4\nbody")
    (workspace / "paper.docx").write_bytes(b"PK\x03\x04docx")
    (workspace / "notes.txt").write_text("hello", encoding="utf-8")

    db_path = workspace / ".llmwiki" / "index.db"
    db_path.parent.mkdir()
    schema = (Path(__file__).resolve().parents[2] / "shared" / "sqlite_schema.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema)
    conn.execute(
        "INSERT INTO workspace (id, name, user_id) VALUES ('w1', 'Test', ?)",
        (USER_ID,),
    )
    conn.commit()
    conn.close()

    module._index_existing_files(workspace, db_path, USER_ID, "w1")

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT filename, status, relative_path FROM documents ORDER BY filename",
    ).fetchall()
    conn.close()

    assert rows == [
        ("notes.txt", "ready", "notes.txt"),
        ("paper.docx", "pending", "paper.docx"),
        ("report.pdf", "pending", "report.pdf"),
    ]


@pytest.fixture
async def local_upload_env(tmp_path, monkeypatch):
    from routes import local_upload
    import domain.local_processor as local_processor

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    db = await create_pool(str(tmp_path / "index.db"))
    await db.execute(
        "INSERT INTO workspace (id, name, user_id) VALUES ('w1', 'Test', ?)",
        (USER_ID,),
    )
    await db.commit()

    scheduled: list[str] = []

    async def fake_process_document(db, doc_id: str, workspace: Path) -> None:
        scheduled.append(doc_id)

    monkeypatch.setattr(local_upload.settings, "WORKSPACE_PATH", str(workspace))
    monkeypatch.setattr(local_processor, "process_document", fake_process_document)

    class LocalAuth:
        async def get_current_user(self, request):
            return USER_ID

    app = FastAPI()
    app.include_router(local_upload.router)
    app.state.sqlite_db = db
    app.state.auth_provider = LocalAuth()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield SimpleNamespace(client=client, db=db, workspace=workspace, scheduled=scheduled)
        finally:
            await db.close()


async def test_local_upload_duplicate_returns_conflict_without_overwriting(local_upload_env):
    env = local_upload_env
    target_dir = env.workspace / "folder"
    target_dir.mkdir()
    target = target_dir / "report.pdf"
    target.write_bytes(b"old")
    await _seed_upload_doc(env.db, "doc-existing", "report.pdf", "/folder/", "folder/report.pdf")

    resp = await env.client.post(
        "/v1/upload",
        data={"path": "/folder/"},
        files={"file": ("report.pdf", b"new", "application/pdf")},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "code": "duplicate_path",
        "path": "/folder/",
        "filename": "report.pdf",
        "relative_path": "folder/report.pdf",
        "existing_document_id": "doc-existing",
    }
    assert target.read_bytes() == b"old"


async def test_local_upload_replace_preserves_doc_and_clears_stale_extraction(local_upload_env):
    env = local_upload_env
    target_dir = env.workspace / "folder"
    target_dir.mkdir()
    target = target_dir / "report.pdf"
    target.write_bytes(b"old")
    await _seed_upload_doc(env.db, "doc-existing", "report.pdf", "/folder/", "folder/report.pdf")
    await env.db.execute(
        "INSERT INTO document_pages (id, document_id, page, content) "
        "VALUES ('page-1', 'doc-existing', 1, 'old page')",
    )
    await env.db.execute(
        "INSERT INTO document_chunks (id, document_id, chunk_index, content, "
        "source_content, token_count) "
        "VALUES ('chunk-1', 'doc-existing', 0, 'old chunk', 'old chunk', 2)",
    )
    await env.db.commit()

    resp = await env.client.post(
        "/v1/upload",
        data={"path": "/folder/", "on_conflict": "replace"},
        files={"file": ("report.pdf", b"%PDF-1.4\nnew", "application/pdf")},
    )
    await asyncio.sleep(0)

    assert resp.status_code == 201
    assert resp.json()["id"] == "doc-existing"
    assert target.read_bytes() == b"%PDF-1.4\nnew"

    cursor = await env.db.execute(
        "SELECT status, content, page_count, parser, document_number, highlights "
        "FROM documents WHERE id = 'doc-existing'",
    )
    row = await cursor.fetchone()
    page_count = await env.db.execute_fetchall(
        "SELECT COUNT(*) FROM document_pages WHERE document_id = 'doc-existing'",
    )
    chunk_count = await env.db.execute_fetchall(
        "SELECT COUNT(*) FROM document_chunks WHERE document_id = 'doc-existing'",
    )

    assert row == ("pending", None, None, None, 7, "[]")
    assert page_count[0][0] == 0
    assert chunk_count[0][0] == 0
    assert env.scheduled == ["doc-existing"]


async def test_local_upload_disk_only_duplicate_returns_conflict(local_upload_env):
    env = local_upload_env
    target = env.workspace / "report.pdf"
    target.write_bytes(b"old")

    resp = await env.client.post(
        "/v1/upload",
        data={"path": "/"},
        files={"file": ("report.pdf", b"new", "application/pdf")},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "code": "duplicate_path",
        "path": "/",
        "filename": "report.pdf",
        "relative_path": "report.pdf",
        "existing_document_id": None,
    }
    assert target.read_bytes() == b"old"


async def _seed_upload_doc(db, doc_id: str, filename: str, path: str, relative_path: str) -> None:
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, "
        "source_kind, file_type, file_size, status, page_count, content, parser, "
        "document_number, highlights) "
        "VALUES (?, ?, ?, 'Report', ?, ?, 'source', 'pdf', 3, 'ready', 1, "
        "'old extracted text', 'opendataloader', 7, '[{\"id\":\"h1\"}]')",
        (doc_id, USER_ID, filename, path, relative_path),
    )
    await db.commit()


def _load_llmwiki_module():
    path = Path(__file__).resolve().parents[2] / "llmwiki"
    loader = importlib.machinery.SourceFileLoader("llmwiki_cli_under_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
