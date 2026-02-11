from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import sqlite3
from pydantic import BaseModel
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- ADD THIS NEW FUNCTION HERE ---
def init_db():
    conn = sqlite3.connect('my_website.db')
    cursor = conn.cursor()
    # This creates the table if it's missing on the server
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# Run the initialization
init_db()
# ----------------------------------

class UserData(BaseModel):
    username: str
    email: str

@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/register")
async def register_user(data: UserData):
    conn = sqlite3.connect('my_website.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (username, email) VALUES (?, ?)", (data.username, data.email))
    conn.commit()
    conn.close()
    return {"status": f"Success! {data.username} saved to the database."}

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