#--kind python:default
#--web true
#--timeout 120000
#-p POSTGRES_URL "$POSTGRES_URL"
import search
def main(args):
  return { "body": search.search(args) }
