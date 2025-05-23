from pydantic import BaseModel
from datetime import datetime

class MessageCreate(BaseModel):
    text: str
    author: str

class MessageOut(BaseModel):
    id: int
    text: str
    created_at: datetime
    author: str

    class Config:
        orm_mode = True
