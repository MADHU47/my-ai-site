import os
import psycopg2
import urllib.parse
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# 1. SETUP & CONFIG
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Get the URL from Render Environment Variables
DB_URL = os.environ.get("DATABASE_URL")

# 2. DATA MODELS (Defined before routes to avoid NameError)
class UserData(BaseModel):
    username: str
    email: str

# 3. DATABASE FUNCTIONS
def get_db_connection():
    if not DB_URL:
        raise ValueError("DATABASE_URL environment variable is not set!")
    # sslmode is required for Supabase
    return psycopg2.connect(DB_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # PostgreSQL 'SERIAL' replaces SQLite 'AUTOINCREMENT'
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT NOT NULL
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

# Initialize the table on startup
init_db()

# 4. ROUTES
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/register")
async def register_user(data: UserData):
    conn = get_db_connection()
    cursor = conn.cursor()
    # PostgreSQL uses %s instead of ?
    cursor.execute("INSERT INTO users (username, email) VALUES (%s, %s)", (data.username, data.email))
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "Saved to Supabase Cloud!"}

@app.get("/view-users", response_class=HTMLResponse)
async def view_users(request: Request):
    conn = get_db_connection() # Switched from sqlite3 to Postgres
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email FROM users")
    all_users = cursor.fetchall()
    cursor.close()
    conn.close()
    return templates.TemplateResponse("users.html", {"request": request, "user_list": all_users})

@app.get("/check-env")
def check_env():
    if DB_URL:
        return {"status": "Found!", "preview": DB_URL[:15] + "..."}
    return {"status": "Not Found. Check Render Environment settings."}

# 5. SERVER RUNNER
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)