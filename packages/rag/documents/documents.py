"""
List documents stored in rag_documents, grouped by filename/categoria/doc_id.

Uses ctx.POSTGRESQL. Schema (rag_documents) is owned by setup/database.
"""
# re-zip trigger


def main(args, ctx=None):
    """
    List documents grouped by filename, categoria, doc_id.

    Args:
        args: dict with:
            - categoria: filter by category (optional, empty = all)
    """
    if not ctx or not hasattr(ctx, "POSTGRESQL") or ctx.POSTGRESQL is None:
        return {"ok": False, "error": "Database not configured"}

    categoria = args.get("categoria", "")
    conn = ctx.POSTGRESQL

    try:
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
