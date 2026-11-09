#--kind python:default
#--web true
# Note: this timeout is 5 minutes - 10 minutes is max allowed
#--timeout 300000
import types, os, questions

builder = []
## build-context ##
#--param AI_CHAT_MODEL "$AI_CHAT_MODEL"
def init_ai_chat_model(args, ctx):
  value = args.get("AI_CHAT_MODEL") or os.getenv("AI_CHAT_MODEL")
  if not value:
    raise RuntimeError("Required secret AI_CHAT_MODEL is not configured")
  setattr(ctx, "AI_CHAT_MODEL", value)
builder.append(init_ai_chat_model)
#--param AI_API_KEY "$AI_API_KEY"
def init_ai_api_key(args, ctx):
  value = args.get("AI_API_KEY") or os.getenv("AI_API_KEY")
  if not value:
    raise RuntimeError("Required secret AI_API_KEY is not configured")
  setattr(ctx, "AI_API_KEY", value)
builder.append(init_ai_api_key)
#--param AI_BASE_URL "$AI_BASE_URL"
def init_ai_base_url(args, ctx):
  value = args.get("AI_BASE_URL") or os.getenv("AI_BASE_URL")
  if not value:
    raise RuntimeError("Required secret AI_BASE_URL is not configured")
  setattr(ctx, "AI_BASE_URL", value)
builder.append(init_ai_base_url)
#--param POSTGRES_URL "$POSTGRES_URL"
import psycopg
def init_postgresql(args, ctx):
  dburl = args.get("POSTGRES_URL", os.getenv("POSTGRES_URL"))
  ctx.POSTGRESQL = psycopg.connect(dburl)
builder.append(init_postgresql)

def main(args):
  try:
    ctx = types.SimpleNamespace()
    for fn in builder: fn(args, ctx)
    return { "body": questions.main(args, ctx=ctx) }
  except Exception as e:
    import traceback
    traceback.print_exc()
    return {
      "body": {"error": str(e) },
      "statusCode": 500
    }
