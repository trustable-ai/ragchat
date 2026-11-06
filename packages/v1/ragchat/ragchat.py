"""
RAG Chat: Postgres fulltext search + LLM response generation.
"""
import psycopg
from openai import OpenAI


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


def ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def fulltext_search(conn, query, categoria="", top_k=15):
    """Run fulltext search and return ranked results."""
    sql = """
        SELECT filename, categoria, doc_id, chunk_index, content,
               ts_rank(content_tsv, plainto_tsquery('english', %s)) AS rank
        FROM rag_documents
        WHERE content_tsv @@ plainto_tsquery('english', %s)
        AND (categoria = %s OR %s = '')
        ORDER BY rank DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (query, query, categoria, categoria, top_k))
        return cur.fetchall()


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


def ragchat(args):
    """
    RAG Chat: search documents then generate LLM response.

    Args:
        args: dict with:
            - input: user question (required)
            - categoria: filter by category (optional)
            - top_k: max chunks to retrieve (default 15)
            - history: conversation history [{role, content}, ...] (optional)
            - POSTGRES_URL: connection string
            - AI_BASE_URL: LLM API base URL
            - AI_API_KEY: LLM API key
            - AI_CHAT_MODEL: LLM model name
    """
    query = args.get("input", "").strip()
    categoria = args.get("categoria", "").strip()
    top_k = int(args.get("top_k", 15))
    history = args.get("messages", args.get("history", []))

    print(f"DEBUG ragchat: query={query!r} categoria={categoria!r} keys={list(args.keys())}")

    if not query:
        return {"ok": False, "error": "input (question) is required"}

    postgres_url = args.get("POSTGRES_URL")
    if not postgres_url:
        return {"ok": False, "error": "POSTGRES_URL not configured"}

    ai_base_url = args.get("AI_BASE_URL")
    ai_api_key = args.get("AI_API_KEY")
    ai_model = args.get("AI_CHAT_MODEL")

    if not ai_base_url or not ai_api_key or not ai_model:
        return {"ok": False, "error": "AI_BASE_URL, AI_API_KEY, and AI_CHAT_MODEL are required"}

    # --- Search ---
    try:
        with psycopg.connect(postgres_url) as conn:
            ensure_table(conn)
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
