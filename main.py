import os
import re
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# 1. Obtener y limpiar rigurosamente la variable de entorno
raw_url = os.environ.get("DATABASE_URL", "sqlite:///./local.db")
# Eliminar comillas simples, dobles, espacios y saltos de línea accidentales
clean_url = raw_url.strip().strip("'").strip('"').strip()

# 2. Corregir protocolo para compatibilidad con SQLAlchemy
if clean_url.startswith("postgres://"):
    clean_url = clean_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif clean_url.startswith("postgresql://") and not clean_url.startswith("postgresql+psycopg2://"):
    clean_url = clean_url.replace("postgresql://", "postgresql+psycopg2://", 1)

try:
    engine = create_engine(clean_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()

    class Usuario(Base):
        __tablename__ = "usuarios"
        id = Column(Integer, primary_key=True, index=True)
        email = Column(String, unique=True, index=True, nullable=False)
        plan = Column(String, default="standard")

    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"Error inicializando la base de datos: {e}")
    # Fallback seguro para evitar que el servicio se caiga por completo
    engine = create_engine("sqlite:///./fallback.db")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()

app = FastAPI(title="Clofovoz Music SaaS API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class RegistroRequest(BaseModel):
    email: str
    plan: str = "standard"

@app.get("/")
def root():
    return {"status": "Clofovoz Music SaaS activo", "env": "Render"}

@app.post("/api/registro")
def registrar(req: RegistroRequest, db: Session = Depends(get_db)):
    existente = db.query(Usuario).filter(Usuario.email == req.email).first()
    if existente:
        raise HTTPException(status_code=400, detail="El correo ya está registrado.")
    nuevo = Usuario(email=req.email, plan=req.plan)
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"mensaje": "Usuario registrado exitosamente", "id": nuevo.id, "email": nuevo.email}
