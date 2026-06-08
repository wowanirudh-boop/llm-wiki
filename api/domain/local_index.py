"""Shared helpers for local filesystem indexing."""

from __future__ import annotations

import hashlib
from pathlib import Path

TEXT_EXTENSIONS = frozenset({
    "md", "txt", "csv", "html", "svg", "json", "xml", "yaml", "yml",
    "toml", "ini", "cfg", "rst", "tex", "latex",
})


def relative_path_for(workspace: Path, file_path: Path) -> str:
    return file_path.relative_to(workspace).as_posix()


def legacy_relative_path_for(workspace: Path, file_path: Path) -> str:
    return str(file_path.relative_to(workspace))


def folder_path_for(relative_path: str) -> str:
    parts = relative_path.split("/")
    if len(parts) <= 1:
        return "/"
    return "/" + "/".join(parts[:-1]) + "/"


def source_kind_for(relative_path: str) -> str:
    return "wiki" if relative_path.startswith("wiki/") else "source"


def extension_for(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def title_for(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return stem.replace("-", " ").replace("_", " ").strip().title()


def read_text_content(file_path: Path, ext: str) -> str | None:
    if ext not in TEXT_EXTENSIONS:
        return None
    try:
        return file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def hash_file(file_path: Path, max_bytes: int = 100_000_000) -> str | None:
    try:
        if file_path.stat().st_size >= max_bytes:
            return None
        return hashlib.sha256(file_path.read_bytes()).hexdigest()
    except Exception:
        return None


def status_for_content(content: str | None) -> str:
    return "ready" if content is not None else "pending"
