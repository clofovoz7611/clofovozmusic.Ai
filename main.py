import os
import re
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from passlib.context import CryptContext
from jose import JWTError, jwt

# --- 1. SEGURIDAD Y JWT ---
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "clofovoz_music_super_secure_key_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 horas

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- 2. BASE DE DATOS POSTGRESQL ---
raw_url = os.environ.get("DATABASE_URL", "sqlite:///./local.db")
clean_url = raw_url.strip().strip("'").strip('"').strip()

if clean_url.startswith("postgres://"):
    clean_url = clean_url.replace("postgres://", "postgresql+psycopg2://", 1)
elif clean_url.startswith("postgresql://") and not clean_url.startswith("postgresql+psycopg2://"):
    clean_url = clean_url.replace("postgresql://", "postgresql+psycopg2://", 1)

try:
    engine = create_engine(clean_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
except Exception as e:
    print(f"Error conectando a DB: {e}")
    engine = create_engine("sqlite:///./fallback.db")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()

# --- 3. MODELOS SQLALCHEMY ---
class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=True)
    email = Column(String(150), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    plan = Column(String(50), default="free")  # free, creator, pro
    created_at = Column(DateTime, default=datetime.utcnow)
    
    tracks = relationship("AudioTrack", back_populates="propietario")

class AudioTrack(Base):
    __tablename__ = "audio_tracks"
    id = Column(Integer, primary_key=True, index=True)
    titulo = Column(String(200), nullable=False)
    genero = Column(String(50), nullable=True)
    descripcion = Column(Text, nullable=True)
    url_audio = Column(String(500), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    propietario = relationship("Usuario", back_populates="tracks")

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- 4. SCHEMAS PYDANTIC ---
class RegistroSchema(BaseModel):
    nombre: Optional[str] = None
    email: EmailStr
    password: str
    plan: Optional[str] = "free"

class LoginSchema(BaseModel):
    email: EmailStr
    password: str

class TokenSchema(BaseModel):
    access_token: str
    token_type: str
    usuario: dict

class TrackCreateSchema(BaseModel):
    titulo: str
    genero: Optional[str] = "General"
    descripcion: Optional[str] = None

# --- 5. APLICACIÓN FASTAPI & CORS ---
app = FastAPI(title="Clofovoz Music SaaS API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper para autenticar endpoints protegidos
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales de acceso no válidas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(Usuario).filter(Usuario.email == email).first()
    if user is None:
        raise credentials_exception
    return user

# --- 6. ENDPOINTS DEL SAAS ---

@app.get("/")
def root():
    return {"status": "Clofovoz Music SaaS activo", "version": "2.0.0", "env": "Render"}

# Registro con hash de contraseña seguro
@app.post("/api/auth/register", response_model=TokenSchema)
def register(req: RegistroSchema, db: Session = Depends(get_db)):
    existente = db.query(Usuario).filter(Usuario.email == req.email).first()
    if existente:
        raise HTTPException(status_code=400, detail="Este correo ya se encuentra registrado.")
    
    nuevo_usuario = Usuario(
        nombre=req.nombre,
        email=req.email,
        hashed_password=get_password_hash(req.password),
        plan=req.plan or "free"
    )
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    
    token = create_access_token(data={"sub": nuevo_usuario.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario": {
            "id": nuevo_usuario.id,
            "nombre": nuevo_usuario.nombre,
            "email": nuevo_usuario.email,
            "plan": nuevo_usuario.plan
        }
    }

# Login con entrega de Token JWT
@app.post("/api/auth/login", response_model=TokenSchema)
def login(req: LoginSchema, db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.email == req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos"
        )
    
    token = create_access_token(data={"sub": user.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario": {
            "id": user.id,
            "nombre": user.nombre,
            "email": user.email,
            "plan": user.plan
        }
    }

# Perfil del usuario autenticado
@app.get("/api/auth/me")
def get_me(current_user: Usuario = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "nombre": current_user.nombre,
        "email": current_user.email,
        "plan": current_user.plan,
        "created_at": current_user.created_at
    }

# Crear o subir pista/audio asociada al usuario
@app.post("/api/tracks")
def create_track(
    track_data: TrackCreateSchema,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    track = AudioTrack(
        titulo=track_data.titulo,
        genero=track_data.genero,
        descripcion=track_data.descripcion,
        usuario_id=current_user.id
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return {"mensaje": "Pista registrada con éxito", "track_id": track.id, "titulo": track.titulo}

# Listar pistas del usuario autenticado
@app.get("/api/tracks")
def get_user_tracks(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tracks = db.query(AudioTrack).filter(AudioTrack.usuario_id == current_user.id).all()
    return [{"id": t.id, "titulo": t.titulo, "genero": t.genero, "created_at": t.created_at} for t in tracks]
