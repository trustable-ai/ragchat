"""
Idempotent database setup for the RAG app.

Creates the rag_documents and rag_categories tables and all indexes.
Safe to run repeatedly (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS).
All schema ownership lives here; business modules must never run DDL.
"""
# re-zip trigger


RAG_DOCUMENTS_DDL = """
CREATE TABLE IF NOT EXISTS rag_documents (
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
CREATE INDEX IF NOT EXISTS idx_rag_docs_tsv ON rag_documents USING GIN(content_tsv);
CREATE INDEX IF NOT EXISTS idx_rag_docs_categoria ON rag_documents(categoria);
CREATE INDEX IF NOT EXISTS idx_rag_docs_doc_id ON rag_documents(doc_id);
CREATE INDEX IF NOT EXISTS idx_rag_docs_filename ON rag_documents(filename);
"""

# Migrate the generated tsvector column from 'english' to 'simple' so the
# fulltext tier works for mixed-language documents (English + Italian).
# 'simple' does no stemming and no stopword removal, which is the right
# tradeoff for invoices/contracts that may be in either language. Idempotent:
# only runs when the existing column definition still uses 'english'. The
# check + conditional ALTER is done from Python (not a DO block) to avoid
# dollar-quoting pitfalls in the action runtime.
RAG_TSV_NEEDS_MIGRATION_SQL = """
SELECT EXISTS (
    SELECT 1
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
    WHERE c.relname = 'rag_documents'
      AND a.attname = 'content_tsv'
      AND pg_get_expr(d.adbin, d.adrelid) LIKE '%english%'
)
"""

RAG_TSV_DROP_SQL = "ALTER TABLE rag_documents DROP COLUMN content_tsv;"
RAG_TSV_ADD_SQL = (
    "ALTER TABLE rag_documents ADD COLUMN content_tsv TSVECTOR "
    "GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED;"
)
RAG_TSV_REINDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_rag_docs_tsv "
    "ON rag_documents USING GIN(content_tsv);"
)

RAG_TRGM_DDL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_rag_docs_trgm ON rag_documents USING GIN(content gin_trgm_ops);
"""

RAG_CATEGORIES_DDL = """
CREATE TABLE IF NOT EXISTS rag_categories (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
"""


def main(args, ctx=None):
    if not ctx or not hasattr(ctx, "POSTGRESQL") or ctx.POSTGRESQL is None:
        return {"ok": False, "error": "Database not configured"}

    conn = ctx.POSTGRESQL
    migrated = False
    try:
        with conn.cursor() as cur:
            cur.execute(RAG_DOCUMENTS_DDL)
            cur.execute(RAG_TRGM_DDL)
            cur.execute(RAG_CATEGORIES_DDL)

            # Migrate tsvector config 'english' -> 'simple' if needed.
            cur.execute(RAG_TSV_NEEDS_MIGRATION_SQL)
            needs_migration = bool(cur.fetchone()[0])
            if needs_migration:
                cur.execute(RAG_TSV_DROP_SQL)
                cur.execute(RAG_TSV_ADD_SQL)
                cur.execute(RAG_TSV_REINDEX_SQL)
                migrated = True
        conn.commit()
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)}

    result = {
        "ok": True,
        "tables": ["rag_documents", "rag_categories"],
        "extensions": ["pg_trgm"],
        "fts_config": "simple",
    }
    if migrated:
        result["migrated_from"] = "english"
    return result
