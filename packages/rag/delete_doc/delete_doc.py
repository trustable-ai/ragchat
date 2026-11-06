"""
Delete a document from rag_documents by doc_id or filename.
"""
import psycopg


def delete_doc(args):
    """
    Delete document chunks by doc_id or filename.

    Args:
        args: dict with:
            - doc_id: document ID to delete
            - filename: filename to delete (fallback)
            - POSTGRES_URL: connection string

    Returns:
        dict with ok and deleted count
    """
    doc_id = args.get("doc_id", "").strip()
    filename = args.get("filename", "").strip()

    if not doc_id and not filename:
        return {"ok": False, "error": "doc_id or filename is required"}

    postgres_url = args.get("POSTGRES_URL")
    if not postgres_url:
        return {"ok": False, "error": "POSTGRES_URL not configured"}

    try:
        with psycopg.connect(postgres_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM rag_documents WHERE doc_id = %s OR filename = %s",
                    (doc_id, filename)
                )
                deleted = cur.rowcount
            conn.commit()

        return {"ok": True, "deleted": deleted}

    except Exception as e:
        return {"ok": False, "error": str(e)}
