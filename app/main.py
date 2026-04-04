from fastapi import FastAPI, Depends, Request, Form, UploadFile, File, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List
from sqlalchemy import func     
from sqlalchemy.orm import Session
from . import models, schemas
from .database import Base, engine, SessionLocal
from fastapi.templating import Jinja2Templates
from datetime import date, datetime, timezone, timedelta
import random
import os
import json
import base64
import mimetypes
import uuid
from dotenv import load_dotenv

load_dotenv()
API_TOKEN = os.getenv("TRMNL_API_TOKEN")
IMAGE_TOKEN = os.getenv("IMAGE_API_TOKEN", API_TOKEN)
IMAGE_DIR = "data/images"

def verify_token(authorization: str = Header(None), token: str = None):
    req_token = None
    if authorization and authorization.startswith("Bearer "):
        req_token = authorization.split(" ")[1]
    elif token:
        req_token = token
    if not API_TOKEN or req_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

def verify_image_token(token: str = None):
    if not IMAGE_TOKEN or token != IMAGE_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

Base.metadata.create_all(bind=engine)

app = FastAPI()

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/messages/image/{filename}")
def get_message_image(filename: str, _=Depends(verify_image_token)):
    file_path = os.path.join(IMAGE_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(file_path)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request=request, name="form.html")

@app.post("/messages/submit")
def submit_form(text: str = Form(...), author: str = Form(...), image: UploadFile = File(None), db: Session = Depends(get_db)):
    image_path = None
    if image and image.filename:
        filename = f"{uuid.uuid4()}_{image.filename}"
        os.makedirs(IMAGE_DIR, exist_ok=True)
        filepath = os.path.join(IMAGE_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(image.file.read())
        image_path = filename # Guardar solo nombre para el endpoint relativo

    message = models.Message(text=text, author=author, image_path=image_path)
    db.add(message)
    db.commit()
    return RedirectResponse("/", status_code=303)

@app.post("/messages/create", response_model=schemas.MessageOut)
def create_message(msg: schemas.MessageCreate, db: Session = Depends(get_db)):
    message = models.Message(text=msg.text, author=msg.author)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message

@app.get("/messages/today/", response_model=dict)
def messages_today(request: Request, db: Session = Depends(get_db), _=Depends(verify_token)):
    today = date.today()
    messages = db.query(models.Message).filter(func.date(models.Message.created_at) == today).all()
    
    notes = []
    
    # Add daily "refran" (proverb)
    refranes_path = "app/static/refranes.txt"
    if os.path.exists(refranes_path):
        with open(refranes_path, "r", encoding="utf-8") as f:
            refranes = [line.strip() for line in f if line.strip()]
        if refranes:
            # Use the date string as seed for daily consistency
            random.seed(today.strftime("%Y%m%d"))
            refran = random.choice(refranes)
            random.seed(None) # Reset seed
            notes.append({
                "id": 0,
                "text": refran,
                "author": "Refranero popular",
                "created_at": datetime.now()
            })
    
    notes.extend([schemas.MessageOut.model_validate(m) for m in messages])
    
    # Formateo compatible para cualquier layout de TRMNL
    notes_data = []
    for note in notes:
        # Pydantic model a dict
        note_dict = note.model_dump() if hasattr(note, 'model_dump') else dict(note)
        # TRMNL parsea mejor los datetime si son string en Liquid
        if "created_at" in note_dict and isinstance(note_dict["created_at"], datetime):
            note_dict["created_at"] = note_dict["created_at"].strftime('%Y-%m-%d %H:%M')
            
        if note_dict.get("image_path"):
            base_url = str(request.base_url).rstrip("/")
            filename = note_dict["image_path"].split("/")[-1]
            note_dict["image_url"] = f"{base_url}/messages/image/{filename}?token={IMAGE_TOKEN}"

        notes_data.append(note_dict)
    
    primary_note = notes_data[0] if notes_data else {"text": "No hay mensajes", "author": ""}
    secondary_note = notes_data[1] if len(notes_data) > 1 else {"text": "", "author": ""}

    return {
        "notes": notes_data, 
        "merge_variables": {
            "date": today.strftime("%d/%m/%Y"),
            "has_notes": len(notes_data) > 0,
            "total_notes": len(notes_data),
            "notes": notes_data,
            "primary_text": primary_note.get("text", ""),
            "primary_author": primary_note.get("author", ""),
            "primary_image_url": primary_note.get("image_url", ""),
            "secondary_text": secondary_note.get("text", ""),
            "secondary_author": secondary_note.get("author", "")
        }
    }

@app.get("/messages/all/", response_model=dict)
def get_all_messages(db: Session = Depends(get_db), _=Depends(verify_token)):
    messages = db.query(models.Message).all()
    notes = [schemas.MessageOut.model_validate(m) for m in messages]
    return {"notes": notes}


# ---------------------------------------------------------------------------
# Endpoint: Lanzamientos musicales de la última semana
# ---------------------------------------------------------------------------

MUSIC_RELEASES_PATH = "app/static/musica/music_releases.json"

@app.get("/music/releases/", response_model=dict)
def music_releases():
    """
    Lee el fichero generado por app/scripts/music_releases.py y devuelve
    los lanzamientos de los últimos 7 días en formato TRMNL (merge_variables).
    """
    if not os.path.exists(MUSIC_RELEASES_PATH):
        return {
            "merge_variables": {
                "has_releases": False,
                "releases": [],
                "total": 0,
                "generated_at": "",
                "week_label": "",
            }
        }

    with open(MUSIC_RELEASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    now = datetime.now(timezone.utc)
    one_week_ago = now - timedelta(days=7)

    recent: list[dict] = []
    for release in data.get("releases", []):
        raw_date = release.get("date", "")
        if not raw_date:
            continue
        # MusicBrainz puede devolver solo año ("2024") o "2024-03" o "2024-03-15"
        try:
            if len(raw_date) == 4:          # solo año
                rel_dt = datetime(int(raw_date), 1, 1, tzinfo=timezone.utc)
            elif len(raw_date) == 7:        # año-mes
                year, month = raw_date.split("-")
                rel_dt = datetime(int(year), int(month), 1, tzinfo=timezone.utc)
            else:                           # año-mes-día
                rel_dt = datetime.fromisoformat(raw_date).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        if one_week_ago <= rel_dt <= now:
            recent.append({
                "artist": release.get("artist", ""),
                "title": release.get("title", ""),
                "date": raw_date,
                "type": release.get("type", ""),
            })

    # Ordenar por fecha desc
    recent.sort(key=lambda r: r["date"], reverse=True)

    primary = recent[0] if recent else {}
    secondary = recent[1] if len(recent) > 1 else {}

    week_start = one_week_ago.strftime("%d/%m")
    week_end = now.strftime("%d/%m")

    return {
        "merge_variables": {
            "has_releases": len(recent) > 0,
            "releases": recent,
            "total": len(recent),
            "generated_at": data.get("generated_at", ""),
            "week_label": f"{week_start} – {week_end}",
            "primary_artist": primary.get("artist", ""),
            "primary_title": primary.get("title", ""),
            "primary_date": primary.get("date", ""),
            "primary_type": primary.get("type", ""),
            "secondary_artist": secondary.get("artist", ""),
            "secondary_title": secondary.get("title", ""),
            "secondary_date": secondary.get("date", ""),
            "secondary_type": secondary.get("type", ""),
        }
    }