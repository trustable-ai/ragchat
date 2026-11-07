"""
List documents stored in rag_documents, grouped by filename/categoria/doc_id.
"""
# re-zip trigger
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


def documents(args):
    """
    List documents grouped by filename, categoria, doc_id.

    Args:
        args: dict with:
            - categoria: filter by category (optional, empty = all)
            - POSTGRES_URL: connection string

    Returns:
        dict with documents list and num_documents count
    """
    categoria = args.get("categoria", "")
    postgres_url = args.get("POSTGRES_URL")

    if not postgres_url:
        return {"ok": False, "error": "POSTGRES_URL not configured"}

    try:
        with psycopg.connect(postgres_url) as conn:
            ensure_table(conn)

            base_query = """
                SELECT filename, categoria, doc_id,
                       COUNT(*) as num_chunks,
                       MIN(created_at) as created_at
                FROM rag_documents
            """

            if categoria:
                base_query += " WHERE categoria = %s"
                base_query += " GROUP BY filename, categoria, doc_id ORDER BY MIN(created_at) DESC"
                params = (categoria,)
            else:
                base_query += " GROUP BY filename, categoria, doc_id ORDER BY MIN(created_at) DESC"
                params = ()

            with conn.cursor() as cur:
                cur.execute(base_query, params)
                rows = cur.fetchall()

            docs = []
            for row in rows:
                docs.append({
                    "filename": row[0],
                    "categoria": row[1],
                    "doc_id": row[2],
                    "num_chunks": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                })

            return {
                "documents": docs,
                "num_documents": len(docs),
            }

    except Exception as e:
        return {"ok": False, "error": str(e)}
