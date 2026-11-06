#--kind python:default
#--web true
#--timeout 300000
#-p POSTGRES_URL "$POSTGRES_URL"
import store
def main(args):
  return { "body": store.store(args) }
