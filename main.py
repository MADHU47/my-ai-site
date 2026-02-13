import os
import psycopg2
import secrets
import io
import string
from fastapi import FastAPI, Request, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from supabase import create_client, Client
from fastapi.staticfiles import StaticFiles



# --- 1. SETUP & CONFIG ---
app = FastAPI()
# Add this line right after app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_URL = os.environ.get("DATABASE_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
ADMIN_USER = os.environ.get("ADMIN_USERNAME")
ADMIN_PASS = os.environ.get("ADMIN_PASSWORD")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
security = HTTPBasic()

def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT NOT NULL, 
        password TEXT NOT NULL, status TEXT DEFAULT 'pending')''')
    cur.execute('''CREATE TABLE IF NOT EXISTS image_metadata (
        id SERIAL PRIMARY KEY, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        file_name TEXT NOT NULL, storage_path TEXT NOT NULL, public_url TEXT NOT NULL, uploaded_by TEXT NOT NULL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS invite_tokens (
        id SERIAL PRIMARY KEY, token TEXT UNIQUE NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW())''')
    conn.commit()
    cur.close()
    conn.close()

init_db()

# --- 2. AUTHENTICATION ---
def authenticate_user(credentials: HTTPBasicCredentials = Depends(security)):
    print(f"DEBUG: Authenticating user '{credentials.username}'")
    if ADMIN_USER and ADMIN_PASS:
        if secrets.compare_digest(credentials.username, ADMIN_USER) and \
           secrets.compare_digest(credentials.password, ADMIN_PASS):
            return credentials.username
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT password FROM users WHERE username = %s AND status = 'active'", (credentials.username,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if result and secrets.compare_digest(credentials.password, result[0]):
        return credentials.username
    print(f"DEBUG: Auth Failed for '{credentials.username}'")
    raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})

# --- 3. ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, token: str = ""):
    return templates.TemplateResponse("signup.html", {"request": request, "token": token})

@app.post("/submit-signup")
async def submit_signup(username: str = Form(...), email: str = Form(...), password: str = Form(...), invite_token: str = Form(...)):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM invite_tokens WHERE token = %s", (invite_token,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Invalid Token")
    try:
        cur.execute("INSERT INTO users (username, email, password, status) VALUES (%s, %s, %s, 'active')", (username, email, password))
        cur.execute("DELETE FROM invite_tokens WHERE token = %s", (invite_token,))
        conn.commit()
        return RedirectResponse(url="/view-gallery", status_code=303)
    except:
        conn.rollback()
        return HTMLResponse("Username already exists or Error occurred.", status_code=400)
    finally:
        cur.close()
        conn.close()

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, current_user: str = Depends(authenticate_user)):
    if current_user != ADMIN_USER: raise HTTPException(status_code=403)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT token, created_at FROM invite_tokens ORDER BY created_at DESC")
    tokens = cur.fetchall()
    cur.close()
    conn.close()
    return templates.TemplateResponse("admin.html", {"request": request, "tokens": tokens, "base_url": str(request.base_url)})

@app.post("/admin/generate-token")
async def generate_token(current_user: str = Depends(authenticate_user)):
    new_t = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO invite_tokens (token) VALUES (%s)", (new_t,))
    conn.commit()
    cur.close()
    conn.close()
    return RedirectResponse(url="/admin/dashboard", status_code=303)

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
            res = supabase.storage.from_("new gallery").create_signed_url(row[1], 900)
            image_list.append({"file_name": row[0], "signed_url": res['signedURL'], "uploaded_by": row[2], "storage_path": row[1]})
        except: continue
    return templates.TemplateResponse("gallery.html", {"request": request, "images": image_list, "current_user": username})

@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...), username: str = Depends(authenticate_user)):
    print(f"DEBUG: {username} is starting upload of {file.filename}")
    try:
        content = await file.read()
        if not content:
            return HTMLResponse("Error: File content is empty.")

        # Folder path using lowercase username
        safe_user = username.lower().strip()
        path = f"{safe_user}/{file.filename}"
        
        print(f"DEBUG: Sending to Supabase path: {path}")

        # Upload to Supabase
        supabase.storage.from_("new gallery").upload(
            path=path, 
            file=content, 
            file_options={"content-type": file.content_type, "upsert": "true"}
        )
        
        # Database Sync
        conn = get_db_connection()
        cur = conn.cursor()
        url = f"{SUPABASE_URL}/storage/v1/object/public/new%20gallery/{path}"
        cur.execute(
            "INSERT INTO image_metadata (file_name, storage_path, public_url, uploaded_by) VALUES (%s, %s, %s, %s)", 
            (file.filename, path, url, username)
        )
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"DEBUG: Upload SUCCESS for {username}")
        return RedirectResponse(url="/view-gallery", status_code=303)

    except Exception as e:
        print(f"CRITICAL ERROR: {str(e)}")
        # Returns the error directly to the browser for debugging
        return HTMLResponse(f"""
            <div style="color:red; font-family:sans-serif; padding:20px; border:2px solid red;">
                <h2>Upload Process Failed</h2>
                <p><strong>Error Message:</strong> {str(e)}</p>
                <p>Possible causes: Supabase bucket name mismatch or RLS policy block.</p>
                <a href="/view-gallery">Try to go back to Gallery</a>
            </div>
        """)

@app.get("/logout")
async def logout():
    return HTMLResponse("<script>alert('Logged out'); window.location.href='/';</script>", status_code=401)

# --- 6. ADDITIONAL MEDIA ACTIONS ---

@app.get("/download-image")
async def download_image(storage_path: str, username: str = Depends(authenticate_user)):
    """Fetches the file from Supabase and streams it to the user's browser."""
    try:
        # 1. Download the raw bytes from Supabase
        file_data = supabase.storage.from_("new gallery").download(storage_path)
        
        # 2. Extract the original filename from the path
        filename = storage_path.split("/")[-1]
        
        # 3. Stream it back so the browser treats it as a download
        return StreamingResponse(
            io.BytesIO(file_data),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        print(f"DOWNLOAD ERROR: {e}")
        raise HTTPException(status_code=500, detail="Could not download file.")

@app.post("/delete-image")
async def delete_image(file_path: str = Form(...), username: str = Depends(authenticate_user)):
    """Removes the image from both Supabase Storage and PostgreSQL Metadata."""
    try:
        # 1. Remove from Supabase Storage
        supabase.storage.from_("new gallery").remove([file_path])
        
        # 2. Remove from Database
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM image_metadata WHERE storage_path = %s", (file_path,))
        conn.commit()
        cur.close()
        conn.close()
        
        print(f"DEBUG: {username} deleted {file_path}")
        return RedirectResponse(url="/view-gallery", status_code=303)
    except Exception as e:
        print(f"DELETE ERROR: {e}")
        raise HTTPException(status_code=500, detail="Could not delete file.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))