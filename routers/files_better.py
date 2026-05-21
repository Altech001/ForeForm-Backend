from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from db import get_db
from models.document import Document
from models.user import User
from schemas.document import DocumentCreate, DocumentUpdate, DocumentOut
from auth.jwt import get_current_user

router = APIRouter(prefix="/api/documents", tags=["Documents"])

@router.post("/", response_model=DocumentOut)
def create_document(doc_in: DocumentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    new_doc = Document(**doc_in.model_dump(), user_id=current_user.id)
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    return new_doc

@router.get("/", response_model=List[DocumentOut])
def get_documents(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    documents = db.query(Document).filter(Document.user_id == current_user.id).order_by(Document.created_at.desc()).all()
    return documents

@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    document = db.query(Document).filter(Document.id == document_id, Document.user_id == current_user.id).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document

@router.put("/{document_id}", response_model=DocumentOut)
def update_document(document_id: str, doc_in: DocumentUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    document = db.query(Document).filter(Document.id == document_id, Document.user_id == current_user.id).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    
    update_data = doc_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(document, field, value)
        
    db.commit()
    db.refresh(document)
    return document

@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    document = db.query(Document).filter(Document.id == document_id, Document.user_id == current_user.id).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    
    db.delete(document)
    db.commit()
    return {"message": "Document deleted"}
