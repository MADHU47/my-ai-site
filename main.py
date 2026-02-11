import os
import psycopg2
import secrets
from fastapi import FastAPI, Request, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from supabase import create_client, Client

# 1. SETUP & CONFIG
app = FastAPI()
templates = Jinja2Templates(directory="templates")

DB_URL = os.environ.get("DATABASE_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

security = HTTPBasic()

# 2. DATABASE & SECURITY
def get_db_connection():
    return psycopg2.connect(DB_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT, email TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS image_metadata (
                        id SERIAL PRIMARY KEY,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        file_name TEXT NOT NULL,
                        storage_path TEXT NOT NULL,
                        public_url TEXT NOT NULL,
                        uploaded_by TEXT NOT NULL)''')
    conn.commit()
    cursor.close()
    conn.close()

init_db()

def authenticate_user(credentials: HTTPBasicCredentials = Depends(security)):
    u1, p1 = os.environ.get("ADMIN_USERNAME"), os.environ.get("ADMIN_PASSWORD")
    u2, p2 = os.environ.get("USER2_USERNAME"), os.environ.get("USER2_PASSWORD")
    is_user1 = (u1 and p1 and secrets.compare_digest(credentials.username, u1) and secrets.compare_digest(credentials.password, p1))
    is_user2 = (u2 and p2 and secrets.compare_digest(credentials.username, u2) and secrets.compare_digest(credentials.password, p2))
    if not (is_user1 or is_user2):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return credentials.username

# 3. ROUTES
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

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
        f_name, s_path, u_by = row
        try:
            # Generate 15-min Signed URL for Private Bucket
            response = supabase.storage.from_("new gallery").create_signed_url(s_path, 900)
            image_list.append({
                "file_name": f_name,
                "signed_url": response['signedURL'],
                "uploaded_by": u_by,
                "storage_path": s_path # Necessary for the delete button
            })
        except: continue
            
    return templates.TemplateResponse("gallery.html", {"request": request, "images": image_list, "current_user": username})

@app.post("/upload-image")
async def upload_image(file: UploadFile = File(...), username: str = Depends(authenticate_user)):
    file_content = await file.read()
    file_path = f"{username}/{file.filename}"
    supabase.storage.from_("new gallery").upload(path=file_path, file=file_content, file_options={"content-type": file.content_type})
    public_url = supabase.storage.from_("new gallery").get_public_url(file_path)
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO image_metadata (file_name, storage_path, public_url, uploaded_by) VALUES (%s, %s, %s, %s)",
                (file.filename, file_path, public_url, username))
    conn.commit()
    cur.close()
    conn.close()
    return RedirectResponse(url="/view-gallery", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/delete-image")
async def delete_image(file_path: str = Form(...), username: str = Depends(authenticate_user)):
    # Both users can delete anything, so we skip the ownership check
    supabase.storage.from_("new gallery").remove([file_path])
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM image_metadata WHERE storage_path = %s", (file_path,))
    conn.commit()
    cur.close()
    conn.close()
    return RedirectResponse(url="/view-gallery", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/register")
async def register_user(data: UserData):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO users (username, email) VALUES (%s, %s)", (data.username, data.email))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "User Registered"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))