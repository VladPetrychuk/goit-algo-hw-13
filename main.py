from fastapi import FastAPI, Depends, HTTPException, status, UploadFile
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import List, Optional
from database import SessionLocal, engine, Base, get_db
from models import Contact, User as ContactModel
from schemas import ContactCreate, ContactUpdate, Contact as ContactSchema, UserCreate
from datetime import date, timedelta
from utils import hash_password, verify_password
from auth import create_access_token, verify_token
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter.depends import RateLimiter
import cloudinary
import cloudinary.uploader
import os
from uuid import uuid4

Base.metadata.create_all(bind=engine)

app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Тут можна додати конкретні дозволені домени
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Налаштування Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# Верифікація електронної пошти
def send_verification_email(user_email, token):
    # Логіка відправки електронного листа з токеном для верифікації
    print(f"Відправлено лист на {user_email} з токеном: {token}")

@app.post("/register/", response_model=ContactSchema)
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(ContactModel).filter(ContactModel.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=409, detail="User with this email already exists")
    
    hashed_password = hash_password(user.password)
    new_user = ContactModel(email=user.email, hashed_password=hashed_password, verification_token=str(uuid4()))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Відправляємо токен для верифікації електронної пошти
    send_verification_email(new_user.email, new_user.verification_token)
    
    return new_user

@app.get("/verify-email/")
def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(ContactModel).filter(ContactModel.verification_token == token).first()
    if user:
        user.is_verified = True
        user.verification_token = None  # Очищаємо токен
        db.commit()
        return {"msg": "Email verified successfully"}
    raise HTTPException(status_code=400, detail="Invalid token")

@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(ContactModel).filter(ContactModel.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_verified:
        raise HTTPException(status_code=401, detail="Email not verified")
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    payload = verify_token(token)
    user_email = payload.get("sub")
    if not user_email:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(ContactModel).filter(ContactModel.email == user_email).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# Створення нового контакту з обмеженням швидкості
@app.post("/contacts/", response_model=ContactSchema, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
def create_contact(contact: ContactCreate, db: Session = Depends(get_db), current_user: ContactModel = Depends(get_current_user)):
    db_contact = Contact(**contact.dict(exclude_unset=True), owner_id=current_user.id)
    db.add(db_contact)
    db.commit()
    db.refresh(db_contact)
    return db_contact

# Отримання списку всіх контактів
@app.get("/contacts/", response_model=List[ContactSchema])
def get_contacts(db: Session = Depends(get_db)):
    return db.query(Contact).all()

# Отримання одного контакту за ідентифікатором
@app.get("/contacts/{contact_id}", response_model=ContactSchema)
def get_contact(contact_id: int, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact

# Оновлення існуючого контакту
@app.put("/contacts/{contact_id}", response_model=ContactSchema)
def update_contact(contact_id: int, contact: ContactUpdate, db: Session = Depends(get_db)):
    db_contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if db_contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    for key, value in contact.dict(exclude_unset=True).items():
        setattr(db_contact, key, value)
    
    db.commit()
    db.refresh(db_contact)
    return db_contact

# Видалення контакту
@app.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    db_contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if db_contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    
    db.delete(db_contact)
    db.commit()
    return {"ok": True}

# Завантаження аватара користувача
@app.put("/users/avatar/")
def update_avatar(file: UploadFile, db: Session = Depends(get_db), current_user: ContactModel = Depends(get_current_user)):
    result = cloudinary.uploader.upload(file.file, folder="avatars")
    current_user.avatar_url = result["url"]
    db.commit()
    return {"msg": "Avatar updated", "avatar_url": current_user.avatar_url}