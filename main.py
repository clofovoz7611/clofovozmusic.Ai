import os
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./local.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    plan = Column(String, default="standard")

Base.metadata.create_all(bind=engine)

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
