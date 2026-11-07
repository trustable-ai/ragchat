"""
Manage RAG document categories in Postgres.
Actions: list, add, delete, rename.

Uses the Trustant builder pattern: ctx.POSTGRESQL is a live psycopg
connection injected by the generated wrapper. Schema (rag_categories) is
owned by setup/database — no DDL here.
"""
# re-zip trigger
import psycopg


def _list_categories(conn):
    """Return sorted list of category names."""
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM rag_categories ORDER BY name")
        return [row[0] for row in cur.fetchall()]


def main(args, ctx=None):
    """
    CRUD operations for categories.

    Args:
        args: dict with:
            - action: list | add | delete | rename
            - name: category name (for add/delete/rename)
            - new_name: new name (for rename)
    """
    if not ctx or not hasattr(ctx, "POSTGRESQL") or ctx.POSTGRESQL is None:
        return {"ok": False, "error": "Database not configured"}

    action = args.get("action", "list")
    name = args.get("name", "").strip()
    new_name = args.get("new_name", "").strip()

    conn = ctx.POSTGRESQL
    try:
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
        conn.rollback()
        return {"ok": False, "error": str(e)}
