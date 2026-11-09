"""
Store chunks in Postgres with tsvector fulltext search.

Uses ctx.POSTGRESQL. Schema (rag_documents) is owned by setup/database.
"""
import re
import uuid


def _normalize_filename(filename):
    """Normalize a filename into a readable source label.

    'Invoice_CloudBridge_102026.pdf' -> 'Invoice CloudBridge 1026'.
    Strips directory, extension, and turns separators into spaces so the
    label is tokenized correctly by tsvector/trigram/ILIKE.
    """
    name = filename or ""
    name = name.rsplit("/", 1)[-1]
    name = re.sub(r"\.(pdf|txt|docx?|csv|xlsx?)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[_-]+", " ", name)
    return name.strip()


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
    source_label = _normalize_filename(filename)
    try:
        with conn.cursor() as cur:
            # Dedup: delete old chunks for same filename
            cur.execute(
                "DELETE FROM rag_documents WHERE filename = %s",
                (filename,)
            )

            # Insert each chunk. Prepend a 'Source: <label>' line so the
            # filename is part of the searchable content: this lets queries by
            # brand/name hit even when the body text does not mention it.
            for ch in normalized:
                content = ch["content"]
                if source_label:
                    content = f"Source: {source_label}\n{content}"
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
                        content,
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
