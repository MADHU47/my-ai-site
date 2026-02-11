from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import sqlite3
from pydantic import BaseModel

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# This helps Python understand the data coming from JavaScript
class UserData(BaseModel):
    username: str
    email: str

# 1. This route shows your website
@app.get("/", response_class=HTMLResponse)
async def serve_home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# 2. This route receives the data and saves it to the database
@app.post("/register")
async def register_user(data: UserData):
    conn = sqlite3.connect('my_website.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (username, email) VALUES (?, ?)", (data.username, data.email))
    conn.commit()
    conn.close()
    return {"status": f"Success! {data.username} has been saved to the database."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)