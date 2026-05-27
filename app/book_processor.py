import zipfile
import io
import re
import os
import time  # Required for the sleep timer
import chromadb
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# Load environment variables
load_dotenv()

# Get the API key from the environment
google_api_key = os.getenv("GEMINI_API_KEY")

# Initialize ChromaDB client and collection
client = chromadb.PersistentClient(path="./chroma_db")
chroma_collection = client.get_or_create_collection("books_collection")

# Pass the API key directly when creating the embeddings model
# Using the new unified Gemini embedding model
embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001", 
    google_api_key=google_api_key
)

def process_book(file_content: bytes, book_id: int):
    try:
        temp_dir = f"/tmp/pdf_files_{book_id}"
        os.makedirs(temp_dir, exist_ok=True)

        page_offset = 0
        all_chunks = []
        chapter_number = 1 # Initialize chapter counter

        with zipfile.ZipFile(io.BytesIO(file_content)) as z:
            pdf_files = sorted([f for f in z.namelist() if f.lower().endswith('.pdf')])
            if not pdf_files:
                raise ValueError("No PDF files found in the zip archive.")

            for pdf_file_path in pdf_files:
                with z.open(pdf_file_path) as pdf_file:
                    filename = os.path.basename(pdf_file_path)
                    temp_pdf_path = os.path.join(temp_dir, filename)
                    with open(temp_pdf_path, "wb") as f:
                        f.write(pdf_file.read())
                    
                    loader = PyPDFLoader(temp_pdf_path)
                    docs = loader.load()
                    
                    # OPTIMIZATION: Increased chunk size to reduce the total number of API calls to Google
                    text_splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=300)
                    chunks = text_splitter.split_documents(docs)
                    
                    for doc in chunks:
                        book_page = doc.metadata.get("page", 0) + 1 + page_offset
                        doc.metadata["book_id"] = str(book_id)
                        doc.metadata["chapter"] = str(chapter_number) # Use chapter number
                        doc.metadata["book_page"] = str(book_page)
                    
                    all_chunks.extend(chunks)
                    os.remove(temp_pdf_path)
                
                page_offset += len(docs)
                chapter_number += 1 # Increment for next chapter

        print(f"Total chunks to process: {len(all_chunks)}")
        
        # --- BATCHING LOGIC FOR RATE LIMITS ---
        BATCH_SIZE = 10

        for i in range(0, len(all_chunks), BATCH_SIZE):
            batch = all_chunks[i : i + BATCH_SIZE]

            try:
                batch_texts = [chunk.page_content for chunk in batch]
                batch_metadatas = [chunk.metadata for chunk in batch]
                batch_ids = [f"{book_id}_{j}" for j in range(i, i + len(batch))]

                print(f"Embedding batch {i // BATCH_SIZE + 1}")

                batch_embeddings = embeddings.embed_documents(batch_texts)

                chroma_collection.add(
                    embeddings=batch_embeddings,
                    documents=batch_texts,
                    metadatas=batch_metadatas,
                    ids=batch_ids
                )

                print("Saved batch")

                time.sleep(5)  # small pause for free tier

            except Exception as e:
                if "429" in str(e):
                    print("Quota reached. Stopping embedding for now.")
                    break
                else:
                    print(f"Error: {e}")
                    break

        return "ready"
    
    except Exception as e:
        print(f"Error processing book {book_id}: {e}")
        return "failed"