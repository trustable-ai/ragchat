"""
Fulltext search over RAG documents in Postgres using ts_rank.

Uses ctx.POSTGRESQL. Schema (rag_documents) is owned by setup/database.
"""
# re-zip trigger


def main(args, ctx=None):
    """
    Fulltext search over rag_documents.

    Args:
        args: dict with:
            - input: query text (required)
            - categoria: filter by category (optional, empty = all)
            - top_k: max results (default 15)
    """
    if not ctx or not hasattr(ctx, "POSTGRESQL") or ctx.POSTGRESQL is None:
        return {"ok": False, "error": "Database not configured"}

    query = args.get("input", "").strip()
    categoria = args.get("categoria", "").strip()
    top_k = int(args.get("top_k", 15))

    if not query:
        return {"ok": False, "error": "input (query text) is required"}

    conn = ctx.POSTGRESQL
    try:
        # OR logic: split words, join with |
        words = query.split()
        or_query = " | ".join(words)

        sql = """
            SELECT filename, categoria, doc_id, chunk_index, content,
                   ts_rank(content_tsv, to_tsquery('english', %s)) AS rank
            FROM rag_documents
            WHERE content_tsv @@ to_tsquery('english', %s)
            AND (categoria = %s OR %s = '')
            ORDER BY rank DESC
            LIMIT %s
        """

        with conn.cursor() as cur:
            cur.execute(sql, (or_query, or_query, categoria, categoria, top_k))
            rows = cur.fetchall()

        # Fallback: ILIKE if fulltext finds nothing
        if not rows:
            like_pattern = "%" + "%".join(words) + "%"
            sql2 = """
                SELECT filename, categoria, doc_id, chunk_index, content, 0.5 AS rank
                FROM rag_documents
                WHERE content ILIKE %s
                AND (categoria = %s OR %s = '')
                ORDER BY created_at DESC
                LIMIT %s
            """
            with conn.cursor() as cur:
                cur.execute(sql2, (like_pattern, categoria, categoria, top_k))
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
