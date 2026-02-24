from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from typing import List
from sqlalchemy import func     
from sqlalchemy.orm import Session
from . import models, schemas
from .database import Base, engine, SessionLocal
from fastapi.templating import Jinja2Templates
from datetime import date, datetime
import random
import os

Base.metadata.create_all(bind=engine)

app = FastAPI()

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})

@app.post("/messages/submit")
def submit_form(text: str = Form(...), author: str = Form(...), db: Session = Depends(get_db)):
    message = models.Message(text=text, author=author)
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
def messages_today(db: Session = Depends(get_db)):
    today = date.today()
    messages = db.query(models.Message).filter(func.date(models.Message.created_at) == today).all()
    
    if not messages:
        refranes_path = "app/static/refranes.txt"
        if os.path.exists(refranes_path):
            with open(refranes_path, "r", encoding="utf-8") as f:
                refranes = [line.strip() for line in f if line.strip()]
            if refranes:
                # Use the date string as seed for daily consistency
                random.seed(today.strftime("%Y%m%d"))
                refran = random.choice(refranes)
                random.seed(None) # Reset seed
                return {
                    "notes": [
                        {
                            "id": 0,
                            "text": refran,
                            "author": "Refranero popular",
                            "created_at": datetime.now()
                        }
                    ]
                }
    
    notes = [schemas.MessageOut.model_validate(m) for m in messages]
    return {"notes": notes}

@app.get("/messages/all/", response_model=dict)
def get_all_messages(db: Session = Depends(get_db)):
    messages = db.query(models.Message).all()
    notes = [schemas.MessageOut.model_validate(m) for m in messages]
    return {"notes": notes}