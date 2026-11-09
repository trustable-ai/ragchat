"""
RAG Chat: Postgres fulltext search + LLM response generation.

Uses ctx.POSTGRESQL. Schema (rag_documents) is owned by setup/database.
"""
# re-zip trigger
import re
import string
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


STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "in", "on", "at", "to", "for", "with", "and", "or", "but",
    "who", "what", "which", "where", "when", "why", "how",
    "my", "your", "his", "her", "its", "our", "their",
    "i", "you", "he", "she", "it", "we", "they",
    "this", "that", "these", "those",
    "do", "does", "did", "has", "have", "had",
    "can", "could", "should", "would", "will", "shall",
}

COLUMNS = "filename, categoria, doc_id, chunk_index, content, rank"


def _normalize(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[" + re.escape(string.punctuation) + r"]", " ", text)
    return " ".join(text.split())


def _keywords(query):
    tokens = _normalize(query).split()
    if not tokens:
        return [], []
    stripped = [t for t in tokens if t not in STOPWORDS]
    return tokens, stripped or tokens


def _tier_tsvector(cur, words, categoria, top_k):
    """Tier 1: fulltext with plainto_tsquery, 'simple' config."""
    if not words:
        return []
    phrase = " ".join(words)
    sql = f"""
        SELECT {COLUMNS} FROM (
            SELECT filename, categoria, doc_id, chunk_index, content,
                   ts_rank_cd(content_tsv, plainto_tsquery('simple', %s)) AS rank
            FROM rag_documents
            WHERE content_tsv @@ plainto_tsquery('simple', %s)
              AND (categoria = %s OR %s = '')
        ) t
        WHERE rank > 0
        ORDER BY rank DESC
        LIMIT %s
    """
    cur.execute(sql, (phrase, phrase, categoria, categoria, top_k))
    return cur.fetchall()


def _tier_trigram(cur, stripped, categoria, top_k, threshold=0.2):
    """Tier 2: pg_trgm word_similarity for typos/partial matches."""
    if not stripped:
        return []
    phrase = " ".join(stripped)
    sql = f"""
        SELECT {COLUMNS} FROM (
            SELECT filename, categoria, doc_id, chunk_index, content,
                   word_similarity(%s, content) AS rank
            FROM rag_documents
            WHERE word_similarity(%s, content) >= %s
              AND (categoria = %s OR %s = '')
        ) t
        ORDER BY rank DESC
        LIMIT %s
    """
    cur.execute(sql, (phrase, phrase, threshold, categoria, categoria, top_k))
    return cur.fetchall()


def _tier_ilike(cur, stripped, categoria, top_k):
    if not stripped:
        return []
    conditions = " OR ".join(["content ILIKE %s" for _ in stripped])
    params = [f"%{w}%" for w in stripped]
    params += [categoria, categoria, top_k]
    sql = f"""
        SELECT {COLUMNS} FROM (
            SELECT filename, categoria, doc_id, chunk_index, content, 0.3 AS rank
            FROM rag_documents
            WHERE ({conditions})
              AND (categoria = %s OR %s = '')
        ) t
        LIMIT %s
    """
    cur.execute(sql, params)
    return cur.fetchall()


def _expand_adjacent(conn, hits, max_total):
    """Fetch chunk_index ±1 around each hit, preserving relevance order.

    Walks primary hits in blended-score order and appends each one's unseen
    neighbors right after it, so the most relevant chunk stays first while its
    context follows — instead of flattening by (doc_id, chunk_index), which
    would destroy relevance ordering.
    """
    if not hits or max_total <= len(hits):
        return hits[:max_total] if hits else hits
    ranges = {}
    for row in hits:
        doc_id, chunk_index = row[2], row[3]
        ranges.setdefault(doc_id, set()).update(
            [chunk_index - 1, chunk_index, chunk_index + 1]
        )
    adjacent_by_doc = {}
    sql = """
        SELECT filename, categoria, doc_id, chunk_index, content, 0.0 AS rank
        FROM rag_documents
        WHERE doc_id = %s AND chunk_index = ANY(%s)
    """
    with conn.cursor() as cur:
        for doc_id, idxs in ranges.items():
            cur.execute(sql, (doc_id, sorted(idxs)))
            for row in cur.fetchall():
                adjacent_by_doc.setdefault(doc_id, {})[row[3]] = row
    seen = set()
    merged = []
    for row in hits:
        doc_id, chunk_index = row[2], row[3]
        neighbors = adjacent_by_doc.get(doc_id, {})
        for idx in sorted([chunk_index - 1, chunk_index, chunk_index + 1]):
            key = (doc_id, idx)
            if key in seen:
                continue
            seen.add(key)
            if idx == chunk_index:
                merged.append(row)
            else:
                neighbor = neighbors.get(idx)
                if neighbor is not None:
                    merged.append(neighbor)
            if len(merged) >= max_total:
                break
        if len(merged) >= max_total:
            break
    return merged[:max_total]


def rag_search(conn, query, categoria="", top_k=15, expand=True):
    """Three-tier search (tsvector + trigram + ILIKE) with chunk expansion."""
    tokens, stripped = _keywords(query)
    if not tokens:
        return []
    results = {}
    max_rank = {"ts": 1.0, "tri": 1.0}
    with conn.cursor() as cur:
        rows = _tier_tsvector(cur, stripped, categoria, top_k * 2)
        if rows:
            max_rank["ts"] = max(float(r[5]) for r in rows) or 1.0
        for r in rows:
            key = (r[2], r[3])
            score = (float(r[5]) / max_rank["ts"]) if max_rank["ts"] else 0.0
            results[key] = {"row": r, "score": score * 0.6}
        rows = _tier_trigram(cur, stripped, categoria, top_k * 2)
        if rows:
            max_rank["tri"] = max(float(r[5]) for r in rows) or 1.0
        for r in rows:
            key = (r[2], r[3])
            score = (float(r[5]) / max_rank["tri"]) if max_rank["tri"] else 0.0
            if key in results:
                results[key]["score"] += score * 0.3
            else:
                results[key] = {"row": r, "score": score * 0.3}
        rows = _tier_ilike(cur, stripped, categoria, top_k)
        for r in rows:
            key = (r[2], r[3])
            if key in results:
                results[key]["score"] += 0.1
            else:
                results[key] = {"row": r, "score": 0.1}
    if not results:
        return []
    ranked = sorted(results.values(), key=lambda v: v["score"], reverse=True)[:top_k]
    hits = [tuple(list(v["row"])[:5] + [v["score"]]) for v in ranked]
    if expand:
        hits = _expand_adjacent(conn, hits, max_total=top_k * 3)
    return hits


def fulltext_search(conn, query, categoria="", top_k=15):
    """Three-tier search with adjacent-chunk expansion (kept for compatibility)."""
    return rag_search(conn, query, categoria, top_k, expand=True)


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
