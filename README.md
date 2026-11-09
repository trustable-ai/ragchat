# ragchat

A **Retrieval-Augmented Generation (RAG)** application for querying PDF documents
through a chat interface. Upload PDFs, extract their text, chunk and index them in
PostgreSQL, then ask questions answered exclusively from the indexed content with
source citations.

Built on **Trustant / OpenServerless**: React + Vite + Tailwind frontend, Python
OpenServerless actions backend, PostgreSQL for retrieval, S3 for document storage,
and Apache Tika for text extraction.

---

## Architecture

```
Browser ──▶ Vite (src/) ──▶ /api/my/v1/ragchat ──▶ Postgres 3-tier search ──▶ LLM
                              /api/my/rag/*         (rag_documents)            (OpenAI-compatible)
                                     │
                                     ├── S3 (PDF + extracted text)
                                     └── Tika (tika:9998, text extraction)
```

### Ingestion pipeline

1. `rag/upload` — browser uploads the PDF in `<1 MB` parts to S3 (`<user>-data`).
2. `rag/ingest` — reassembles parts, sends to Tika (`tika:9998/tika`), stores
   extracted text back to S3.
3. `rag/chunk` — splits the extracted text into chunks.
4. `rag/store` — inserts chunks into `rag_documents`, prepending a normalized
   `Source: <filename>` label to each chunk so the filename is searchable too.

### Retrieval pipeline

`rag/search` (and `v1/ragchat`, which wraps it) runs a **three-tier search**
with score blending, then expands adjacent chunks for richer context.

| Tier | Method | Handles | Weight |
|------|--------|---------|--------|
| 1 | `tsvector` fulltext (`plainto_tsquery`, `'simple'` config) | exact keyword matches | 0.6 |
| 2 | `pg_trgm` `word_similarity` | typos / partial matches | 0.3 |
| 3 | `ILIKE OR` per keyword | broad substring fallback | 0.1 |

- `content_tsv` uses the `'simple'` text-search config (no stemming) so it works
  for mixed-language documents (English + Italian). Stopwords are stripped in the
  query tier, not by the config.
- Scores are normalized per tier by the max rank in the result set before blending.
- After ranking the top-`k` primary hits, each hit's `chunk_index ±1` neighbors
  are fetched for context, **preserving relevance order** (the most relevant chunk
  stays first, its neighbors follow). Total capped at `top_k × 3`.

### Answer generation (`v1/ragchat`)

1. Runs the three-tier search over `rag_documents`.
2. Builds a context string labeling each chunk by source: `[Source: <filename>]`.
3. Sends to the LLM with a system prompt that enforces: answer **only** from the
   context, cite sources by filename, never invent information.
4. Returns `{output, sources[], num_chunks_used}`.

A `debug: true` flag on `rag/search` returns per-tier raw ranks for ranking
diagnostics.

---

## Actions

All backend logic lives in `packages/<package>/<action>/<module>.py`. The
`__main__.py` wrappers are generated and must not be edited.

### Private setup actions (`packages/setup/`)

| Action | Responsibility |
|--------|----------------|
| `setup/database` | Idempotent DDL: creates `rag_documents`, `rag_categories`, `rag_suggested_questions`; installs `pg_trgm`; builds GIN indexes; migrates `content_tsv` from `'english'` to `'simple'`. **Owns all schema — business modules never run DDL.** |

### RAG actions (`packages/rag/`)

| Action | Responsibility |
|--------|----------------|
| `rag/upload` | Chunked S3 upload (`<1 MB` parts) |
| `rag/ingest` | PDF → S3 → Tika text extraction → S3 |
| `rag/chunk` | Splits extracted text into chunks |
| `rag/store` | Inserts chunks into Postgres with `Source:` label |
| `rag/search` | Three-tier search (retrieval only, no LLM) |
| `rag/questions` | Suggested questions per category (LLM-generated, DB-cached) |
| `rag/categories` | Lists categories |
| `rag/documents` | Lists ingested documents |
| `rag/delete-doc` | Deletes a document (cascades suggested questions) |
| `rag/clean` | Cleanup |

### Public API actions (`packages/v1/`)

| Action | Responsibility |
|--------|----------------|
| `v1/ragchat` | Search + LLM response generation (used by the frontend) |
| `v1/chat` | Basic chat with `doc.jsonl` as static context |

Public endpoints are reachable at `/api/my/<package>/<action>`.

---

## Database schema

Owned exclusively by `setup/database` (idempotent `CREATE TABLE IF NOT EXISTS`).

```sql
CREATE TABLE rag_documents (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    categoria TEXT NOT NULL DEFAULT '',
    doc_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE rag_categories (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE rag_suggested_questions (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    categoria TEXT NOT NULL DEFAULT '',
    doc_id TEXT NOT NULL,
    question TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

Indexes: GIN on `content_tsv`, GIN `gin_trgm_ops` on `content` (via `pg_trgm`),
plus btree indexes on `categoria`, `doc_id`, `filename`.

---

## Service access pattern

Actions use the **Trustant builder pattern** (standard, not an exception):

- `action_add_postgresql` generates the `ctx.POSTGRESQL` connection wiring.
  Editable modules use `conn = ctx.POSTGRESQL` and `with conn.cursor() as cur`.
  No `psycopg2` imports, no manual `connect()`, no hardcoded credentials.
- `action_add_s3` generates `ctx.S3_CLIENT` / `ctx.S3_DATA`. Actions read/write
  the `<user>-data` bucket and never call `list_buckets()`.
- AI credentials (`AI_BASE_URL`, `AI_API_KEY`, `AI_CHAT_MODEL`) are bound as
  secrets and exposed on `ctx` by the generated builder.

`setup/database` running DDL through `ctx.POSTGRESQL` is the prescribed Trustant
pattern — schema ownership lives in setup actions, business modules consume the
generated connection. Direct `psql` / MCP writes to create schema or seed data
are explicitly forbidden.

---

## Frontend

- `src/pages/Index.tsx` — chat UI: message history, streaming responses,
  category filter, suggested-question chips, Reset and RAG buttons.
- Calls actions via relative `/api/my/...` URLs.

---

## Development

```bash
# Frontend typecheck + build
npm run build

# Python action syntax check
python3 -m compileall packages

# Action contract checker (after watcher settles)
timeout 60 check_openserverless_actions.sh .

# Re-run setup after setup/database changes
timeout 120 ops ide setup
```

Trustant manages the Vite dev server (`http://localhost:5173`) and the
`ops ide devel` watcher. Do not start them manually.

## Specifications

- `spec/6-chat.md` — chat message handling
- `spec/7-chatui.md` — chat UI
- `spec/8-rag-search.md` — retrieval architecture (detailed)
