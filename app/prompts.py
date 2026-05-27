PROMPT_TEMPLATES = {
    "Multiple-Choice": """
    You are an expert in creating educational assessment materials. 
    Based on the context provided, generate exactly {num_questions} high-quality multiple-choice questions (MCQs).
    Your response MUST be a valid JSON object containing a single key "questions", which is a list of question objects.
    Each object in the list must have the following exact keys: "question", "options", "answer", "source".
    - "question": The question text.
    - "options": A dictionary where keys are "A", "B", "C", "D" and values are the option texts.
    - "answer": The key of the correct option (e.g., "C").
    - "source": The exact sentence from the provided context that justifies the answer.
    Context:
    ---
    {context}
    ---
    """,
    "Fill in the Blanks": """
    You are an expert in creating educational assessment materials.
    Based on the context provided, generate exactly {num_questions} fill-in-the-blank questions.
    Your response MUST be a valid JSON object containing a single key "questions", which is a list of question objects.
    Each object in the list must have the following exact keys: "question_sentence", "answer_word", "source".
    - "question_sentence": The sentence with a blank represented by '___'.
    - "answer_word": The exact word or short phrase that fits in the blank.
    - "source": The original, complete sentence from the provided context.
    Context:
    ---
    {context}
    ---
    """,
    "Short Answer": """
    You are an expert in creating educational assessment materials.
    Based on the context provided, generate exactly {num_questions} short-answer questions that require a concise, factual answer.
    Your response MUST be a valid JSON object containing a single key "questions", which is a list of question objects.
    Each object in the list must have the following exact keys: "question", "answer", "source".
    - "question": The question text.
    - "answer": A concise, accurate answer (typically 1-2 sentences).
    - "source": The exact sentence(s) from the context that contain the answer.
    Context:
    ---
    {context}
    ---
    """,
    "Long Answer": """
    You are an expert in creating educational assessment materials.
    Based on the context provided, generate exactly {num_questions} open-ended, long-answer questions that require synthesizing information from the text.
    Your response MUST be a valid JSON object containing a single key "questions", which is a list of question objects.
    Each object in the list must have the following exact keys: "question", "model_answer", "sources".
    - "question": The open-ended question that prompts for analysis or synthesis.
    - "model_answer": A detailed model answer in a paragraph format.
    - "sources": A list of the multiple sentences or paragraphs from the original text that support the model answer.
    Context:
    ---
    {context}
    ---
    """
}

# --- RAG PROMPT TEMPLATE (UPDATED FOR ALL TYPES) ---
RAG_PROMPT_TEMPLATE = """
You are an expert question-generation assistant. Your task is to generate exactly {num_questions} questions based on the user's topic and the provided source text chunks.

**User's Topic:** "{user_topic}"
**Hardness Level:** "{hardness}"
**Question Type:** "{question_type}"

**Provided Sources:**
---
{retrieved_context}
---

**CRITICAL INSTRUCTIONS:**
1.  Generate exactly {num_questions} questions.
2.  **Distribute questions evenly** across the different source chunks.
3.  **Strict JSON Output:** Your response must be a single, valid JSON object with a "questions" key. 

**FORMATTING RULES BY TYPE:**

**1. If Question Type is "Multiple-Choice":**
   - Provide "question", "options" (keys A, B, C, D), "answer" (single key like "B"), and "source_text".

**2. If Question Type is "Multiple-Answer" (Checkbox):**
   - Provide "question" (e.g., "Select ALL correct statements...").
   - Provide "options" (keys A, B, C, D, E).
   - **"answer":** MUST be a comma-separated string of correct keys (e.g., "A, C" or "B, D, E").
   - Ensure there are at least 2 correct options.
   - Include "source_text".

**3. If Question Type is "Assertion-Reason":**
   - **"question":** Format as "Assertion: [Statement]\nReason: [Statement]".
   - **"options":** You MUST use exactly these standard options:
     A: Both A and R are true and R is the correct explanation of A.
     B: Both A and R are true but R is NOT the correct explanation of A.
     C: A is true but R is false.
     D: A is false but R is true.
   - **"answer":** The single correct key (e.g., "A").
   - Include "source_text".

**4. If Question Type is "Short Answer" or "Long Answer":**
   - Provide "question", "answer" (the text answer), and "source_text". No options.

**Generic Output Schema (for every object):**
{{
  "question": "string",
  "options": {{ "A": "...", "B": "..." }},  // (Only for MCQs/Assertion/Multiple-Answer)
  "answer": "string",
  "source_chapter": "string",
  "source_book_page": "string",
  "source_text": "string" 
}}
"""