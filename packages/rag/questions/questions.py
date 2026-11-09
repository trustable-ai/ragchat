"""
Suggested questions per category, with lazy LLM generation and DB cache.

For each document in the requested category that has no cached questions yet,
generates 3 questions via the LLM (using the first chunk as a sample), saves
them in rag_suggested_questions, then returns the top-N for the category.

If the LLM call fails, falls back to a deterministic question derived from
the filename so the endpoint always returns something useful.

Uses ctx.POSTGRESQL, ctx.AI_BASE_URL, ctx.AI_API_KEY, ctx.AI_CHAT_MODEL.
Schema (rag_suggested_questions) is owned by setup/database.
"""
# re-zip trigger
import time

from openai import OpenAI

QUESTIONS_PER_DOC = 3
MAX_RETURN = 3
LLM_DELAY = 1  # seconds between LLM calls to avoid rate limits

GEN_PROMPT = """You are a document analyst. Given a sample of text from a document, generate {n} concise, natural questions that a user could ask about this document and that the document can answer.

Rules:
- Each question must be answerable from the document content
- Questions should be diverse (cover different aspects: amounts, dates, parties, terms, etc.)
- Keep each question under 12 words
- IMPORTANT: when the document name identifies a specific entity (company, supplier, type), include it in the question so it is unambiguous among similar documents in the same category. For example, prefer "What is the invoice number for CloudBridge?" over "What is the invoice number?"
- Return ONLY the questions, one per line, no numbering, no quotes, no prefixes

Document filename: {filename}
Category: {categoria}
Sample text:
{sample}"""


def _fallback_questions(filename, n=QUESTIONS_PER_DOC):
    """Deterministic fallback if the LLM fails."""
    base = filename or "this document"
    base = base.rsplit("/", 1)[-1]
    base = base.rsplit(".", 1)[0]
    return [
        f"What are the key details in {base}?",
        f"Summarize {base}",
        f"What is the most important information in {base}?",
    ][:n]


def _generate_questions(ai_base_url, ai_api_key, ai_model, filename, categoria, sample, retries=2):
    """Call the LLM to generate questions from a document sample.

    Returns (questions, debug_info). Retries once on empty response.
    """
    client = OpenAI(base_url=ai_base_url, api_key=ai_api_key)
    prompt = GEN_PROMPT.format(
        n=QUESTIONS_PER_DOC,
        filename=filename,
        categoria=categoria,
        sample=sample[:800],
    )
    text = ""
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=ai_model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                max_tokens=400,
                temperature=0.7,
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                break
            time.sleep(1)
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                raise
    questions = [
        q.strip().lstrip("0123456789.-) ").strip()
        for q in text.splitlines()
        if q.strip()
    ]
    questions = [q for q in questions if len(q) > 5 and len(q) < 120]
    result = questions[:QUESTIONS_PER_DOC]
    debug = {"raw": text[:200], "parsed": len(result)}
    if not result:
        result = _fallback_questions(filename)
        debug["fallback"] = True
    return result, debug


def _get_cached_questions(conn, categoria):
    sql = """
        SELECT filename, question
        FROM rag_suggested_questions
        WHERE categoria = %s OR %s = ''
        ORDER BY created_at
    """
    with conn.cursor() as cur:
        cur.execute(sql, (categoria, categoria))
        return cur.fetchall()


def _get_docs_needing_questions(conn, categoria):
    sql = """
        SELECT DISTINCT d.filename, d.categoria, d.doc_id, d.content
        FROM rag_documents d
        LEFT JOIN rag_suggested_questions q
            ON q.doc_id = d.doc_id
        WHERE q.id IS NULL
          AND (d.categoria = %s OR %s = '')
          AND d.chunk_index = 0
    """
    with conn.cursor() as cur:
        cur.execute(sql, (categoria, categoria))
        return cur.fetchall()


def _save_questions(conn, filename, categoria, doc_id, questions):
    sql = """
        INSERT INTO rag_suggested_questions (filename, categoria, doc_id, question)
        VALUES (%s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        for q in questions:
            cur.execute(sql, (filename, categoria, doc_id, q))
    conn.commit()


def main(args, ctx=None):
    """
    Get suggested questions for a category (lazy generation + cache).

    Args:
        args: dict with:
            - categoria: category to filter by (optional, empty = all)
            - max: max questions to return (default 5)
            - regenerate: force regeneration (default false)
    """
    if not ctx or not hasattr(ctx, "POSTGRESQL") or ctx.POSTGRESQL is None:
        return {"ok": False, "error": "Database not configured"}

    conn = ctx.POSTGRESQL
    categoria = args.get("categoria", "").strip()
    max_return = int(args.get("max", MAX_RETURN))
    regenerate = args.get("regenerate", False)
    if isinstance(regenerate, str):
        regenerate = regenerate.lower() not in ("0", "false", "no")

    ai_base_url = getattr(ctx, "AI_BASE_URL", None) or args.get("AI_BASE_URL")
    ai_api_key = getattr(ctx, "AI_API_KEY", None) or args.get("AI_API_KEY")
    ai_model = getattr(ctx, "AI_CHAT_MODEL", None) or args.get("AI_CHAT_MODEL")

    try:
        if regenerate:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM rag_suggested_questions WHERE categoria = %s OR %s = ''",
                    (categoria, categoria),
                )
            conn.commit()

        # Generate + cache questions for documents that don't have them yet.
        needs = _get_docs_needing_questions(conn, categoria)
        if needs:
            for i, (filename, cat, doc_id, sample) in enumerate(needs):
                # Rate-limit between LLM calls to avoid 429 errors.
                if i > 0 and ai_base_url and ai_api_key and ai_model:
                    time.sleep(LLM_DELAY)
                try:
                    if ai_base_url and ai_api_key and ai_model:
                        questions, _ = _generate_questions(
                            ai_base_url, ai_api_key, ai_model,
                            filename, cat, sample,
                        )
                    else:
                        questions = _fallback_questions(filename)
                except Exception:
                    questions = _fallback_questions(filename)
                _save_questions(conn, filename, cat, doc_id, questions)

        # Return cached questions for the category, capped.
        cached = _get_cached_questions(conn, categoria)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    questions = [{"filename": row[0], "question": row[1]} for row in cached[:max_return]]

    return {
        "questions": questions,
        "num_questions": len(questions),
    }
