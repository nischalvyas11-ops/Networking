import os
import sqlite3
import re
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from pydantic import BaseModel

app = FastAPI(title="SVNIT Networking")

# Session middleware configured for Render proxy headers
app.add_middleware(
    SessionMiddleware, 
    secret_key="svnit_super_secret_random_string_987",
    same_site="lax",
    https_only=True
)

templates = Jinja2Templates(directory="templates")

if os.path.exists("static"):
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Environment variables provided by Render
TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

def get_db():
    """
    Returns a robust database connection for Turso cloud or local fallback.
    """
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        import libsql
        try:
            conn = libsql.connect(
                database=TURSO_DATABASE_URL, 
                auth_token=TURSO_AUTH_TOKEN
            )
            return conn
        except Exception as e:
            print(f"Turso connection error: {e}")
            raise HTTPException(status_code=500, detail="Cloud database connection failed.")
    else:
        conn = sqlite3.connect("svnit_network.db")
        conn.row_factory = sqlite3.Row
        return conn

def get_current_user(request: Request):
    user_session = request.session.get("user")
    if not user_session or "email" not in user_session:
        return None
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (user_session["email"],))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            if hasattr(row, "keys"):
                return dict(row)
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                return dict(zip(columns, row))
    except Exception:
        pass
    
    request.session.clear()
    return None

oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                name TEXT,
                department TEXT,
                batch TEXT,
                avatar_url TEXT DEFAULT '',
                bio TEXT DEFAULT ''
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT,
                user_name TEXT,
                department TEXT,
                batch TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_email TEXT,
                recipient_email TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER,
                user_email TEXT,
                user_name TEXT,
                department TEXT,
                batch TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS upvotes (
                question_id INTEGER,
                user_email TEXT,
                PRIMARY KEY (question_id, user_email)
            )
        """)
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database initialization error: {e}")

@app.on_event("startup")
def startup_event():
    init_db()

def parse_svnit_email(email: str):
    email_lower = email.lower()
    local_part = email_lower.split('@')[0]
    
    department = "General / Undergraduate"
    batch_year = "2026"
    
    if "ai" in local_part:
        department = "Artificial Intelligence"
    elif "ece" in local_part or "ec" in local_part:
        department = "Electronics and Communication"
    elif "cs" in local_part or "co" in local_part:
        department = "Computer Science"
    elif "ee" in local_part:
        department = "Electrical Engineering"
    elif "me" in local_part or "mech" in local_part:
        department = "Mechanical Engineering"
    elif "ce" in local_part or "civ" in local_part:
        department = "Civil Engineering"
    elif "ch" in local_part or "che" in local_part:
        department = "Chemical Engineering"
    elif "ph" in local_part or "phy" in local_part:
        department = "Physics"
    elif "cy" in local_part or "chem" in local_part:
        department = "Chemistry"
    elif "mh" in local_part or "amh" in local_part:
        department = "Mathematics"
    elif "ic" in local_part or "id" in local_part:
        department = "Industrial Chemistry"
    elif "vl" in local_part or "eve" in local_part:
        department = "Electronics and VLSI"
        
    match = re.search(r'(?:i|u)?(\d{2})', local_part)
    if match:
        YY = match.group(1)
        if int(YY) >= 20 and int(YY) <= 30:
            batch_year = f"20{YY}"
        
    return {
        "department": department,
        "batch": batch_year
    }

# --- Page Routes ---

@app.get("/")
async def home(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="index.html", context={})

@app.get("/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for('auth_callback')
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        return {"error": f"Auth error: {str(e)}"}
    
    user_info = token.get('userinfo')
    if not user_info:
        resp = await oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo', token=token)
        user_info = resp.json()

    email = user_info.get('email', '')
    full_name = user_info.get('name', 'SVNIT Student')
    picture = user_info.get('picture', '')

    if not (email.endswith('@svnit.ac.in') or email.endswith('@aid.svnit.ac.in')):
        return {"error": "Access denied. Only official @svnit.ac.in and @aid.svnit.ac.in emails are allowed."}

    parsed_metadata = parse_svnit_email(email)

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (email, name, department, batch, avatar_url) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(email) DO UPDATE SET 
                name=?, 
                department=?, 
                batch=?, 
                avatar_url=?
        """, (
            email, full_name, parsed_metadata["department"], parsed_metadata["batch"], picture,
            full_name, parsed_metadata["department"], parsed_metadata["batch"], picture
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        return {"error": f"Database write error during login: {str(e)}"}

    request.session['user'] = {
        "email": email,
        "name": full_name,
        "department": parsed_metadata["department"],
        "batch": parsed_metadata["batch"],
        "avatar_url": picture
    }

    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/dashboard")
async def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    
    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html", 
        context={
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "department": user.get("department", ""),
            "batch": user.get("batch", ""),
            "avatar_url": user.get("avatar_url", "")
        }
    )

