import sqlite3

DB_NAME = "svnit_networking.db"

def get_db_connection():
    """Establishes and returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_NAME)
    # Allows accessing columns by name (e.g., row['email'])
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database, creates required tables, and seeds test users."""
    conn = get_db_connection()
    
    # 1. Users table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            department TEXT NOT NULL,
            batch_year TEXT NOT NULL
        )
    ''')
    
    # 2. Questions table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (author_id) REFERENCES users (id)
        )
    ''')
    
    # 3. Messages table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            content TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users (id),
            FOREIGN KEY (receiver_id) REFERENCES users (id)
        )
    ''')
    
    # Seed default test users (ID 1 and ID 2) if the table is empty
    existing_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing_users == 0:
        conn.execute("INSERT INTO users (email, full_name, department, batch_year) VALUES (?, ?, ?, ?)",
                     ("i26ai001@aid.svnit.ac.in", "Student (I26AI001)", "Artificial Intelligence", "2026"))
        conn.execute("INSERT INTO users (email, full_name, department, batch_year) VALUES (?, ?, ?, ?)",
                     ("i26ai002@aid.svnit.ac.in", "Student (I26AI002)", "Artificial Intelligence", "2026"))
        conn.commit()
    
    conn.close()