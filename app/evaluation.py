import os
from dotenv import load_dotenv # <-- ADD THIS LINE
load_dotenv()
import chromadb
from . import ai_engine
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from transformers import pipeline

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
# The PDF is in the SAME directory as the script
TEST_DOCUMENT_PATH = os.path.join(SCRIPT_DIR, "test_document.pdf")

TEST_QUERIES = [
    "string",
    "membership"
]
NUM_QUESTIONS_PER_QUERY = 2
import evaluate

# --- SETUP ---
# Load all necessary models and metrics once
print("--- Initializing Models ---")
google_api_key = os.getenv("GEMINI_API_KEY")
embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004", google_api_key=google_api_key)
qa_validator = pipeline("question-answering", model="distilbert-base-cased-distilled-squad")
squad_metric = evaluate.load("squad")
chroma_client = chromadb.Client()

def setup_test_collection(collection_name):
    """Indexes the test document into a fresh ChromaDB collection."""
    print(f"\n--- Setting up Test Collection: '{collection_name}' ---")
    
    # Delete collection if it exists to ensure a fresh start
    if collection_name in [c.name for c in chroma_client.list_collections()]:
        chroma_client.delete_collection(name=collection_name)
        
    collection = chroma_client.create_collection(name=collection_name)
    
    print(f"Loading and chunking document: {TEST_DOCUMENT_PATH}")
    loader = PyPDFLoader(TEST_DOCUMENT_PATH)
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = text_splitter.split_documents(docs)
    
    print(f"Indexing {len(chunks)} chunks into the vector store...")
    collection.add(
        embeddings=embeddings.embed_documents([chunk.page_content for chunk in chunks]),
        documents=[chunk.page_content for chunk in chunks],
        metadatas=[chunk.metadata for chunk in chunks],
        ids=[f"doc_{i}" for i in range(len(chunks))]
    )
    return collection

def evaluate_system(system_name, generation_function, **kwargs):
    """A generic function to evaluate a given question generation system."""
    print(f"\n--- Evaluating System: {system_name} ---")
    
    predictions, references = [], []
    
    for query in TEST_QUERIES:
        print(f"\nProcessing query: '{query}'")
        generated_data = generation_function(user_topic=query, **kwargs)
        
        if "error" in generated_data or "questions" not in generated_data:
            print(f"  - Failed to generate questions for this query.")
            continue
            
        for i, item in enumerate(generated_data["questions"]):
            gen_q = item["question"]
            gen_a = item["answer"]
            source_text = item.get("source_text", kwargs.get("full_context"))

            # Validate the answer against the source text
            validation_result = qa_validator(question=gen_q, context=source_text)
            validated_a = validation_result["answer"]
            
            print(f"  - Q: {gen_q}")
            print(f"    - Generated A: '{gen_a}'")
            print(f"    - Validated A: '{validated_a}'")

            predictions.append({'prediction_text': validated_a, 'id': f"{query}_{i}"})
            references.append({'answers': {'text': [gen_a], 'answer_start': [1]}, 'id': f"{query}_{i}"})

    if not predictions:
        print("No questions were generated to evaluate.")
        return None
        
    print("\n--- Calculating Final Scores ---")
    final_scores = squad_metric.compute(predictions=predictions, references=references)
    print(f"Results for {system_name}:")
    print(f"  - Average F1 Score: {final_scores['f1']:.2f}")
    print(f"  - Average Exact Match (EM): {final_scores['exact_match']:.2f}")
    return final_scores

def run_all_evaluations():
    # 1. Index the document for the RAG system
    rag_collection = setup_test_collection("rag_test_collection")

    # 2. Define the RAG generation logic
    def rag_generator(user_topic):
        retrieved_docs = rag_collection.query(
            query_embeddings=[embeddings.embed_query(user_topic)],
            n_results=5
        )
        documents = retrieved_docs['documents'][0]
        context_for_llm = "\n\n".join(documents)
        
        return ai_engine.generate_questions_from_rag(
            user_topic=user_topic,
            retrieved_context=context_for_llm,
            num_questions=NUM_QUESTIONS_PER_QUERY,
            question_type="Short Answer",
            hardness="Easy"
        )
    
    # 3. Define the Baseline generation logic
    full_text = " ".join([doc.page_content for doc in PyPDFLoader(TEST_DOCUMENT_PATH).load()])
    def baseline_generator(user_topic, **kwargs):
        return ai_engine.generate_questions_baseline(
            user_topic=user_topic,
            full_context=kwargs.get("full_context"), # Get full_context from kwargs
            num_questions=NUM_QUESTIONS_PER_QUERY
        )

    # 4. Run evaluations for both systems
    rag_scores = evaluate_system("CogniGen (RAG)", rag_generator)
    baseline_scores = evaluate_system("Baseline (No RAG)", baseline_generator, full_context=full_text)
    
    print("\n--- FINAL COMPARISON ---")
    if rag_scores:
        print(f"CogniGen (RAG):     F1 = {rag_scores['f1']:.2f}, EM = {rag_scores['exact_match']:.2f}")
    if baseline_scores:
        print(f"Baseline (No RAG):  F1 = {baseline_scores['f1']:.2f}, EM = {baseline_scores['exact_match']:.2f}")

if __name__ == "__main__":
    run_all_evaluations()