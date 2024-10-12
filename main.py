from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import List, Optional
from database import SessionLocal, engine, Base, get_db
from models import Contact, User as ContactModel
from schemas import ContactCreate, ContactUpdate, Contact as ContactSchema, UserCreate
from datetime import date, timedelta
from utils import hash_password, verify_password
from auth import create_access_token, verify_token

Base.metadata.create_all(bind=engine)

app = FastAPI()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

@app.post("/register/", response_model=ContactSchema)
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(ContactModel).filter(ContactModel.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=409, detail="User with this email already exists")
    hashed_password = hash_password(user.password)
    new_user = ContactModel(email=user.email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(ContactModel).filter(ContactModel.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
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

# Створення нового контакту
@app.post("/contacts/", response_model=ContactSchema)
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

# Пошук контактів
@app.get("/contacts/search/", response_model=List[ContactSchema])
def search_contacts(
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Contact)
    if first_name:
        query = query.filter(Contact.first_name.ilike(f"%{first_name}%"))
    if last_name:
        query = query.filter(Contact.last_name.ilike(f"%{last_name}%"))
    if email:
        query = query.filter(Contact.email.ilike(f"%{email}%"))
    
    return query.all()

# Отримання списку контактів з днями народження на найближчі 7 днів
@app.get("/contacts/birthdays/", response_model=List[ContactSchema])
def get_upcoming_birthdays(db: Session = Depends(get_db)):
    today = date.today()
    next_week = today + timedelta(days=7)
    return db.query(Contact).filter(Contact.birthday.between(today, next_week)).all()