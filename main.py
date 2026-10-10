import os
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from jose import JWTError, jwt

# --- 1. SEGURIDAD Y HASHING NATIVO ---
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "clofovoz_music_super_secure_key_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def get_password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return f"{salt}${hashed}"

def verify_password(plain_password: str, stored_password: str) -> bool:
    try:
        salt, hashed = stored_password.split("$")
        return hashlib.sha256((salt + plain_password).encode('utf-8')).hexdigest() == hashed
    except Exception:
        return False

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
    engine = create_engine("sqlite:///./fallback.db")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()

# --- 3. MODELOS ---
class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=True)
    email = Column(String(150), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    plan = Column(String(50), default="free")
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

# --- 4. SCHEMAS ---
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

# --- 5. FASTAPI APP ---
app = FastAPI(title="Clofovoz Music SaaS API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# --- 6. ENDPOINTS ---
@app.get("/")
def root():
    return {"status": "Clofovoz Music SaaS activo", "version": "2.0.0", "env": "Render"}

@app.post("/api/auth/register", response_model=TokenSchema)
def register(req: RegistroSchema, db: Session = Depends(get_db)):
    try:
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
    except HTTPException:
        raise
    except Exception as err:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Error en base de datos: {str(err)}")

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

@app.get("/api/auth/me")
def get_me(current_user: Usuario = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "nombre": current_user.nombre,
        "email": current_user.email,
        "plan": current_user.plan,
        "created_at": current_user.created_at
    }

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

@app.get("/api/tracks")
def get_user_tracks(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tracks = db.query(AudioTrack).filter(AudioTrack.usuario_id == current_user.id).all()
    return [{"id": t.id, "titulo": t.titulo, "genero": t.genero, "created_at": t.created_at} for t in tracks]
