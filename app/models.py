from sqlalchemy import Column, Integer, Text, DateTime
from datetime import datetime
from .database import Base
from zoneinfo import ZoneInfo

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now(tz=ZoneInfo("Europe/Madrid")))
    author = Column(Text, nullable = False)
