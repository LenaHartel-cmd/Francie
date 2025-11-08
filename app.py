import os, time, sqlite3, requests
from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
APP_TITLE = "Francie – Französisch-Chat (A1–B1)"
MAX_TURNS = int(os.getenv("MAX_TURNS", "10"))
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mistral")

SYSTEM_PROMPT = """Tu es un tuteur bienveillant de FLE (A1–B1).
Objectif : mener une conversation jusqu’à 10 tours maximum (élève ↔ toi).
Règles :
1) Utilise un français simple adapté au niveau de l’élève (A1–B1).
2) À chaque tour :
– réponds brièvement,
– reformule doucement les erreurs de l’élève (recast),
– pose une nouvelle question courte liée au sujet.
3) À partir du 8e tour, oriente vers une conclusion. Au 10e tour, termine : “Merci pour cette conversation ! À bientôt !”.
4) Ne demande jamais de données personnelles.
5) Reste motivant et encourageant.
Format :
– Réponse (1–3 phrases)
– Question (1 phrase)
"""

DB_PATH = "chat.db"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute("""CREATE TABLE IF NOT EXISTS messages(
  session_id TEXT, turn INTEGER, role TEXT, content TEXT, ts REAL
)""")
conn.commit()

app = FastAPI(title=APP_TITLE)

class TurnIn(BaseModel):
    session_id: str
    user_text: str

def get_turn(session_id):
    cur = conn.execute("SELECT MAX(turn) FROM messages WHERE session_id=?", (session_id,))
    row = cur.fetchone()
    return row[0] if row and row[0] else 0

def save_msg(session_id, turn, role, content):
    conn.execute("INSERT INTO messages VALUES (?,?,?,?,?)",
                 (session_id, turn, role, content, time.time()))
    conn.commit()

def get_history(session_id):
    cur = conn.execute("SELECT role,content FROM messages WHERE session_id=? ORDER BY turn",(session_id,))
    return [{"role": r, "content": c} for r,c in cur.fetchall()]

def lvl_hint(text):
    n = len(text.split())
    return "A1" if n<8 else "A2" if n<18 else "B1"

def call_llm(history, level):
    assert LLM_API_KEY, "LLM_API_KEY fehlt (bitte als Environment Variable setzen)."
    if LLM_PROVIDER.lower() == "mistral":
      headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
      payload = {"model":"mistral-small-latest",
                 "messages":[{"role":"system","content":SYSTEM_PROMPT+f"\nNiveau: {level}"}]+history,
                 "temperature":0.6}
      r = requests.post("https://api.mistral.ai/v1/chat/completions",
                        headers=headers, json=payload, timeout=30)
      r.raise_for_status()
      return r.json()["choices"][0]["message"]["content"]
    else:
      raise ValueError("Unbekannter LLM_PROVIDER. Nutze vorerst 'mistral'.")

@app.get("/", response_class=HTMLResponse)
def home():
    return open("index.html","r",encoding="utf-8").read()

@app.post("/turn")
def turn(inp: TurnIn):
    t = get_turn(inp.session_id)
    if t >= MAX_TURNS:
        return JSONResponse({"bot":"Merci pour cette conversation ! À bientôt !","turn":t,"done":True})
    save_msg(inp.session_id, t+1, "user", inp.user_text)
    history = get_history(inp.session_id)
    bot = call_llm(history, lvl_hint(inp.user_text))
    save_msg(inp.session_id, t+1, "assistant", bot)
    return JSONResponse({"bot":bot,"turn":t+1,"done":(t+1)>=MAX_TURNS})

