#--kind python:default
#--web true
#--timeout 300000
#-p POSTGRES_URL "$POSTGRES_URL"
#-p AI_BASE_URL "$AI_BASE_URL"
#-p AI_API_KEY "$AI_API_KEY"
#-p AI_CHAT_MODEL "$AI_CHAT_MODEL"
import ragchat
def main(args):
  return { "body": ragchat.ragchat(args) }
