# Highlights in Search Spec

## Purpose

User highlights and comments should be visible to MCP search without making
`documents.highlights` the primary search surface. Search continues to query
`document_chunks.content`; highlight text is materialized into that column only
for chunks touched by a highlight.

## Storage Model

- `documents.highlights` remains the canonical JSONB highlight store.
- `document_chunks.source_content` stores the original chunk text produced by
  the chunker.
- `document_chunks.annotations_text` stores rendered highlight/comment footnotes
  for highlights mapped to that chunk, or `NULL` when none apply.
- `document_chunks.has_highlight` supports the annotated-only search filter.
- `document_chunks.content` is materialized as `source_content` plus
  `annotations_text`, preserving the existing search index target.

## Materialization Flow

Highlight writes go through the document highlight CRUD path. In the same write
flow, the repository code compares old and new highlights, finds every chunk
touched by either set, and rewrites only those chunk rows. This catches creates,
updates, and deletes without rebuilding the whole document index.

Mapping rules live in `api/services/highlight_chunks.py`:

- PDF highlights first match by page, then prefer the smallest chunk containing
  the normalized selected text.
- Text highlights prefer overlapping character ranges and use text matching as
  fallback.
- Legacy anchors use normalized selected-text matching.
- If no chunk can be mapped, the highlight remains canonical in
  `documents.highlights` but no chunk annotation is materialized.

Rendered annotations use deterministic per-chunk footnote IDs:

```text
[^user-1]: User highlighted "quoted text" - user note: optional comment
```

## Search Behavior

- Default search can match either source text or materialized annotation text.
- Annotated-only search filters to chunks with `has_highlight = true`.
- Search results can distinguish direct annotation hits from source hits on
  annotated chunks when the backend supports that distinction.

## Verification

Keep these scenarios covered by tests:

- Creating a highlight sets `annotations_text`, `has_highlight`, and updated
  `content` on the mapped chunk.
- Deleting a highlight clears stale annotations and restores `content` to
  `source_content` when no highlights remain.
- Updating a comment refreshes the materialized annotation.
- Multiple highlights in one chunk render in stable order.
- PDF page mapping and text-range mapping both select the intended chunks.
