import os
import psycopg2
import urllib.parse
import secrets
from fastapi import FastAPI, Request, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from supabase import create_client, Client

# 1. SETUP & CONFIG
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Environment Variables
DB_URL = os.environ.get("DATABASE_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Initialize Supabase Client for Storage
# Ensure these variables are set in Render!
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

security = HTTPBasic()

# 2. DATA MODELS
class UserData(BaseModel):
    username: str
    email: str

# 3. DATABASE & SECURITY FUNCTIONS
def get_db_connection():
    if not DB_URL:
        raise ValueError("DATABASE_URL environment variable is not set!")
    return psycopg2.connect(DB_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Create Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT NOT NULL
        )
    ''')
    # Create Image Metadata Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS image_metadata (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            file_name TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            public_url TEXT NOT NULL,
            uploaded_by TEXT NOT NULL
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

# Initialize tables on startup
init_db()

def authenticate_user(credentials: HTTPBasicCredentials = Depends(security)):
    # Fetching credentials from Render Env Vars
    u1, p1 = os.environ.get("ADMIN_USERNAME"), os.environ.get("ADMIN_PASSWORD")
    u2, p2 = os.environ.get("USER2_USERNAME"), os.environ.get("USER2_PASSWORD")

    is_user1 = (u1 and p1 and 
                secrets.compare_digest(credentials.username, u1) and 
                secrets.compare_digest(credentials.password, p1))
    
    is_user2 = (u2 and p2 and 
                secrets.compare_digest(credentials.username, u2) and 
                secrets.compare_digest(credentials.password, p2))

    if not (is_user1 or is_user2):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# 4. ROUTES

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# --- GALLERY & UPLOAD LOGIC ---

@app.get("/view-gallery", response_class=HTMLResponse)
async def view_gallery(request: Request, username: str = Depends(authenticate_user)):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT file_name, public_url, uploaded_by FROM image_metadata ORDER BY created_at DESC")
    images = cur.fetchall()
    cur.close()
    conn.close()
    
    image_list = [
        {"file_name": row[0], "public_url": row[1], "uploaded_by": row[2]} 
        for row in images
    ]
    return templates.TemplateResponse("gallery.html", {
        "request": request, 
        "images": image_list, 
        "current_user": username
    })

@app.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...), 
    username: str = Depends(authenticate_user)
):
    # 1. Read file content
    file_content = await file.read()
    # Path inside the bucket (organized by user)
    file_path = f"{username}/{file.filename}"

    # 2. Upload to Supabase Storage Bucket: "new gallery"
    supabase.storage.from_("new gallery").upload(
        path=file_path,
        file=file_content,
        file_options={"content-type": file.content_type}
    )

    # 3. Get Public URL from "new gallery"
    public_url = supabase.storage.from_("new gallery").get_public_url(file_path)

    # 4. Save metadata to Postgres
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO image_metadata (file_name, storage_path, public_url, uploaded_by) VALUES (%s, %s, %s, %s)",
        (file.filename, file_path, public_url, username)
    )
    conn.commit()
    cur.close()
    conn.close()

    return {"status": "Uploaded Successfully to 'new gallery'", "url": public_url}

# --- EXISTING REGISTRATION LOGIC ---

@app.post("/register")
async def register_user(data: UserData):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO users (username, email) VALUES (%s, %s)", (data.username, data.email))
    conn.commit()
    cursor.close()
    conn.close()
    return {"status": "Saved to Supabase Cloud!"}

@app.get("/view-users", response_class=HTMLResponse)
async def view_users(request: Request):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email FROM users")
    all_users = cursor.fetchall()
    cursor.close()
    conn.close()
    return templates.TemplateResponse("users.html", {"request": request, "user_list": all_users})

@app.get("/check-env")
def check_env():
    return {
        "db_status": "Found" if DB_URL else "Missing",
        "supabase_url": "Found" if SUPABASE_URL else "Missing",
        "supabase_key": "Found" if SUPABASE_KEY else "Missing",
        "auth_users_configured": "Yes" if (os.environ.get("ADMIN_USERNAME") and os.environ.get("USER2_USERNAME")) else "No"
    }

# 5. SERVER RUNNER
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)