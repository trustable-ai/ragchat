"""
Store chunks in Postgres with tsvector fulltext search.

Uses ctx.POSTGRESQL. Schema (rag_documents) is owned by setup/database.
"""
import uuid


def main(args, ctx=None):
    """
    Store chunks in Postgres.

    Args:
        args: dict with:
            - chunks: list of strings or dicts
            - filename: source filename
            - categoria: category label (default '')

    Returns:
        dict with ok, num_stored, doc_id, filename
    """
    if not ctx or not hasattr(ctx, "POSTGRESQL") or ctx.POSTGRESQL is None:
        return {"ok": False, "error": "Database not configured"}

    chunks = args.get("chunks", [])
    filename = args.get("filename", "")
    categoria = args.get("categoria", "")

    if not chunks:
        return {"ok": False, "error": "No chunks provided"}
    if not filename:
        return {"ok": False, "error": "No filename provided"}

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

    conn = ctx.POSTGRESQL
    try:
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
        conn.rollback()
        return {"ok": False, "error": str(e)}
