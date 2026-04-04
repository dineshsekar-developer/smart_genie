from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import sqlite3
from groq import Groq
import os

app = Flask(__name__)
CORS(app)

# ---------- API KEY ----------
api_key = os.environ.get("GROQ_API_KEY")
if not api_key:
    raise ValueError("❌ GROQ_API_KEY NOT FOUND")

client = Groq(api_key=api_key)

# ---------- DB ----------

def get_db():
    return sqlite3.connect("chat_history.db", check_same_thread=False)

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS conversations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        session_id TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER,
        role TEXT,
        message TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------- HOME ----------

@app.route("/")
def home():
    return send_file("index.html")

# ---------- NEW CHAT ----------

@app.route("/new_chat", methods=["POST"])
def new_chat():
    data = request.json
    session_id = data.get("session_id")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO conversations(title, session_id) VALUES(?,?)",
        ("New Chat", session_id)
    )
    conn.commit()

    chat_id = cur.lastrowid
    conn.close()

    return jsonify({"chat_id": chat_id})

# ---------- GET CHATS ----------

@app.route("/get_chats", methods=["POST"])
def get_chats():
    data = request.json
    session_id = data.get("session_id")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT id,title FROM conversations WHERE session_id=? ORDER BY id DESC",
        (session_id,)
    )
    rows = cur.fetchall()

    conn.close()

    return jsonify([{"id": r[0], "title": r[1]} for r in rows])

# ---------- DELETE CHAT ----------

@app.route("/delete_chat/<int:chat_id>", methods=["POST"])
def delete_chat(chat_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM messages WHERE conversation_id=?", (chat_id,))
    cur.execute("DELETE FROM conversations WHERE id=?", (chat_id,))
    conn.commit()
    conn.close()

    return jsonify({"status": "deleted"})

# ---------- LOAD CHAT ----------

@app.route("/load_chat/<int:chat_id>")
def load_chat(chat_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT role,message FROM messages WHERE conversation_id=? ORDER BY id",
        (chat_id,)
    )

    rows = cur.fetchall()
    conn.close()

    return jsonify([{"role": r[0], "message": r[1]} for r in rows])

# ---------- RENAME CHAT ----------

@app.route("/rename_chat/<int:chat_id>", methods=["POST"])
def rename_chat(chat_id):
    data = request.json
    new_title = data.get("title")

    if not new_title:
        return jsonify({"error": "Title required"}), 400

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "UPDATE conversations SET title=? WHERE id=?",
        (new_title, chat_id)
    )

    conn.commit()
    conn.close()

    return jsonify({"status": "renamed"})

# ---------- TITLE GENERATION ----------

def generate_title(user_msg):
    try:
        clean_msg = user_msg.strip()[:200]

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
    "Generate a clear, professional conversation title (3 to 6 words). "
    "Focus on the main intent of the user message. "
    "Do not include punctuation, quotes, or filler words."
)
                },
                {
                    "role": "user",
                    "content": clean_msg
                }
            ]
        )
        return response.choices[0].message.content.strip()
    except:
        return "New Chat"

# ---------- AI ----------

def generate_reply(history, user_msg):

    system_prompt = {
        "role": "system",
        "content": (
            "You are a helpful AI assistant. Always give clear, correct, and relevant answers.\n"
            "If the user speaks in Tanglish (Tamil + English mix) OR explicitly asks for Tanglish, reply in natural Tanglish.\n"
            "Otherwise, always reply in English.\n"
            "Do not generate random or unrelated sentences.\n"
            "Keep answers simple, meaningful, and context-based."
        )
    }

    messages = [system_prompt] + history[-6:] + [{"role": "user", "content": user_msg}]

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"⚠️ Error: {str(e)}"

# ---------- CHAT ----------

@app.route("/chat", methods=["POST"])
def chat():

    data = request.json
    msg = data["message"]
    chat_id = data["chat_id"]

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO messages(conversation_id,role,message) VALUES(?,?,?)",
        (chat_id, "user", msg)
    )
    conn.commit()

    cur.execute("SELECT title FROM conversations WHERE id=?", (chat_id,))
    current_title = cur.fetchone()[0]

    if current_title == "New Chat":
        new_title = generate_title(msg)
        cur.execute(
            "UPDATE conversations SET title=? WHERE id=?",
            (new_title, chat_id)
        )
        conn.commit()

    cur.execute(
        "SELECT role,message FROM messages WHERE conversation_id=? ORDER BY id",
        (chat_id,)
    )

    rows = cur.fetchall()
    history = [{"role": r[0], "content": r[1]} for r in rows]

    reply = generate_reply(history, msg)

    cur.execute(
        "INSERT INTO messages(conversation_id,role,message) VALUES(?,?,?)",
        (chat_id, "assistant", reply)
    )

    conn.commit()
    conn.close()

    return jsonify({"reply": reply})

# ---------- RUN ----------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))