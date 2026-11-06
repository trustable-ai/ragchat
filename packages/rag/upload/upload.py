"""
Chunked S3 upload action.

The OpenWhisk/nginx gateway limits request bodies to ~1 MB, so a full PDF
cannot be sent in a single request. The browser slices the file into small
chunks (each well under 1 MB) and uploads every chunk as its own standalone
S3 object via this action. S3 multipart upload is NOT used because SeaweedFS
enforces a 5 MB minimum per part, which is incompatible with the 1 MB request
limit.

The browser chooses one S3 key per chunk (e.g. `uploads/<ts>_<name>.part1`,
`.part2`, ...) and then passes the full list of keys to `rag/ingest`, which
reads and concatenates them before extracting text with Tika.

All S3 access goes through the generated ctx.S3_CLIENT / ctx.S3_DATA wiring.
"""
import base64


def _client(ctx):
    if not ctx or not hasattr(ctx, "S3_CLIENT") or ctx.S3_CLIENT is None:
        raise RuntimeError("S3 non configurato")
    return ctx.S3_CLIENT, getattr(ctx, "S3_DATA", None)


def main(args, ctx=None):
    client, bucket = _client(ctx)
    key = args.get("filename") or args.get("key")
    part_b64 = args.get("part")

    if not key:
        return {"error": "filename is required"}
    if not part_b64:
        return {"error": "part (base64) is required"}

    try:
        body = base64.b64decode(part_b64)
        if not body:
            return {"error": "decoded part is empty"}
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/octet-stream",
        )
        return {"ok": True, "key": key, "size": len(body)}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}