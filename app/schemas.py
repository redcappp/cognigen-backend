from pydantic import BaseModel, EmailStr
from typing import List, Dict, Any, Optional
from datetime import datetime  # Import the class directly


# --- User & Auth Schemas ---
class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserDisplay(BaseModel):
    id: int
    email: EmailStr
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

# --- Book Schemas ---
class BookDisplay(BaseModel):
    """
    Schema for displaying book information to the user.
    """
    id: int
    book_name: str
    status: str
    created_at: datetime  # Correct usage

    class Config:
        from_attributes = True

# --- Question Generation Schemas ---
class QuestionConfig(BaseModel):
    question_type: str
    hardness: str
    num_questions: int

class BookQuestionRequest(BaseModel):
    context: str
    book_ids: List[int]
    configs: List[QuestionConfig]

class QuestionResponse(BaseModel):
    questions: List[Dict[str, Any]]
    class Config:
        from_attributes = True

# --- Chat Schemas ---
class ChatRequest(BaseModel):
    message: str
    book_ids: List[int]

# --- Quiz & Results Schemas ---
class QuizCreate(BaseModel):
    title: str
    questions: List[dict] # The list of generated questions

# ... inside schemas.py ...

class QuizDisplay(BaseModel):
    id: int
    title: str
    created_at: datetime
    
    # --- ADD THIS LINE ---
    questions_data: List[dict] 
    
    class Config:
        from_attributes = True

class StudentSubmit(BaseModel):
    student_name: str
    answers: Dict[str, Any] # Question Index -> Selected Option/Text

# ... (rest of the file is fine) ...

class ResultDisplay(BaseModel):
    student_name: str
    score: int
    total_questions: int
    submitted_at: datetime
    
    # --- ADD THIS LINE ---
    answers_data: Optional[Dict[str, Any]] = None 
    
    class Config:
        from_attributes = True

class ScoreUpdate(BaseModel):
    new_score: int