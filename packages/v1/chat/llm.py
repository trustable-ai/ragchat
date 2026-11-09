from openai import OpenAI
import os, socket, time, json, pathlib

# load the instruction file
# the file format is:
def loader(file):
    abs_path = os.path.abspath(__file__)
    current_dir = os.path.dirname(abs_path)
    path =  pathlib.Path(os.path.join(current_dir, file))
    text = path.read_text()
    lines = text.split("\n")
    res = []
    for line in lines:
        try:
            line = line.strip()
            if not line.startswith("{"):
                continue
            res.append(json.loads(line))
        except:
            print("error parsing line:", line)
    print(f"loaded #{len(res)} instructions from {file}")
    return res

class LLM:
    def __init__(self, args):
        # params
        self.base_url  = args.get("AI_BASE_URL", os.getenv("AI_BASE_URL", "missing AI_BASE_URL"))
        self.api_key = args.get("AI_API_KEY", os.getenv("AI_API_KEY", "missing AI_API_KEY"))
        self.model = args.get("AI_CHAT_MODEL", os.getenv("AI_CHAT_MODEL", "missing AI_CHAT_MODEL"))
        self.rate = float(args.get("STREAM_RATE", 0.01))
        # urls
        self.ai = OpenAI(base_url=self.base_url, api_key=self.api_key)

        self.instruct = loader("doc.jsonl")
        print(self.model)
        print(self.instruct)

        self.messages = self.instruct
        self.context = []
        if "messages" in args:
            self.context = args.get("messages", [])
            self.messages += self.context

    def welcome(self, args):
        text = f"Welcome to TruGPT\nHost:{self.base_url}\nModel:{self.model}\n"
        text += f"RAG has #{len(self.instruct)} instructions.\n"
        return self.text(args, text)

    def message(self, role, content):
        self.messages.append({"role": role, "content":content})

    def stream(self, args, lines):
        out = ""
        sock = None
        host = args.get("STREAM_HOST", "")
        port = int(args.get("STREAM_PORT") or "0")
        if host and port:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host,port))
        try:
            for line in lines:
                if sock is not None:
                    #print(line + ":" + line.encode().hex())
                    sock.sendall(json.dumps(line).encode("utf-8"))
                    time.sleep(self.rate)
                out += line
        except Exception as e:
            print(e)
            print("interrupted")
        if sock is not None:
            sock.close()
        return out

    def _ask(self, inp):
        self.messages.append({"role": "user", "content": inp})
        print(f"context: {len(self.context)}\ninstruct: {len(self.instruct)}\nnmessages: {len(self.messages)}")
        stream = self.ai.chat.completions.create(
            model=self.model,
            messages=self.messages,
            stream=True
        )
        for chunk in stream:
            # ogni chunk è un oggetto tipo Event
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                yield content

    def ask(self, args, inp):
        st = self._ask(inp)
        return self.stream(args, st)

    def _text(self, lines):
        for line in lines.splitlines():
            for word in line.split(" "):
                yield word+" "
            yield "\n"

    def text(self, args, lines):
        return self.stream(args, self._text(lines))

    def _rag(self, args):
        for msg in self.instruct:
            yield f"- *{msg['role'].capitalize()}*: {msg['content']}\n"

    def rag(self, args):
        return self.stream(args, self._rag(args))
