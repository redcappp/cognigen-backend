import time
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from . import models, schemas, ai_engine, auth
from .database import SessionLocal, engine
from .prompts import PROMPT_TEMPLATES
from fastapi.middleware.cors import CORSMiddleware

from fastapi import UploadFile, File, Form
from . import book_processor

from typing import List

models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="CogniGen API", version="1.0")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# --- SECURITY CLEARANCE (CORS) ---
# For now, we allow '*' (everything) so the deployment doesn't block your frontend.
# Once your frontend is live, we will lock this down to just your Vercel URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ... rest of your backend routes go below here
# --- Dependencies ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = schemas.TokenData(email=email)
    except JWTError:
        raise credentials_exception
    user = db.query(models.User).filter(models.User.email == token_data.email).first()
    if user is None:
        raise credentials_exception
    return user

# --- API Endpoints ---
@app.post("/api/v1/signup", response_model=schemas.UserDisplay)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed_password = auth.get_password_hash(user.password)
    new_user = models.User(email=user.email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = auth.create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/api/v1/books/upload")
async def upload_book(
    book_name: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Endpoint to upload a book, create a record, and start processing.
    """
    if not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a .zip file.")

    # Create book record in database
    new_book = models.Book(user_id=current_user.id, book_name=book_name, status="processing")
    db.add(new_book)
    db.commit()
    db.refresh(new_book)
    
    # Process the book
    file_content = await file.read()
    final_status = book_processor.process_book(file_content, new_book.id)
    
    # Update status after processing
    new_book.status = final_status
    db.commit()
    
    return {"filename": file.filename, "book_id": new_book.id, "status": final_status}

# Add a new endpoint to get a list of books
@app.get("/api/v1/books", response_model=List[schemas.BookDisplay]) # You'll need to create BookDisplay schema
async def get_user_books(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return db.query(models.Book).filter(models.Book.user_id == current_user.id).all()



@app.post("/api/v1/chat")
async def chat_with_books(
    request: schemas.ChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # 1. Embed the user's question
    query_embedding = book_processor.embeddings.embed_query(request.message)
    
    # 2. Retrieve relevant chunks (Top 5 is usually enough for an answer)
    retrieved_docs = book_processor.chroma_collection.query(
        query_embeddings=[query_embedding],
        n_results=5,
        where={"book_id": {"$in": [str(bid) for bid in request.book_ids]}}
    )
    
    # 3. Format context
    documents = retrieved_docs['documents'][0]
    metadatas = retrieved_docs['metadatas'][0]
    
    context_text = ""
    for i, doc in enumerate(documents):
        meta = metadatas[i]
        context_text += f"Source (Chapter {meta.get('chapter')}, Page {meta.get('book_page')}):\n{doc}\n---\n"
        
    # 4. Get Answer
    answer = ai_engine.chat_with_book(request.message, context_text)
    
    return {"response": answer}

# ... imports ...

# 1. CREATE QUIZ (Teacher clicks "Conduct Quiz")
@app.post("/api/v1/quizzes", response_model=schemas.QuizDisplay)
def create_quiz(
    quiz_data: schemas.QuizCreate, 
    db: Session = Depends(get_db), 
    current_user: models.User = Depends(get_current_user)
):
    new_quiz = models.Quiz(
        user_id=current_user.id,
        title=quiz_data.title,
        questions_data=quiz_data.questions
    )
    db.add(new_quiz)
    db.commit()
    db.refresh(new_quiz)
    return new_quiz

# 2. GET QUIZ (Student opens the link - No Auth needed!)
@app.get("/api/v1/quizzes/{quiz_id}")
def get_quiz_for_student(quiz_id: int, db: Session = Depends(get_db)):
    quiz = db.query(models.Quiz).filter(models.Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    # We return the questions. 
    # NOTE: In a real production app, you might want to hide the 'answer' field here 
    # so students can't cheat by inspecting the network tab. 
    # For this prototype, sending the full object is fine.
    return {"title": quiz.title, "questions": quiz.questions_data}

# 3. SUBMIT QUIZ (Student submits answers)

# 4. GET RESULTS (Teacher views leaderboard)
@app.get("/api/v1/quizzes/{quiz_id}/results", response_model=List[schemas.ResultDisplay])
def get_quiz_results(
    quiz_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Verify the user owns this quiz
    quiz = db.query(models.Quiz).filter(models.Quiz.id == quiz_id, models.Quiz.user_id == current_user.id).first()
    if not quiz:
        raise HTTPException(status_code=403, detail="Not authorized to view these results")
    
    return quiz.responses


# ... inside main.py ...

# ... inside main.py ...

# main.py

@app.post("/api/v1/generate-questions-from-book")
async def generate_questions_from_book(
    request: schemas.BookQuestionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # 1. Retrieve source documents
    
    # 1. Retrieve source documents using Pinecone Similarity Search
    # Pinecone/LangChain handles the embedding step for us implicitly during search
    filter_dict = {"book_id": {"$in": [str(bid) for bid in request.book_ids]}}
    
    raw_docs = book_processor.vectorstore.similarity_search(
        query=request.context, 
        k=10, 
        filter=filter_dict
    )
    
    # Restructure back into the format your existing pipeline expects
    documents = [doc.page_content for doc in raw_docs]
    metadatas = [doc.metadata for doc in raw_docs]
    
    final_questions_list = []

    # 2. Iterate through each configuration group
    for config in request.configs:
        print(f"Processing config: {config.num_questions} {config.hardness} {config.question_type}")
        
        # --- FIXED HARD PIPELINE CALL ---
        if config.hardness == "Hard":
            print(f">>> Triggering Advanced Hard Pipeline ({config.question_type})")
            
            # PASS 'metadatas' HERE
            hard_qs = ai_engine.generate_hard_questions_pipeline(
                retrieved_docs=documents,
                retrieved_metas=metadatas,   # <--- NEW ARGUMENT
                num_questions=config.num_questions,
                question_type=config.question_type
            )
            
            # Inject Book Name (Database Lookup)
            for q in hard_qs:
                # The 'source_metadata' field now holds the specific page info from the pipeline
                # We just need to resolve the Book Name
                
                # Take the first source to find the Book ID (usually they are from the same book in this flow)
                first_meta = q.get("source_metadata", [{}])[0]
                book_id = first_meta.get('book_id')
                
                book_name = "Unknown Book"
                if book_id:
                    book = db.query(models.Book).filter(models.Book.id == int(book_id)).first()
                    if book: book_name = book.book_name
                
                q["source_book_name"] = book_name
                
                # Map internal fields to what your Frontend expects
                # If it's multi-hop, 'source_book_page' can show the combined string we made
                q["source_book_page"] = q.get("source_ref_text", "See details")

            final_questions_list.extend(hard_qs)

        # --- EXISTING STRATEGY A: Easy/Medium ---
        else:
            mid_point = len(documents) // 2
            batches = [
                (documents[:mid_point], metadatas[:mid_point]),
                (documents[mid_point:], metadatas[mid_point:])
            ]
            
            qs_for_batch_1 = -(-config.num_questions // 2)
            qs_for_batch_2 = config.num_questions - qs_for_batch_1
            questions_counts = [qs_for_batch_1, qs_for_batch_2]

            for i, (batch_docs, batch_metas) in enumerate(batches):
                if questions_counts[i] <= 0: continue

                batch_context = ""
                for j, doc in enumerate(batch_docs):
                    meta = batch_metas[j]
                    batch_context += f"Source {j+1} (Chapter {meta.get('chapter')}, Page {meta.get('book_page')}):\n{doc}\n---\n"

                if i > 0 or len(final_questions_list) > 0: 
                    time.sleep(1)

                ai_response = ai_engine.generate_questions_from_rag(
                    user_topic=request.context,
                    retrieved_context=batch_context,
                    num_questions=questions_counts[i],
                    question_type=config.question_type,
                    hardness=config.hardness
                )
                
                if "questions" in ai_response:
                    for q in ai_response["questions"]:
                        if "source_book_page" not in q or q["source_book_page"] == "N/A":
                            q["source_chapter"] = batch_metas[0].get('chapter', 'Unknown')
                            q["source_book_page"] = batch_metas[0].get('book_page', 'Unknown')
                        
                        book_name = "Unknown Book"
                        book_id = batch_metas[0].get('book_id')
                        if book_id:
                            book = db.query(models.Book).filter(models.Book.id == int(book_id)).first()
                            if book: book_name = book.book_name
                        q["source_book_name"] = book_name

                    final_questions_list.extend(ai_response["questions"])

    return {"questions": final_questions_list}

# ... inside main.py ...

# 5. GET TEACHER'S QUIZZES
@app.get("/api/v1/my-quizzes", response_model=List[schemas.QuizDisplay])
def get_my_quizzes(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    return db.query(models.Quiz).filter(models.Quiz.user_id == current_user.id).order_by(models.Quiz.created_at.desc()).all()


# In main.py, replace the submit_quiz function with this:

@app.post("/api/v1/quizzes/{quiz_id}/submit")
def submit_quiz(
    quiz_id: int, 
    submission: schemas.StudentSubmit, 
    db: Session = Depends(get_db)
):
    quiz = db.query(models.Quiz).filter(models.Quiz.id == quiz_id).first()
    if not quiz: raise HTTPException(status_code=404, detail="Quiz not found")

    questions = quiz.questions_data
    total_score = 0
    graded_answers = {}

    print(f"--- Processing Submission for Quiz {quiz_id} ---")
    
    # Helper 1: Clean text (remove case/dots)
    def clean_text(text):
        return str(text).strip().rstrip('.').lower()

    # Helper 2: Normalize Keys (e.g., "A.", "a)", "A " -> "A")
    def normalize_key(k):
        return str(k).strip().upper().replace('.', '').replace(')', '')

    for idx, q in enumerate(questions):
        idx_str = str(idx) 
        student_ans = submission.answers.get(idx_str, "")
        
        final_stored_answer = student_ans 
        points = 0
        is_correct = False
        
        correct_raw = str(q.get('answer', ''))
        
        # 'options' comes as a Dictionary {"A": "Text", "B": "Text"}
        options_data = q.get('options') or q.get('choices')
        q_type = q.get('question_type', 'Unknown')

        if student_ans:
            print(f"Checking Q{idx} [{q_type}]: Student Input='{student_ans}' Correct='{correct_raw}'")

            # --- LOGIC 1: MULTIPLE ANSWER ---
            # Trigger if type says 'Multiple-Answer' OR if student sent a list
            if (q_type == "Multiple-Answer" or isinstance(student_ans, list)):
                # Ensure student_ans is a list
                if not isinstance(student_ans, list):
                    student_ans = [student_ans]

                # Normalize everything to Sets of Keys {"A", "B"}
                correct_keys = set(normalize_key(k) for k in correct_raw.split(','))
                student_keys = set(normalize_key(k) for k in student_ans)
                
                # Generate Readable Answer String
                selected_texts = []
                if isinstance(options_data, dict):
                    for k in student_ans:
                        norm_k = normalize_key(k)
                        # Try finding by raw key or normalized key
                        val = options_data.get(k) or options_data.get(norm_k)
                        if val: selected_texts.append(str(val))
                if selected_texts:
                    final_stored_answer = ", ".join(selected_texts)

                # Strict Comparison
                if student_keys == correct_keys:
                    points = 1
                    is_correct = True

            # --- LOGIC 2: SINGLE CHOICE / ASSERTION ---
            # Trigger if MC/Assertion OR if correct answer is a single letter like "A"
            elif (q_type in ["Multiple-Choice", "Assertion-Reason"]) or (len(normalize_key(correct_raw)) == 1 and normalize_key(correct_raw).isalpha()):
                
                norm_student = normalize_key(student_ans)
                norm_correct = normalize_key(correct_raw)

                # 1. Direct Key Comparison ("A" == "A")
                if norm_student == norm_correct:
                    points = 1
                    is_correct = True
                
                # 2. Text Fallback (Did they send "Modularity" instead of "A"?)
                if not is_correct and isinstance(options_data, dict):
                    correct_text = options_data.get(norm_correct)
                    # Check if student answer matches the text of the correct option
                    if correct_text and clean_text(student_ans) == clean_text(correct_text):
                        points = 1
                        is_correct = True
                        
                # Store readable text
                if isinstance(options_data, dict):
                    val = options_data.get(student_ans) or options_data.get(norm_student)
                    if val: final_stored_answer = val

            # --- LOGIC 3: OPEN TEXT ---
            else:
                points = ai_engine.grade_answer(q.get('question'), correct_raw, str(student_ans))
                if points >= 1: is_correct = True

        total_score += points
        
        graded_answers[idx_str] = {
            "answer": final_stored_answer, 
            "points": points,
            "is_correct": is_correct
        }
    
    new_response = models.QuizResponse(
        quiz_id=quiz_id,
        student_name=submission.student_name,
        score=total_score,
        total_questions=len(questions),
        answers_data=graded_answers 
    )
    db.add(new_response)
    db.commit()
    
    return {"message": "Submitted", "score": total_score}



@app.patch("/api/v1/quiz-responses/{response_id}/score")
def update_quiz_score(
    response_id: int, 
    update: schemas.ScoreUpdate, # <--- Use the schema prefix
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # ... logic ...
    # Fetch response
    response = db.query(models.QuizResponse).filter(models.QuizResponse.id == response_id).first()
    if not response: raise HTTPException(status_code=404, detail="Response not found")
    
    # Verify ownership (via Quiz relationship)
    quiz = db.query(models.Quiz).filter(models.Quiz.id == response.quiz_id).first()
    if quiz.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Update Score
    response.score = update.new_score
    db.commit()
    return {"message": "Score updated", "new_score": response.score}