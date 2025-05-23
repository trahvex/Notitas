from pydantic import BaseModel

class MessageCreate(BaseModel):
    text: str
    author: str

class MessageOut(BaseModel):
    id: int
    text: str
    created_at: str
    author: str

    class Config:
        orm_mode = True
