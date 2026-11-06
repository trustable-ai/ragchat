#--kind python:default
#--web true
import clean
def main(args):
  return { "body": clean.clean(args) }