@app.get("/inbox")
async def inbox(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
        
    return templates.TemplateResponse(
        request=request, 
        name="inbox.html", 
        context={
            "name": user.get("name", ""),
            "email": user.get("email", "")
        }
    )

@app.get("/profile", response_class=HTMLResponse)
async def view_profile(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request, 
        name="profile.html", 
        context={"user": user}
    )

@app.post("/profile/update-bio")
async def update_bio(request: Request, bio: str = Form("")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET bio = ? WHERE email = ?", (bio, user["email"]))
        conn.commit()
        conn.close()
    except Exception:
        pass
    
    return RedirectResponse(url="/profile", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

# --- Q&A API Routes ---

class QuestionCreate(BaseModel):
    content: str

class ReplyCreate(BaseModel):
    content: str

@app.post("/api/questions")
async def create_question(question: QuestionCreate, request: Request):
    user = get_current_user(request)
    if not user:
        return {"error": "Unauthorized"}
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO questions (user_email, user_name, department, batch, content) VALUES (?, ?, ?, ?, ?)",
            (user.get('email'), user.get('name'), user.get('department'), user.get('batch'), question.content)
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/questions")
async def get_questions(request: Request):
    user = get_current_user(request)
    my_email = user.get('email') if user else ""

    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT q.id, q.user_email, q.user_name, q.department, q.batch, q.content, q.timestamp,
                   (SELECT COUNT(*) FROM upvotes WHERE question_id = q.id) AS upvote_count,
                   (SELECT COUNT(*) FROM upvotes WHERE question_id = q.id AND user_email = ?) AS user_has_upvoted,
                   (SELECT COUNT(*) FROM replies WHERE question_id = q.id) AS reply_count
            FROM questions q
            ORDER BY q.id DESC
        """, (my_email,))
        rows = cursor.fetchall()
        conn.close()
        
        questions = []
        for row in rows:
            questions.append({
                "id": row[0],
                "user_email": row[1],
                "user_name": row[2],
                "department": row[3],
                "batch": row[4],
                "content": row[5],
                "timestamp": row[6],
                "upvotes": row[7],
                "has_upvoted": bool(row[8]),
                "reply_count": row[9]
            })
        return questions
    except Exception as e:
        return []

@app.post("/api/questions/{question_id}/upvote")
async def toggle_upvote(question_id: int, request: Request):
    user = get_current_user(request)
    if not user:
        return {"error": "Unauthorized"}
    
    my_email = user.get('email')
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT 1 FROM upvotes WHERE question_id = ? AND user_email = ?", (question_id, my_email))
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute("DELETE FROM upvotes WHERE question_id = ? AND user_email = ?", (question_id, my_email))
            status = "unvoted"
        else:
            cursor.execute("INSERT INTO upvotes (question_id, user_email) VALUES (?, ?)", (question_id, my_email))
            status = "upvoted"
            
        conn.commit()
        conn.close()
        return {"status": status}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/questions/{question_id}/replies")
async def get_replies(question_id: int, request: Request):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_email, user_name, department, batch, content, timestamp FROM replies WHERE question_id = ? ORDER BY id ASC", (question_id,))
        rows = cursor.fetchall()
        conn.close()
        
        replies = []
        for r in rows:
            replies.append({
                "id": r[0],
                "user_email": r[1],
                "user_name": r[2],
                "department": r[3],
                "batch": r[4],
                "content": r[5],
                "timestamp": r[6]
            })
        return replies
    except Exception:
        return []

@app.post("/api/questions/{question_id}/replies")
async def create_reply(question_id: int, reply: ReplyCreate, request: Request):
    user = get_current_user(request)
    if not user:
        return {"error": "Unauthorized"}
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO replies (question_id, user_email, user_name, department, batch, content) VALUES (?, ?, ?, ?, ?, ?)",
            (question_id, user.get('email'), user.get('name'), user.get('department'), user.get('batch'), reply.content)
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

@app.delete("/api/questions/{question_id}")
async def delete_question(question_id: int, request: Request):
    user = get_current_user(request)
    if not user:
        return {"error": "Unauthorized"}
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT user_email FROM questions WHERE id = ?", (question_id,))
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return {"error": "Not found"}
            
        if row[0] != user.get('email'):
            conn.close()
            return {"error": "Forbidden"}
            
        cursor.execute("DELETE FROM questions WHERE id = ?", (question_id,))
        cursor.execute("DELETE FROM replies WHERE question_id = ?", (question_id,))
        cursor.execute("DELETE FROM upvotes WHERE question_id = ?", (question_id,))
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

# --- Direct Messaging API Routes ---

class MessageCreate(BaseModel):
    recipient_email: str
    content: str

@app.get("/api/users")
async def get_users(request: Request):
    user = get_current_user(request)
    if not user:
        return {"error": "Unauthorized"}
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT email, name, department, batch FROM users WHERE email != ?", (user.get('email'),))
        rows = cursor.fetchall()
        conn.close()
        
        users_list = []
        for r in rows:
            users_list.append({
                "email": r[0],
                "name": r[1],
                "department": r[2],
                "batch": r[3]
            })
        return users_list
    except Exception:
        return []

@app.post("/api/messages")
async def send_message(msg: MessageCreate, request: Request):
    user = get_current_user(request)
    if not user:
        return {"error": "Unauthorized"}
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (sender_email, recipient_email, content) VALUES (?, ?, ?)",
            (user.get('email'), msg.recipient_email, msg.content)
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/messages/{peer_email}")
async def get_messages(peer_email: str, request: Request):
    user = get_current_user(request)
    if not user:
        return {"error": "Unauthorized"}
    
    my_email = user.get('email')
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sender_email, recipient_email, content, timestamp 
            FROM messages 
            WHERE (sender_email = ? AND recipient_email = ?) 
               OR (sender_email = ? AND recipient_email = ?)
            ORDER BY timestamp ASC
        """, (my_email, peer_email, peer_email, my_email))
        rows = cursor.fetchall()
        conn.close()
        
        messages = []
        for r in rows:
            messages.append({
                "sender_email": r[0],
                "recipient_email": r[1],
                "content": r[2],
                "timestamp": r[3]
            })
        return messages
    except Exception:
        return []

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)