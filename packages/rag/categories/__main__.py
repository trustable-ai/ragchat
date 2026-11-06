#--kind python:default
#--web true
#-p POSTGRES_URL "$POSTGRES_URL"
import categories
def main(args):
  return { "body": categories.categories(args) }
