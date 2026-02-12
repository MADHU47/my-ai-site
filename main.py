import os
import psycopg2
import secrets
import io
from fastapi import FastAPI, Request, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from supabase import create_client, Client

# 1. SETUP & CONFIG
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Environment Variables
DB_URL = os.environ.get("DATABASE_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
ADMIN_USER = os.environ.get("ADMIN_USERNAME")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD")

# Initialize Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
security = HTTPBasic()

# --- 2. DATABASE FUNCTIONS ---
def get_db_connection():
    if not DB_URL:
        raise HTTPException(status_code=500, detail="Database URL not configured")
    return psycopg2.connect(DB_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Updated Users Table for Moderated Access
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            password TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    ''')
    cur.execute('''
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
    cur.close()
    conn.close()

init_db()

# --- 3. AUTHENTICATION GATEKEEPER ---
def authenticate_user(credentials: HTTPBasicCredentials = Depends(security)):
    # A. Check Master Admin (from Env Vars)
    if ADMIN_USER and ADMIN_PASS:
        if secrets.compare_digest(credentials.username, ADMIN_USER) and \
           secrets.compare_digest(credentials.password, ADMIN_PASS):
            return credentials.username

    # B. Check Approved Users in Database
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username = %s AND status = 'active'", (credentials.username,))
    result = cur.fetchone()
    cur.close()
    conn.close()

    if result and secrets.compare_digest(credentials.password, result[0]):
        return credentials.username
    
    # C. Deny if neither admin nor active
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, 
        detail="Unauthorized or Pending Approval", 
        headers={"WWW-Authenticate": "Basic"}
    )

# --- 4. PUBLIC & SIGNUP ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@app.post("/submit-signup")
async def submit_signup(username: str = Form(...), email: str = Form(...), password: str = Form(...)):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, email, password, status) VALUES (%s, %s, %s, 'pending')", 
                    (username, email, password))
        conn.commit()
        cur.close()
        conn.close()
        return HTMLResponse("<h2>Request Submitted!</h2><p>Wait for admin approval.</p><a href='/'>Home</a>")
    except Exception:
        raise HTTPException(status_code=400, detail="Username already exists.")

# --- 5. ADMIN DASHBOARD ---

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, current_user: str = Depends(authenticate_user)):
    if current_user != ADMIN_USER:
        raise HTTPException(status_code=403, detail="Admins only.")
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, email, status FROM users WHERE status = 'pending'")
    pending = cur.fetchall()
    cur.close()
    conn.close()
    return templates.TemplateResponse("admin.html", {"request": request, "users": pending})

@app.post("/admin/approve")
async def approve_user(user_id: int = Form(...), current_user: str = Depends(authenticate_user)):
    if current_user == ADMIN_USER:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET status = 'active' WHERE id = %s", (user_id,))
        conn.commit()
        cur.close()
        conn.close()
    return RedirectResponse(url="/admin/dashboard", status_code=303)

# --- 6. GALLERY & MEDIA ROUTES ---

@app.get("/view-gallery", response_class=HTMLResponse)
async def view_gallery(request: Request, username: str = Depends(authenticate_user)):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT file_name, storage_path, uploaded_by FROM image_metadata ORDER BY created_at DESC")
    images = cur.fetchall()
    cur.close()
    conn.close()
    
    image_list = []
    for row in images:
        try:
            response = supabase.storage.from_("new gallery").create_signed_url(row[1], 900)
            image_list.append({
                "file_name": row[0],
                "signed_url": response['signedURL'],
                "uploaded_by": row[2],
                "storage_path": row[1]
            })
        except Exception:
            continue
            
    return templates.TemplateResponse("gallery.html", {"request": request, "images": image_list, "current_user": username})

@app.get("/download-image")
async def download_image(storage_path: str, username: str = Depends(authenticate_user)):
    try:
        file_data = supabase.storage.from_("new gallery").download(storage_path)
        filename = storage_path.split("/")[-1]
        return StreamingResponse(
            io.BytesIO(file_data),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...), username: str = Depends(authenticate_user)):
    try:
        file_content = await file.read()
        file_path = f"{username}/{file.filename}"
        supabase.storage.from_("new gallery").upload(
            path=file_path, file=file_content, 
            file_options={"content-type": file.content_type, "upsert": "true"}
        )
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM image_metadata WHERE storage_path = %s", (file_path,))
        if not cur.fetchone():
            placeholder_url = f"{SUPABASE_URL}/storage/v1/object/public/new%20gallery/{file_path}"
            cur.execute(
                "INSERT INTO image_metadata (file_name, storage_path, public_url, uploaded_by) VALUES (%s, %s, %s, %s)",
                (file.filename, file_path, placeholder_url, username)
            )
        conn.commit()
        cur.close()
        conn.close()
        return RedirectResponse(url="/view-gallery", status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/delete-image")
async def delete_image(file_path: str = Form(...), username: str = Depends(authenticate_user)):
    try:
        supabase.storage.from_("new gallery").remove([file_path])
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM image_metadata WHERE storage_path = %s", (file_path,))
        conn.commit()
        cur.close()
        conn.close()
        return RedirectResponse(url="/view-gallery", status_code=303)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/logout")
async def logout():
    return HTMLResponse(content="<script>alert('Logged out.'); window.location.href='/';</script>", status_code=401)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))