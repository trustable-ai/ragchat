"""
Store chunks in Postgres with tsvector fulltext search.
"""
import uuid
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


def store(args):
    """
    Store chunks in Postgres.

    Args:
        args: dict with:
            - chunks: list of strings or dicts
            - filename: source filename
            - categoria: category label (default '')
            - POSTGRES_URL: connection string

    Returns:
        dict with ok, num_stored, doc_id, filename
    """
    chunks = args.get("chunks", [])
    filename = args.get("filename", "")
    categoria = args.get("categoria", "")

    if not chunks:
        return {"ok": False, "error": "No chunks provided"}
    if not filename:
        return {"ok": False, "error": "No filename provided"}

    postgres_url = args.get("POSTGRES_URL")
    if not postgres_url:
        return {"ok": False, "error": "POSTGRES_URL not configured"}

    doc_id = uuid.uuid4().hex[:8]
    total_chunks = len(chunks)

    # Normalize chunks: if strings, wrap with metadata
    normalized = []
    for i, chunk in enumerate(chunks):
        if isinstance(chunk, str):
            normalized.append({
                "filename": filename,
                "categoria": categoria,
                "doc_id": doc_id,
                "chunk_index": i,
                "total_chunks": total_chunks,
                "content": chunk,
            })
        elif isinstance(chunk, dict):
            normalized.append({
                "filename": chunk.get("filename", filename),
                "categoria": chunk.get("categoria", categoria),
                "doc_id": chunk.get("doc_id", doc_id),
                "chunk_index": chunk.get("chunk_index", i),
                "total_chunks": chunk.get("total_chunks", total_chunks),
                "content": chunk.get("content", ""),
            })

    try:
        with psycopg.connect(postgres_url) as conn:
            ensure_table(conn)

            with conn.cursor() as cur:
                # Dedup: delete old chunks for same filename
                cur.execute(
                    "DELETE FROM rag_documents WHERE filename = %s",
                    (filename,)
                )

                # Insert each chunk
                for ch in normalized:
                    cur.execute(
                        """INSERT INTO rag_documents
                           (filename, categoria, doc_id, chunk_index, total_chunks, content)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (
                            ch["filename"],
                            ch["categoria"],
                            ch["doc_id"],
                            ch["chunk_index"],
                            ch["total_chunks"],
                            ch["content"],
                        )
                    )

            conn.commit()

        return {
            "ok": True,
            "num_stored": len(normalized),
            "doc_id": doc_id,
            "filename": filename,
        }

    except Exception as e:
        return {"ok": False, "error": str(e)}
