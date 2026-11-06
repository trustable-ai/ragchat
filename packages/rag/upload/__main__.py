#--kind python:default
#--web true
# Note: this timeout is 5 minutes - 10 minutes is max allowed
#--timeout 300000
import types, os, upload

builder = []
## build-context ##
#--param S3_HOST "$S3_HOST"
#--param S3_PORT "$S3_PORT"
#--param S3_ACCESS_KEY "$S3_ACCESS_KEY"
#--param S3_SECRET_KEY "$S3_SECRET_KEY"
#--param S3_BUCKET_DATA "$S3_BUCKET_DATA"
#--param S3_BUCKET_STATIC "$S3_BUCKET_STATIC"
#--param S3_PUBLIC "$OPSDEV_S3"
import boto3
from botocore.client import Config
def init_s3(args, ctx):
  host = args.get("S3_HOST", os.getenv("S3_HOST"))
  port = args.get("S3_PORT", os.getenv("S3_PORT"))
  url = f"http://{host}:{port}"
  key = args.get("S3_ACCESS_KEY", os.getenv("S3_ACCESS_KEY"))
  sec = args.get("S3_SECRET_KEY", os.getenv("S3_SECRET_KEY"))
  cfg = Config(signature_version='s3v4')
  ctx.S3_CLIENT = boto3.client('s3', region_name='us-east-1', endpoint_url=url, aws_access_key_id=key, aws_secret_access_key=sec, config=cfg)
  ctx.S3_DATA = args.get("S3_BUCKET_DATA", os.getenv("S3_BUCKET_DATA"))
  ctx.S3_WEB = args.get("S3_BUCKET_STATIC", os.getenv("S3_BUCKET_STATIC"))
  ctx.S3_PUBLIC = args.get("S3_PUBLIC", os.getenv("OPSDEV_S3"))
builder.append(init_s3)

def main(args):
  try:
    ctx = types.SimpleNamespace()
    for fn in builder: fn(args, ctx)
    return { "body": upload.main(args, ctx=ctx) }
  except Exception as e:
    import traceback
    traceback.print_exc()
    return {
      "body": {"error": str(e) },
      "statusCode": 500
    }
