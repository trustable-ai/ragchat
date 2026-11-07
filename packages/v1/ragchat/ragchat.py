"""
RAG Chat: Postgres fulltext search + LLM response generation.

Uses ctx.POSTGRESQL. Schema (rag_documents) is owned by setup/database.
"""
# re-zip trigger
from openai import OpenAI


SYSTEM_PROMPT = """You are an intelligent document assistant. Answer questions based EXCLUSIVELY on the context provided.

Rules:
- Always answer in English
- Cite sources using ONLY the filename (e.g. "According to Invoice_EnergyPlus_092026.pdf")
- If the question mentions a specific company or document, use ONLY information from matching documents
- When multiple documents contain relevant info, present EACH separately with clear headings
- Never mix data from different documents in the same paragraph
- If context insufficient, say so clearly
- Do not make up information not in context
- Use structured format (bullet points, tables) when comparing
- Be concise and direct — answer first, then details"""


def fulltext_search(conn, query, categoria="", top_k=15):
    """Run fulltext search with OR logic and ILIKE fallback."""
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

    return rows


def build_context(rows):
    """Build context string from search results, labeling each chunk by source."""
    chunks = []
    for row in rows:
        filename = row[0]
        content = row[4]
        chunks.append(f"[Source: {filename}]\n{content}")
    return "\n\n---\n\n".join(chunks)


def collect_sources(rows, min_score=0.01):
    """Collect unique sources with score above threshold."""
    seen = set()
    sources = []
    for row in rows:
        filename = row[0]
        categoria = row[1]
        score = float(row[5])
        if score > min_score and filename not in seen:
            seen.add(filename)
            sources.append({
                "filename": filename,
                "categoria": categoria,
                "score": round(score, 4),
            })
    return sources


def list_documents(conn):
    """List distinct ingested documents with categoria and chunk count."""
    sql = """
        SELECT filename, categoria, COUNT(*) AS chunks, MAX(created_at) AS last
        FROM rag_documents
        GROUP BY filename, categoria
        ORDER BY filename
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    docs = []
    for row in rows:
        docs.append({
            "filename": row[0],
            "categoria": row[1],
            "chunks": row[2],
            "last_ingested": row[3].isoformat() if row[3] else None,
        })
    return docs


def main(args, ctx=None):
    """
    RAG Chat: search documents then generate LLM response.

    Args:
        args: dict with:
            - input: user question (required); "all" lists ingested documents
            - categoria: filter by category (optional)
            - top_k: max chunks to retrieve (default 15)
            - history: conversation history [{role, content}, ...] (optional)
            - AI_BASE_URL: LLM API base URL
            - AI_API_KEY: LLM API key
            - AI_CHAT_MODEL: LLM model name
    """
    if not ctx or not hasattr(ctx, "POSTGRESQL") or ctx.POSTGRESQL is None:
        return {"ok": False, "error": "Database not configured"}

    query = args.get("input", "").strip()
    categoria = args.get("categoria", "").strip()
    top_k = int(args.get("top_k", 15))
    history = args.get("messages", args.get("history", []))

    conn = ctx.POSTGRESQL

    # "all": list ingested documents (no LLM call needed)
    if query.lower() == "all":
        try:
            docs = list_documents(conn)
        except Exception as e:
            return {"ok": False, "error": f"Database error: {e}"}
        if not docs:
            return {"output": "No documents ingested yet.", "documents": [], "count": 0}
        lines = [f"Ingested documents ({len(docs)}):"]
        for d in docs:
            cat = f" [{d['categoria']}]" if d["categoria"] else ""
            lines.append(f"- {d['filename']}{cat} ({d['chunks']} chunks)")
        return {
            "output": "\n".join(lines),
            "documents": docs,
            "count": len(docs),
        }

    if not query:
        return {"ok": False, "error": "input (question) is required"}

    # AI credentials from builder context (secret bindings), with args fallback
    ai_base_url = getattr(ctx, "AI_BASE_URL", None) or args.get("AI_BASE_URL")
    ai_api_key = getattr(ctx, "AI_API_KEY", None) or args.get("AI_API_KEY")
    ai_model = getattr(ctx, "AI_CHAT_MODEL", None) or args.get("AI_CHAT_MODEL")

    if not ai_base_url or not ai_api_key or not ai_model:
        return {"ok": False, "error": "AI_BASE_URL, AI_API_KEY, and AI_CHAT_MODEL are required"}

    # --- Search ---
    try:
        rows = fulltext_search(conn, query, categoria, top_k)
    except Exception as e:
        return {"ok": False, "error": f"Database error: {e}"}

    if not rows:
        return {
            "output": "No matching documents found for your query.",
            "sources": [],
            "num_chunks_used": 0,
        }

    # --- Build context and sources ---
    context = build_context(rows)
    sources = collect_sources(rows)
    num_chunks_used = len(rows)

    # --- Build messages ---
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add conversation history (if any)
    if isinstance(history, list):
        for msg in history:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                messages.append({"role": msg["role"], "content": msg["content"]})

    # Add user query with context
    user_message = f"""Context from documents:

{context}

---

Question: {query}"""

    messages.append({"role": "user", "content": user_message})

    # --- Call LLM ---
    try:
        client = OpenAI(base_url=ai_base_url, api_key=ai_api_key)
        response = client.chat.completions.create(
            model=ai_model,
            messages=messages,
            stream=False,
        )
        response_text = response.choices[0].message.content
    except Exception as e:
        return {
            "output": f"LLM error: {e}",
            "sources": sources,
            "num_chunks_used": num_chunks_used,
        }

    return {
        "output": response_text,
        "sources": sources,
        "num_chunks_used": num_chunks_used,
    }
