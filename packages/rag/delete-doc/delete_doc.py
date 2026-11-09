"""
Delete a document from rag_documents by doc_id or filename.

This action uses the Trustant builder pattern: ctx.POSTGRESQL is a live
psycopg connection injected by the generated wrapper. No DDL here — schema
ownership lives in setup/database.
"""


def main(args, ctx=None):
    """
    Delete document chunks by doc_id or filename.

    Args:
        args: dict with:
            - doc_id: document ID to delete
            - filename: filename to delete (fallback)
    """
    if not ctx or not hasattr(ctx, "POSTGRESQL") or ctx.POSTGRESQL is None:
        return {"ok": False, "error": "Database not configured"}

    doc_id = (args.get("doc_id") or "").strip()
    filename = (args.get("filename") or "").strip()

    if not doc_id and not filename:
        return {"ok": False, "error": "doc_id or filename is required"}

    conn = ctx.POSTGRESQL
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM rag_documents WHERE doc_id = %s OR filename = %s",
                (doc_id, filename),
            )
            deleted = cur.rowcount
            # Cascade: remove suggested questions for the same document.
            cur.execute(
                "DELETE FROM rag_suggested_questions WHERE doc_id = %s OR filename = %s",
                (doc_id, filename),
            )
        conn.commit()
        return {"ok": True, "deleted": deleted}
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)}
