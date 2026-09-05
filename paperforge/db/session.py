import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from paperforge.db.models import Base

def get_engine(db_path: str = ".paperforge/paperforge.db"):
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return engine

def init_db(db_path: str = ".paperforge/paperforge.db"):
    engine = get_engine(db_path)
    Base.metadata.create_all(bind=engine)
    return engine

def get_session(db_path: str = ".paperforge/paperforge.db"):
    engine = get_engine(db_path)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()
