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
    image_path: str | None = None

    model_config = {
        "from_attributes": True
    }
