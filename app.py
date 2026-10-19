import sqlite3
import re
import os
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from pydantic import BaseModel

# Initialize FastAPI app
app = FastAPI()

# Secure session middleware for tracking logged-in users
app.add_middleware(SessionMiddleware, secret_key="svnit_super_secret_random_string_987")

# Setup Jinja2 HTML templates
templates = Jinja2Templates(directory="templates")

def get_db():
    conn = sqlite3.connect("svnit_network.db")
    conn.row_factory = sqlite3.Row  # Allows accessing columns by name like user["email"]
    return conn

def get_current_user(request: Request):
    user_session = request.session.get("user")
    if not user_session or "email" not in user_session:
        return None
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (user_session["email"],))
    user = cursor.fetchone()
    conn.close()
    
    return user

# Configure Google OAuth
oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

def init_db():
    conn = sqlite3.connect("svnit_network.db")
    cursor = conn.cursor()
    
    # Questions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT,
            department TEXT,
            batch TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Unified Users directory & profile table
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
    
    # Direct Messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_email TEXT,
            recipient_email TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Safely add columns if the table already existed without them
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column already exists
        
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    conn.commit()
    conn.close()

# Automatically run init_db when FastAPI starts up
@app.on_event("startup")
def startup_event():
    init_db()

def parse_svnit_email(email: str):
    """Extracts department and batch year from an SVNIT email (e.g., i26ai007@aid.svnit.ac.in)."""
    email_lower = email.lower()
    local_part = email_lower.split('@')[0]
    
    department = "Artificial Intelligence"
    batch_year = "2026"
    
    if "ai" in local_part:
        department = "Artificial Intelligence"
    elif "ec" in local_part:
        department = "Electronics and Communication"
    elif "ee" in local_part:
        department = "Electrical Engineering"
    elif "cs" in local_part:
        department = "Computer Science"
        
    match = re.search(r'i(\d{2})', local_part)
    if match:
        batch_year = f"20{match.group(1)}"
        
    return {
        "department": department,
        "batch": batch_year
    }

# --- Page Routes ---

@app.get("/")
async def home(request: Request):
    if "user" in request.session:
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
    picture = user_info.get('picture', '')  # Extracted Google profile picture URL

    if not (email.endswith('@svnit.ac.in') or email.endswith('@aid.svnit.ac.in')):
        return {"error": "Access denied. Only official @svnit.ac.in and @aid.svnit.ac.in emails are allowed."}

    parsed_metadata = parse_svnit_email(email)

    # Upsert user into database directory (including avatar_url)
    conn = sqlite3.connect("svnit_network.db")
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
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url="/", status_code=303)
    
    return templates.TemplateResponse(
        request=request, 
        name="dashboard.html", 
        context={
            "name": user.get('name'),
            "department": user.get('department'),
            "batch": user.get('batch'),
            "avatar_url": user.get('avatar_url')
        }
    )

@app.get("/inbox")
async def inbox(request: Request):
    user = request.session.get('user')
    if not user:
        return RedirectResponse(url="/", status_code=303)
        
    return templates.TemplateResponse(
        request=request, 
        name="inbox.html", 
        context={
            "name": user.get('name'),
            "email": user.get('email')
        }
    )

# --- Profile Management Routes ---

@app.get("/profile", response_class=HTMLResponse)
async def view_profile(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})

@app.post("/profile/update-bio")
async def update_bio(request: Request, bio: str = Form("")):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET bio = ? WHERE email = ?", 
        (bio, user["email"])
    )
    conn.commit()
    conn.close()
    
    return RedirectResponse(url="/profile", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

# --- Q&A API Routes ---

class QuestionCreate(BaseModel):
    content: str

@app.post("/api/questions")
async def create_question(question: QuestionCreate, request: Request):
    user = request.session.get('user')
    if not user:
        return {"error": "Unauthorized"}
    
    conn = sqlite3.connect("svnit_network.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO questions (user_name, department, batch, content) VALUES (?, ?, ?, ?)",
        (user.get('name'), user.get('department'), user.get('batch'), question.content)
    )
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/api/questions")
async def get_questions(request: Request):
    conn = sqlite3.connect("svnit_network.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_name, department, batch, content, timestamp FROM questions ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    
    questions = []
    for row in rows:
        questions.append({
            "id": row[0],
            "user_name": row[1],
            "department": row[2],
            "batch": row[3],
            "content": row[4],
            "timestamp": row[5]
        })
    return questions

# --- Messaging API Routes ---

class MessageCreate(BaseModel):
    recipient_email: str
    content: str

@app.get("/api/users")
async def get_users(request: Request):
    user = request.session.get('user')
    if not user:
        return {"error": "Unauthorized"}
    
    conn = sqlite3.connect("svnit_network.db")
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

@app.post("/api/messages")
async def send_message(msg: MessageCreate, request: Request):
    user = request.session.get('user')
    if not user:
        return {"error": "Unauthorized"}
    
    conn = sqlite3.connect("svnit_network.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (sender_email, recipient_email, content) VALUES (?, ?, ?)",
        (user.get('email'), msg.recipient_email, msg.content)
    )
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/api/messages/{peer_email}")
async def get_messages(peer_email: str, request: Request):
    user = request.session.get('user')
    if not user:
        return {"error": "Unauthorized"}
    
    my_email = user.get('email')
    conn = sqlite3.connect("svnit_network.db")
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

# --- Server Startup ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)