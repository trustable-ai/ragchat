"""
Manage RAG document categories in Postgres.
Actions: list, add, delete, rename.
"""
import psycopg


DDL = """
CREATE TABLE IF NOT EXISTS rag_categories (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
"""


def ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def _list_categories(conn):
    """Return sorted list of category names."""
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM rag_categories ORDER BY name")
        return [row[0] for row in cur.fetchall()]


def categories(args):
    """
    CRUD operations for categories.

    Args:
        args: dict with:
            - action: list | add | delete | rename
            - name: category name (for add/delete/rename)
            - new_name: new name (for rename)
            - POSTGRES_URL: connection string
    """
    action = args.get("action", "list")
    name = args.get("name", "").strip()
    new_name = args.get("new_name", "").strip()

    postgres_url = args.get("POSTGRES_URL")
    if not postgres_url:
        return {"ok": False, "error": "POSTGRES_URL not configured"}

    try:
        with psycopg.connect(postgres_url) as conn:
            ensure_table(conn)

            if action == "list":
                return {"categories": _list_categories(conn)}

            elif action == "add":
                if not name:
                    return {"ok": False, "error": "name is required"}
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO rag_categories (name) VALUES (%s)",
                            (name,)
                        )
                    conn.commit()
                except psycopg.errors.UniqueViolation:
                    conn.rollback()
                    return {"ok": False, "error": f"Category '{name}' already exists"}
                return {"ok": True, "categories": _list_categories(conn)}

            elif action == "delete":
                if not name:
                    return {"ok": False, "error": "name is required"}
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM rag_categories WHERE name = %s",
                        (name,)
                    )
                    if cur.rowcount == 0:
                        conn.rollback()
                        return {"ok": False, "error": f"Category '{name}' not found"}
                conn.commit()
                return {"ok": True, "categories": _list_categories(conn)}

            elif action == "rename":
                if not name or not new_name:
                    return {"ok": False, "error": "name and new_name are required"}
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE rag_categories SET name = %s WHERE name = %s",
                            (new_name, name)
                        )
                        if cur.rowcount == 0:
                            conn.rollback()
                            return {"ok": False, "error": f"Category '{name}' not found"}
                    conn.commit()
                except psycopg.errors.UniqueViolation:
                    conn.rollback()
                    return {"ok": False, "error": f"Category '{new_name}' already exists"}
                return {"ok": True, "categories": _list_categories(conn)}

            else:
                return {"ok": False, "error": f"Unknown action: {action}"}

    except Exception as e:
        return {"ok": False, "error": str(e)}
