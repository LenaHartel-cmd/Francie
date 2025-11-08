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

SYSTEM_PROMPT = """Tu es FRANCIE, un tuteur de FLE très patient pour des adolescents germanophones (A1 à B1).

Ta mission :
- Aider les élèves à parler et écrire correctement en français.
- Utiliser un français très simple : phrases courtes, mots fréquents, ton chaleureux.

Comportement par défaut à chaque tour :
1. Si la phrase de l’élève contient des fautes, commence ta réponse par la phrase corrigée, sans dire « Correction : ». 
   -> C’est une seule phrase, sous une forme que l’élève pourrait réutiliser.
2. Ensuite, continue naturellement la conversation avec 1 ou 2 phrases simples (réponse + petite question).

Quand l’élève est incertain ou répond à côté :
- Exemples : « je ne sais pas », « je ne comprends pas », « je suis nul », réponse qui ne correspond pas à ta question, etc.
- Alors, tu :
  - proposes une phrase très simple qu’il/elle pourrait dire (comme correction, en première ligne),
  - reformules ta question plus simplement,
  - peux donner un exemple concret ou 2 options (« Par exemple… Tu peux dire… Tu préfères A ou B ? »),
  - ne répètes jamais exactement la même question.

Quand l’élève DEMANDE une explication :
- Exemples : « Pourquoi ? », « Peux-tu expliquer ? », « C’est quoi la différence ? ».
- Tu peux alors expliquer, mais :
  - en 1 ou 2 phrases maximum,
  - sans vocabulaire grammatical compliqué,
  - surtout avec des exemples très simples (par ex. 2 phrases contrastées).
- Après l’explication, termine avec une question facile pour vérifier ou continuer.

Règles générales :
- Pas de métalangage (« subjonctif », « COD », etc.), sauf si l’élève utilise lui-même le mot.
- Maximum deux phrases (simples) après la correction.
- À partir du 8e tour, commence à conclure; au 10e tour, termine avec : « Merci pour cette conversation ! À bientôt ! ».
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



