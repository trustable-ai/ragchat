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
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rag_docs_tsv ON rag_documents USING GIN(content_tsv);
CREATE INDEX IF NOT EXISTS idx_rag_docs_categoria ON rag_documents(categoria);
CREATE INDEX IF NOT EXISTS idx_rag_docs_doc_id ON rag_documents(doc_id);
CREATE INDEX IF NOT EXISTS idx_rag_docs_filename ON rag_documents(filename);
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
    try:
        with conn.cursor() as cur:
            cur.execute(RAG_DOCUMENTS_DDL)
            cur.execute(RAG_CATEGORIES_DDL)
        conn.commit()
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)}

    return {"ok": True, "tables": ["rag_documents", "rag_categories"]}
