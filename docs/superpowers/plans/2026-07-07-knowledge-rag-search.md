# Knowledge RAG Search Plan

## Goal

Upgrade the knowledge search base from simple document filtering to source-chunk retrieval suitable for RAG prompts.

## Steps

1. Keep document chunking as the durable retrieval unit.
2. Synchronize chunk writes with the SQLite FTS5 table when FTS5 is available.
3. Merge FTS and lexical fallback results with reciprocal-rank scoring.
4. Return source metadata for citations: base, document, chunk, chunk index, source name, snippet, score.

## Acceptance

- Search returns ranked chunks with source metadata.
- Document updates refresh the retrievable chunks.
- Document deletes remove retrievable chunks.
- If FTS5 is unavailable, lexical search still works.
