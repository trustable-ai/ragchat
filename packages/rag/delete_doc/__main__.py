#--kind python:default
#--web true
#-p POSTGRES_URL "$POSTGRES_URL"
import delete_doc
def main(args):
  return { "body": delete_doc.delete_doc(args) }
