from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.pic.config import get_settings

# Same database as the PIC API (Neon PostgreSQL): DATABASE_URL from the environment or backend/.env.
DATABASE_URL = get_settings().sqlalchemy_url

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
