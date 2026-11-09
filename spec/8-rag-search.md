# RAG Search & Ingest — Retrieval Architecture

## Overview

The RAG app retrieves document chunks from Postgres (`rag_documents` table)
using a three-tier search with score blending and adjacent-chunk expansion,
then feeds the results to an LLM as context.

Three actions own the retrieval surface:

- `rag/search` — search-only endpoint (returns ranked chunks)
- `v1/ragchat` — search + LLM response generation (used by the frontend)
- `rag/store` — chunk storage (prepends a `Source:` label to each chunk)

The schema (tables, extensions, indexes, generated columns) is owned
exclusively by `setup/database`; business modules never run DDL.

## Schema (`setup/database`)

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
```

- **`content_tsv`** uses the `'simple'` text-search config (no stemming, no
  stopword removal) so the fulltext tier works for mixed-language documents
  (English + Italian). Stopwords are stripped in the query tier instead.
- **`pg_trgm`** extension is installed (trusted) with a `GIN(content
  gin_trgm_ops)` index for fuzzy/typo matching via `word_similarity()`.

### Migration

`setup/database` migrates an existing `content_tsv` column from `'english'` to
`'simple'` idempotently: it checks `pg_attrdef` for the generated-column
expression, and if it still references `'english'`, drops the column, re-adds
it with `'simple'`, and rebuilds the GIN index. The check + conditional ALTER
is done from Python (not a SQL `DO` block) to avoid dollar-quoting issues in
the action runtime.

## Ingest: `Source:` label (`rag/store`)

Before inserting each chunk, `rag/store` prepends a normalized source label
to the content:

```
Source: <normalized filename>
<chunk body>
```

The filename is normalized (`Invoice_CloudBridge_102026.pdf` → `Invoice
CloudBridge 102026`): directory and extension stripped, underscores/hyphens
turned to spaces. This makes the filename part of the searchable content, so a
query by brand or document name hits even when the body text does not mention
it. All three search tiers (tsvector, trigram, ILIKE) see the label because it
is part of `content`.

Documents ingested before this change do not have the label; re-ingest them to
benefit. For existing documents where the brand is already in the body, the
label is a bonus, not a requirement.

## Search tiers (`rag/search`, `v1/ragchat`)

Both actions share the same retrieval logic (`v1/ragchat` keeps a
`fulltext_search` wrapper for compatibility that delegates to `rag_search`).

### Query preprocessing

- Lowercase, strip punctuation, collapse whitespace.
- Produce `tokens` (all) and `stripped` (stopwords removed). The stopword list
  is English-only and applies to the trigram/ILIKE tiers and to the tsvector
  query (since `'simple'` does no stopword removal of its own).

### Tier 1 — tsvector fulltext

`plainto_tsquery('simple', <stripped>)` + `ts_rank_cd`. `ts_rank_cd` is
non-normalized, so the score is divided by the max rank in the result set
before blending.

### Tier 2 — pg_trgm `word_similarity`

`word_similarity(<query phrase>, content)` measures how well the query matches
a *substring* of the content (unlike `similarity()`, which compares whole
strings). This is the right operator for typo-tolerant search inside long
chunks. Threshold default `0.2`. Uses the function directly (not the `<%`
operator) so the threshold is honored; the operator filters on
`pg_trgm.similarity_threshold` which would ignore a lower threshold.

### Tier 3 — ILIKE OR per keyword

`content ILIKE %keyword%` joined with `OR`. This fixes the old buggy
`"%word1%word2%..."` pattern that required words in order and almost never
matched.

### Score blending

Each chunk's blended score is:

```
0.6 * (ts_rank / max_ts_rank)   # if found by tsvector
  + 0.3 * (word_sim / max_word_sim)   # if found by trigram
  + 0.1                              # if found by ILIKE
```

Tiers fill gaps: a chunk found by multiple tiers sums contributions. The raw
tier rank is replaced by the blended score in the returned rows.

### Adjacent-chunk expansion

After ranking the top-`k` primary hits, each hit's neighbors (`chunk_index ±1`)
are fetched for richer context. **Relevance order is preserved**: primary hits
are walked in blended-score order and each one's unseen neighbors are appended
right after it, so the most relevant chunk stays first while its context
follows. The total is capped at `top_k * 3`.

This is better than flattening the whole set by `(doc_id, chunk_index)`, which
would destroy relevance ordering (the most relevant chunk could be pushed down
by document-id ordering).

### Debug mode

`rag/search` accepts `debug: true` to return per-tier raw ranks and tier
counts for the top 5 hits, for ranking diagnostics. It does not change
behavior.

## Suggested questions (`rag/questions`)

The app generates suggested questions per category to help users start a
conversation. Questions are generated lazily via LLM on first access and cached
in `rag_suggested_questions` (linked to the document, so `rag/delete-doc`
cascades the cleanup).

### Schema

```sql
CREATE TABLE rag_suggested_questions (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    categoria TEXT NOT NULL DEFAULT '',
    doc_id TEXT NOT NULL,
    question TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Generation flow

1. Frontend calls `rag/questions` with a `categoria`.
2. The action finds documents in that category without cached questions.
3. For each, it sends the first chunk (capped at 1500 chars) to the LLM with
   a prompt asking for 3 concise, answerable questions.
4. Generated questions are saved in `rag_suggested_questions`.
5. The action returns the top-`max` (default 5) cached questions for the
   category.

If the LLM call fails (rate limit, timeout, missing credentials), a
deterministic fallback is used (filename-based: "What are the key details in
<X>?"). This ensures the endpoint always returns something useful.

A `regenerate=true` parameter forces regeneration (deletes cached questions
for the category and regenerates). A `time.sleep(1)` rate-limits between LLM
calls to avoid 429 errors.

### Frontend

In the chat empty state, when a specific category is selected (not "All") and
the category has indexed documents, the frontend fetches suggested questions
and renders them as clickable chips. Clicking a chip sends it as a message.

## Language note

The `'simple'` config is the tradeoff chosen for mixed-language corpora. It
loses stemming (so `"running"` does not match `"run"`), but:
- it is correct for Italian documents (where English stemming would be wrong);
- the trigram and ILIKE tiers compensate for misspellings and partial matches;
- stopword stripping in the query tier keeps precision high.

If all documents are known to be a single language, switching the generated
column and the `plainto_tsquery` config to that language's config would
improve stemming-based recall at the cost of multi-language robustness.
