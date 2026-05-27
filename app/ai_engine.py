import os
import json
import time
import random
import re
from groq import Groq
from .prompts import RAG_PROMPT_TEMPLATE
from dotenv import load_dotenv

load_dotenv()

client = Groq(
    api_key=os.environ.get("GROQ_API_KEY"),
)

BLOOMS_PROMPTS = {
    "Analysis": "Analyze the relationship between the concepts. Ask 'Why' or 'How'.",
    "Evaluation": "Present a scenario and ask the student to judge the best course of action.",
    "Creation": "Ask the student to predict an outcome or synthesize a solution."
}

def call_groq_json(messages, model="llama-3.3-70b-versatile", temperature=0.2):
    max_retries = 3
    base_delay = 2

    for attempt in range(max_retries):
        try:
            chat_completion = client.chat.completions.create(
                messages=messages,
                model=model,
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            response_content = chat_completion.choices[0].message.content
            return json.loads(response_content)
        except Exception as e:
            print(f"Groq Error (Attempt {attempt+1}): {e}")
            if "429" in str(e): 
                time.sleep(base_delay)
                base_delay *= 2
            else:
                if attempt == max_retries - 1:
                    return None
    return None

def clean_question_text(text):
    """Removes meta-references to 'Source A', 'Source B', or 'The text'."""
    if not text: return ""
    text = re.sub(r'(?i)(according to|based on|in) source [a-z]\s*,?', '', text)
    text = re.sub(r'(?i)source [a-z] (states|says|mentions)', 'the text states', text)
 
    text = text.strip()
    if text:
        text = text[0].upper() + text[1:]
    return text

def get_type_instructions(question_type):
    """Returns specific formatting instructions based on the question type."""
    if question_type == "Multiple-Answer":
        return """
        CRITICAL: This is a MULTIPLE RESPONSE question.
        1. There MUST be at least TWO correct options.
        2. Output 'answer' as a LIST of keys (e.g., ["A", "C"]).
        3. 'options' must be a dictionary with at least 4 choices.
        """
    elif question_type == "Assertion-Reason":
        return """
        Format: 'Assertion: [Statement]. Reason: [Statement]'.
        'options' MUST be exactly:
        {"A": "Both A and R are true and R is the correct explanation of A",
         "B": "Both A and R are true but R is NOT the correct explanation of A",
         "C": "A is true but R is false",
         "D": "A is false but R is true"}
        """
    elif question_type in ["Short Answer", "Long Answer"]:
        return """
        CRITICAL: This is a text-based answer.
        1. Set "options" to null (do NOT provide choices).
        2. Set "answer" to the reference text solution.
        """
    else: 
        return "Standard single-select multiple choice. One correct answer key."

def generate_questions_from_rag(user_topic, retrieved_context, num_questions, question_type, hardness):
    prompt = RAG_PROMPT_TEMPLATE.format(
        num_questions=num_questions,
        user_topic=user_topic,
        hardness=hardness,
        retrieved_context=retrieved_context,
        question_type=question_type
    )
    
    messages = [
        {"role": "system", "content": "You are a helpful educational assistant that outputs strictly valid JSON."},
        {"role": "user", "content": prompt}
    ]
    
    result = call_groq_json(messages)
    if result:
        return result
    return {"error": "Failed to generate questions after retries."}

def generate_question_bloom(context_chunk, question_type, difficulty="Hard"):
    bloom_level = random.choice(["Analysis", "Evaluation", "Creation"])
    type_instr = get_type_instructions(question_type)
    
    prompt = f"""
    Generate ONE {difficulty} '{question_type}' Question.
    
    TARGET COGNITIVE LEVEL: {bloom_level} ({BLOOMS_PROMPTS.get(bloom_level)})
    
    STRICT FORMATTING RULES:
    {type_instr}
    
    CONTEXT:
    {context_chunk}
    
    OUTPUT FORMAT (JSON):
    {{
        "question": "The question text (Do not mention 'Source' or 'Text')",
        "options": {{"A": "...", "B": "..."}} (OR null if Short/Long Answer),
        "answer": "The correct key (or list of keys, or text)",
        "explanation": "Why this is correct",
        "cognitive_level": "{bloom_level}"
    }}
    """
    
    messages = [
        {"role": "system", "content": "You are an expert exam creator. Output valid JSON."},
        {"role": "user", "content": prompt}
    ]
    return call_groq_json(messages)

def generate_multihop_question(chunk_a, chunk_b, question_type):
    type_instr = get_type_instructions(question_type)
    
    prompt = f"""
    Create ONE HARD '{question_type}' question that requires Multi-Hop reasoning.
    
    SOURCE A:
    {chunk_a}
    
    SOURCE B:
    {chunk_b}
    
    INSTRUCTIONS:
    1. Identify a concept connecting Source A and Source B.
    2. formulate the question so it sounds natural. DO NOT use phrases like "According to Source A" or "In Source B". Just ask the question directly as if the student already knows the context.
    3. {type_instr}
    
    OUTPUT FORMAT (JSON):
    {{
        "question": "The question text (Clean, no meta-references)",
        "options": {{"A": "...", "B": "..."}} (OR null if Short/Long Answer),
        "answer": "The correct key (or list of keys, or text)",
        "explanation": "Explain the connection found."
    }}
    """
    
    messages = [
        {"role": "system", "content": "You are an expert exam creator. Output valid JSON."},
        {"role": "user", "content": prompt}
    ]
    return call_groq_json(messages)

def adversarial_review(question_data, context):
    if not question_data: return False

    q_text = question_data.get("question", "")
    correct_ans = question_data.get("answer", "")
    q_type = question_data.get("question_type", "Multiple-Choice")

    if q_type in ["Short Answer", "Long Answer"]:
        return True

    prompt = f"""
    You are a 'Critic AI'. Review this question for difficulty.
    
    QUESTION: {q_text}
    CORRECT ANSWER: {correct_ans}
    SOURCE TEXT: {context}
    
    TASK:
    Determine if this question is "Too Easy" (Extractive).
    - It is TOO EASY if the answer is a direct copy-paste or simple keyword match.
    - It is GOOD if it requires logical reasoning, synthesis, or inference.
    
    Output JSON:
    {{
        "is_too_easy": true/false,
        "reason": "Brief reason"
    }}
    """
    
    messages = [{"role": "user", "content": prompt}]
    result = call_groq_json(messages, temperature=0.0) 
    
    if result and result.get("is_too_easy") is True:
        return False 
    return True


def generate_hard_questions_pipeline(retrieved_docs, retrieved_metas, num_questions=3, question_type="Multiple-Choice"):
    """
    Master pipeline that orchestrates Multi-hop, Bloom's, and Adversarial checks.
    NOW ACCEPTS METADATA to track dual sources.
    """
    final_questions = []

    combined_data = list(zip(retrieved_docs, retrieved_metas))
    
    if len(combined_data) > 1:
        random.shuffle(combined_data)

    shuffled_docs, shuffled_metas = zip(*combined_data)
    shuffled_docs = list(shuffled_docs)
    shuffled_metas = list(shuffled_metas)
    
    attempts = 0

    while len(final_questions) < num_questions and attempts < (num_questions * 4):
        attempts += 1
        
        can_do_multihop = len(shuffled_docs) >= 2 and question_type not in ["Assertion-Reason"]
        is_multihop = random.choice([True, False]) if can_do_multihop else False
        
        question_data = None
        used_context = ""
        sources_info = []
        
        if is_multihop:
            idx_a = attempts % len(shuffled_docs)
            idx_b = (attempts + 1) % len(shuffled_docs)
            
            chunk_a = shuffled_docs[idx_a]
            chunk_b = shuffled_docs[idx_b]
            meta_a = shuffled_metas[idx_a]
            meta_b = shuffled_metas[idx_b]
            
            question_data = generate_multihop_question(chunk_a, chunk_b, question_type)
            used_context = chunk_a + "\n" + chunk_b
            type_label = "Multi-Hop"

            sources_info = [meta_a, meta_b]
            
        else:
            idx = attempts % len(shuffled_docs)
            chunk = shuffled_docs[idx]
            meta = shuffled_metas[idx]
            
            question_data = generate_question_bloom(chunk, question_type, difficulty="Hard")
            used_context = chunk
            type_label = "Deep-Reasoning"

            sources_info = [meta]
            
        if not question_data: 
            continue

        if "question" in question_data:
            question_data["question"] = clean_question_text(question_data["question"])

        if question_type in ["Short Answer", "Long Answer"]:
            question_data["options"] = None

        if question_type == "Multiple-Answer":
            ans = question_data.get("answer")
            if not isinstance(ans, list):
                if isinstance(ans, str) and "," in ans:
                    question_data["answer"] = [k.strip() for k in ans.split(",")]
                elif isinstance(ans, str):
                    question_data["answer"] = [ans]

        question_data["question_type"] = question_type
        question_data["hardness"] = "Hard"

        question_data["source_metadata"] = sources_info

        source_texts = []
        for i, m in enumerate(sources_info):
            src_label = f"Source {i+1}" if len(sources_info) > 1 else "Source"
            source_texts.append(f"{src_label}: Ch {m.get('chapter', '?')} Pg {m.get('book_page', '?')}")
        question_data["source_ref_text"] = " | ".join(source_texts)

        if adversarial_review(question_data, used_context):
            question_data["ai_tags"] = [type_label, question_data.get("cognitive_level", "Synthesis")]
            final_questions.append(question_data)
            print(f"Accepted Hard Question ({type_label})")
        else:
            print(f"Skipped question: Too easy/extractive.")

    return final_questions


def grade_answer(question, reference_answer, student_answer):
    if not student_answer or len(student_answer.strip()) < 2:
        return 0

    prompt = f"""
    You are a strict teacher grading a quiz.
    
    Question: "{question}"
    Correct Answer (Reference): "{reference_answer}"
    Student Answer: "{student_answer}"
    
    Task: Compare the Student Answer to the Reference.
    - If the student's answer conveys the correct meaning (even if worded differently), return 1.
    - If it is wrong or irrelevant, return 0.
    
    Output strictly a single number: 1 or 0.
    """

    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0, 
            max_tokens=5
        )
        score_text = chat_completion.choices[0].message.content.strip()
        return 1 if "1" in score_text else 0
    except:
        return 0