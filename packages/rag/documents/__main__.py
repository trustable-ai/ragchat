#--kind python:default
#--web true
#-p POSTGRES_URL "$POSTGRES_URL"
import documents
def main(args):
  return { "body": documents.documents(args) }
