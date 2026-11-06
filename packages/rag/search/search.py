"""
Fulltext search over RAG documents in Postgres using ts_rank.
"""
import psycopg


DDL = """
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


def ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def search(args):
    """
    Fulltext search over rag_documents.

    Args:
        args: dict with:
            - input: query text (required)
            - categoria: filter by category (optional, empty = all)
            - top_k: max results (default 15)
            - POSTGRES_URL: connection string

    Returns:
        dict with results list and num_results count
    """
    query = args.get("input", "").strip()
    categoria = args.get("categoria", "").strip()
    top_k = int(args.get("top_k", 15))

    if not query:
        return {"ok": False, "error": "input (query text) is required"}

    postgres_url = args.get("POSTGRES_URL")
    if not postgres_url:
        return {"ok": False, "error": "POSTGRES_URL not configured"}

    try:
        with psycopg.connect(postgres_url) as conn:
            ensure_table(conn)

            sql = """
                SELECT filename, categoria, doc_id, chunk_index, content,
                       ts_rank(content_tsv, plainto_tsquery('english', %s)) AS rank
                FROM rag_documents
                WHERE content_tsv @@ plainto_tsquery('english', %s)
                AND (categoria = %s OR %s = '')
                ORDER BY rank DESC
                LIMIT %s
            """

            with conn.cursor() as cur:
                cur.execute(sql, (query, query, categoria, categoria, top_k))
                rows = cur.fetchall()

            results = []
            for row in rows:
                results.append({
                    "text": row[4],
                    "filename": row[0],
                    "categoria": row[1],
                    "doc_id": row[2],
                    "chunk_index": row[3],
                    "score": float(row[5]),
                })

            return {
                "results": results,
                "num_results": len(results),
            }

    except Exception as e:
        return {"ok": False, "error": str(e)}
