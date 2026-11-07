"""
Chunk text using empty lines as separators.
Merges small chunks (under MIN_CHUNK_CHARS) with the next one.
Optionally stores chunks in S3 as JSONL.

Uses ctx.S3_CLIENT / ctx.S3_DATA (Trustant builder pattern).
"""
import json
from datetime import datetime

MIN_CHUNK_CHARS = 400


def _split_chunks(input_text):
    """Split text into chunks using empty lines as separators."""
    if not input_text:
        return []

    # Split by empty lines (one or more consecutive newlines)
    raw_chunks = []
    current_chunk = []

    for line in input_text.split('\n'):
        if line.strip():  # Non-empty line
            current_chunk.append(line)
        else:  # Empty line - end current chunk
            if current_chunk:
                raw_chunks.append('\n'.join(current_chunk))
                current_chunk = []

    # Add the last chunk if there's any content
    if current_chunk:
        raw_chunks.append('\n'.join(current_chunk))

    # Merge small chunks (under MIN_CHUNK_CHARS) with the next one
    chunks = []
    buffer = ""

    for rc in raw_chunks:
        if buffer:
            buffer = buffer + "\n\n" + rc
        else:
            buffer = rc

        if len(buffer) >= MIN_CHUNK_CHARS:
            chunks.append(buffer)
            buffer = ""

    # Trailing buffer: append to last chunk if exists, otherwise add as-is
    if buffer:
        if chunks:
            chunks[-1] = chunks[-1] + "\n\n" + buffer
        else:
            chunks.append(buffer)

    return chunks


def _store_chunks_in_s3(chunks, ctx):
    """Store chunks in S3 as JSONL with format {"assistant": <chunk>}."""
    if not ctx or not hasattr(ctx, "S3_CLIENT") or ctx.S3_CLIENT is None:
        return None
    bucket = getattr(ctx, "S3_DATA", None)
    if not bucket:
        return None

    try:
        client = ctx.S3_CLIENT
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        s3_key = f"chunks/chunks_{timestamp}.jsonl"

        # Create JSONL content with format {"assistant": <chunk>}
        jsonl_lines = [json.dumps({"assistant": c}) for c in chunks]
        jsonl_content = '\n'.join(jsonl_lines)

        client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=jsonl_content.encode('utf-8'),
            ContentType='application/jsonl'
        )
        return s3_key
    except Exception as e:
        print(f"Warning: Failed to store chunks in S3: {e}")
        return None


def main(args, ctx=None):
    """
    Split text into chunks using empty lines as separators.

    Args:
        args: dict with 'input' (text to chunk)

    Returns:
        dict with 'output' (list of chunks) and 'num_chunks'
    """
    input_text = args.get("input", "")
    chunks = _split_chunks(input_text)

    result = {
        "output": chunks,
        "num_chunks": len(chunks)
    }

    # Store in S3 if ctx.S3_CLIENT is available
    if chunks and ctx and hasattr(ctx, "S3_CLIENT") and ctx.S3_CLIENT is not None:
        s3_key = _store_chunks_in_s3(chunks, ctx)
        if s3_key:
            result["s3_key"] = s3_key

    return result
