import psycopg2 # Use this instead of sqlite3
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import sqlite3
from pydantic import BaseModel
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Replace this with your actual URI from Supabase
#DB_URL = "postgresql://postgres:[YOUR-PASSWORD]@db.wizruqwyffvdqjxbxkgr.supabase.co:5432/postgres"

# This line says: "Look for a variable named DATABASE_URL. 
# If you don't find it, use None."
DB_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if DB_URL is None:
        raise ValueError("DATABASE_URL environment variable is not set!")
    conn = psycopg2.connect(DB_URL)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # PostgreSQL uses slightly different syntax (SERIAL instead of AUTOINCREMENT)
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

init_db()

@app.post("/register")
async def register_user(data: UserData):
    conn = get_db_connection()
    cursor = conn.cursor()
    # PostgreSQL uses %s as placeholders instead of ?
    cursor.execute("INSERT INTO users (username, email) VALUES (%s, %s)", (data.username, data.email))
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "Saved to Cloud Database!"}

if __name__ == "__main__":
    import uvicorn
    # Important: Use 0.0.0.0 and dynamic port for Render
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)


    # ... (rest of your existing code)

@app.get("/view-users", response_class=HTMLResponse)
async def view_users(request: Request):
    conn = sqlite3.connect('my_website.db')
    cursor = conn.cursor()
    # Fetch all users from the table
    cursor.execute("SELECT id, username, email FROM users")
    all_users = cursor.fetchall()
    conn.close()
    
    # Send the list of users to the HTML template
    return templates.TemplateResponse("users.html", {"request": request, "user_list": all_users})

    @app.get("/check-env")
def check_env():
    # This checks if the variable exists without revealing the full password
    if os.environ.get("DATABASE_URL"):
        # We only show the first 10 characters for safety
        return {"status": "Found!", "preview": os.environ.get("DATABASE_URL")[:10] + "..."}
    else:
        return {"status": "Not Found. Check Render settings."}