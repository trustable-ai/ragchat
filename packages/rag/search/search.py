"""
Three-tier RAG search over Postgres: tsvector + pg_trgm + ILIKE, with
adjacent-chunk expansion for richer context.

Schema (rag_documents + pg_trgm extension) is owned by setup/database.
Uses ctx.POSTGRESQL.
"""
# re-zip trigger
import re
import string

# Stopwords stripped ONLY from the trigram/ILIKE tiers (tsvector handles its
# own). Keep the list small and English-only for now; documents are English.
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

# Columns selected everywhere, in a stable order.
COLUMNS = "filename, categoria, doc_id, chunk_index, content, rank"


def _normalize(text):
    """Lowercase, strip punctuation, collapse whitespace."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[" + re.escape(string.punctuation) + r"]", " ", text)
    return " ".join(text.split())


def _keywords(query):
    """Return raw keyword tokens and a stopword-stripped subset."""
    tokens = _normalize(query).split()
    if not tokens:
        return [], []
    stripped = [t for t in tokens if t not in STOPWORDS]
    return tokens, stripped or tokens


def _tier_tsvector(cur, words, categoria, top_k):
    """Tier 1: fulltext with plainto_tsquery.

    Uses 'simple' config (no stemming) to stay correct for mixed-language
    documents. Stopwords are pre-stripped by _keywords so they don't inflate
    the rank on 'simple' (which does no stopword removal of its own).
    """
    if not words:
        return []
    phrase = " ".join(words)
    sql = """
        SELECT filename, categoria, doc_id, chunk_index, content,
               ts_rank_cd(content_tsv, plainto_tsquery('simple', %s)) AS rank
        FROM rag_documents
        WHERE content_tsv @@ plainto_tsquery('simple', %s)
          AND (categoria = %s OR %s = '')
        ORDER BY rank DESC
        LIMIT %s
    """
    cur.execute(sql, (phrase, phrase, categoria, categoria, top_k))
    return cur.fetchall()


def _tier_trigram(cur, stripped, categoria, top_k, threshold=0.2):
    """Tier 2: pg_trgm word_similarity for typos/partial matches.

    word_similarity(query, content) measures how well the query matches a
    *substring* of the content, unlike similarity() which compares whole
    strings. This is the right operator for typo-tolerant search inside long
    chunks. Uses the function directly (not the <% operator) so the threshold
    is honored.
    """
    if not stripped:
        return []
    phrase = " ".join(stripped)
    sql = """
        SELECT filename, categoria, doc_id, chunk_index, content,
               word_similarity(%s, content) AS rank
        FROM rag_documents
        WHERE word_similarity(%s, content) >= %s
          AND (categoria = %s OR %s = '')
        ORDER BY rank DESC
        LIMIT %s
    """
    cur.execute(sql, (phrase, phrase, threshold, categoria, categoria, top_k))
    return cur.fetchall()


def _tier_ilike(cur, stripped, categoria, top_k):
    """Tier 3: ILIKE OR per keyword (fixed: old code required words in order)."""
    if not stripped:
        return []
    conditions = " OR ".join(["content ILIKE %s" for _ in stripped])
    params = [f"%{w}%" for w in stripped]
    params += [categoria, categoria, top_k]
    sql = f"""
        SELECT filename, categoria, doc_id, chunk_index, content, 0.3 AS rank
        FROM rag_documents
        WHERE ({conditions})
          AND (categoria = %s OR %s = '')
        LIMIT %s
    """
    cur.execute(sql, params)
    return cur.fetchall()


def _expand_adjacent(conn, hits, max_total):
    """Fetch chunk_index ±1 around each hit for richer context.

    Preserves the relevance order of the primary hits: for each primary hit
    (already ranked by blended score), append its adjacent chunks right after
    it. This keeps the most relevant chunk first while grouping its context,
    instead of flattening the whole set by (doc_id, chunk_index), which would
    destroy relevance ordering.
    """
    if not hits:
        return hits
    if max_total <= len(hits):
        return hits[:max_total]

    # Collect adjacency ranges per doc_id.
    ranges = {}
    for row in hits:
        doc_id, chunk_index = row[2], row[3]
        ranges.setdefault(doc_id, set()).update(
            [chunk_index - 1, chunk_index, chunk_index + 1]
        )

    # Fetch all candidate adjacent rows per doc in one query each.
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

    # Walk primary hits in relevance order; append each one's unseen neighbors.
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


def search(conn, query, categoria="", top_k=15, expand=True, debug=False):
    """Three-tier search with score blending and optional chunk expansion."""
    tokens, stripped = _keywords(query)
    if not tokens:
        return []

    results = {}
    max_rank = {"ts": 1.0, "tri": 1.0, "ilike": 0.3}
    tier_counts = {"ts": 0, "tri": 0, "ilike": 0}
    tier_rows = {"ts": [], "tri": [], "ilike": []}

    with conn.cursor() as cur:
        # Tier 1: fulltext. Pass stopword-stripped tokens since 'simple'
        # config does not remove stopwords itself.
        rows = _tier_tsvector(cur, stripped, categoria, top_k * 2)
        tier_counts["ts"] = len(rows)
        tier_rows["ts"] = rows
        if rows:
            max_rank["ts"] = max(float(r[5]) for r in rows) or 1.0
        for r in rows:
            key = (r[2], r[3])
            score = (float(r[5]) / max_rank["ts"]) if max_rank["ts"] else 0.0
            results[key] = {"row": r, "score": score * 0.6}

        # Tier 2: trigram (0..1 already). Only fills gaps not already found.
        rows = _tier_trigram(cur, stripped, categoria, top_k * 2)
        tier_counts["tri"] = len(rows)
        tier_rows["tri"] = rows
        if rows:
            max_rank["tri"] = max(float(r[5]) for r in rows) or 1.0
        for r in rows:
            key = (r[2], r[3])
            score = (float(r[5]) / max_rank["tri"]) if max_rank["tri"] else 0.0
            if key in results:
                results[key]["score"] += score * 0.3
            else:
                results[key] = {"row": r, "score": score * 0.3}

        # Tier 3: ILIKE OR per keyword. Fills the last gaps.
        rows = _tier_ilike(cur, stripped, categoria, top_k)
        tier_counts["ilike"] = len(rows)
        tier_rows["ilike"] = rows
        for r in rows:
            key = (r[2], r[3])
            if key in results:
                results[key]["score"] += 0.1
            else:
                results[key] = {"row": r, "score": 0.1}

    if not results:
        return []

    # Rank the primary hits, keep the top_k best.
    ranked = sorted(
        results.values(), key=lambda v: v["score"], reverse=True
    )[:top_k]
    # Replace the raw tier rank with the blended score so callers see the
    # combined ranking, not a single tier's raw value.
    hits = [tuple(list(v["row"])[:5] + [v["score"]]) for v in ranked]

    if debug:
        def _tier_rank(tier_rows_list, doc_id, chunk_index):
            for r in tier_rows_list:
                if r[2] == doc_id and r[3] == chunk_index:
                    return round(float(r[5]), 4)
            return None
        return hits, {
            "tier_counts": tier_counts,
            "max_rank": {k: round(v, 4) for k, v in max_rank.items()},
            "top5": [
                {
                    "filename": v["row"][0],
                    "doc_id": v["row"][2],
                    "chunk_index": v["row"][3],
                    "blend": round(v["score"], 4),
                    "raw_ts": _tier_rank(tier_rows["ts"], v["row"][2], v["row"][3]),
                    "raw_tri": _tier_rank(tier_rows["tri"], v["row"][2], v["row"][3]),
                    "raw_ilike": _tier_rank(tier_rows["ilike"], v["row"][2], v["row"][3]),
                }
                for v in ranked[:5]
            ],
        }

    if expand:
        # Expand to adjacent chunks but cap the total context size.
        hits = _expand_adjacent(conn, hits, max_total=top_k * 3)

    return hits


def main(args, ctx=None):
    """
    Three-tier RAG search with adjacent-chunk expansion.

    Args:
        args: dict with:
            - input: query text (required)
            - categoria: filter by category (optional, empty = all)
            - top_k: max primary results (default 15); expansion may add
              adjacent chunks up to ~3x for context
            - expand: enable adjacent-chunk expansion (default true)
            - debug: return per-tier raw ranks for the top hits (default false)
    """
    if not ctx or not hasattr(ctx, "POSTGRESQL") or ctx.POSTGRESQL is None:
        return {"ok": False, "error": "Database not configured"}

    query = args.get("input", "").strip()
    categoria = args.get("categoria", "").strip()
    top_k = int(args.get("top_k", 15))
    expand = args.get("expand", True)
    if isinstance(expand, str):
        expand = expand.lower() not in ("0", "false", "no")
    debug = args.get("debug", False)
    if isinstance(debug, str):
        debug = debug.lower() not in ("0", "false", "no")

    if not query:
        return {"ok": False, "error": "input (query text) is required"}

    conn = ctx.POSTGRESQL
    try:
        if debug:
            hits, info = search(conn, query, categoria, top_k, expand, debug=True)
            results = [{
                "text": row[4],
                "filename": row[0],
                "categoria": row[1],
                "doc_id": row[2],
                "chunk_index": row[3],
                "score": round(float(row[5]), 4),
            } for row in hits]
            return {
                "results": results,
                "num_results": len(results),
                "debug": info,
            }
        hits = search(conn, query, categoria, top_k, expand)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    results = []
    for row in hits:
        results.append({
            "text": row[4],
            "filename": row[0],
            "categoria": row[1],
            "doc_id": row[2],
            "chunk_index": row[3],
            "score": round(float(row[5]), 4),
        })

    return {
        "results": results,
        "num_results": len(results),
    }
