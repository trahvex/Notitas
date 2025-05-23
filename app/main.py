from fastapi import FastAPI, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from . import models, schemas
from .database import Base, engine, SessionLocal
from fastapi.templating import Jinja2Templates
from datetime import datetime

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

@app.get("/messages/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})

@app.post("/messages/submit")
def submit_form(text: str = Form(...), author: str = Form(...), db: Session = Depends(get_db)):
    message = models.Message(text=text, author=author)
    db.add(message)
    db.commit()
    return RedirectResponse("/messages/", status_code=303)

@app.post("/messages/create", response_model=schemas.MessageOut)
def create_message(msg: schemas.MessageCreate, db: Session = Depends(get_db)):
    message = models.Message(text=msg.text, author=msg.author)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message

@app.get("/messages/today/", response_model=schemas.MessageOut)
def latest_message(db: Session = Depends(get_db)):
    return db.query(models.Message).order_by(models.Message.created_at.desc()).filter(models.Message.created_at  >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
