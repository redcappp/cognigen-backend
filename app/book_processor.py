import os
import zipfile
import io
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from pinecone import Pinecone
from langchain_pinecone import PineconeVectorStore

load_dotenv()

# Production-grade embedding engine (runs locally in RAM)
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# Connect to Pinecone Cloud
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
vectorstore = PineconeVectorStore(
    index_name=os.getenv("PINECONE_INDEX_NAME", "cognigen-index"),
    embedding=embeddings
)

def process_book(file_content: bytes, book_id: int):
    try:
        # Create temporary storage for processing
        temp_dir = f"/tmp/books_{book_id}"
        os.makedirs(temp_dir, exist_ok=True)

        all_chunks = []
        chapter_number = 1

        with zipfile.ZipFile(io.BytesIO(file_content)) as z:
            pdf_files = sorted([f for f in z.namelist() if f.lower().endswith('.pdf')])
            if not pdf_files:
                raise ValueError("No PDF files found.")

            for pdf_file_path in pdf_files:
                with z.open(pdf_file_path) as pdf_file:
                    temp_path = os.path.join(temp_dir, os.path.basename(pdf_file_path))
                    with open(temp_path, "wb") as f:
                        f.write(pdf_file.read())
                    
                    loader = PyPDFLoader(temp_path)
                    docs = loader.load()
                    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
                    chunks = text_splitter.split_documents(docs)
                    
                    for doc in chunks:
                        doc.metadata["book_id"] = str(book_id)
                        doc.metadata["chapter"] = str(chapter_number)
                    
                    all_chunks.extend(chunks)
                    os.remove(temp_path)
                chapter_number += 1

        # Production-grade Upsert to Vector Store
        vectorstore.add_documents(all_chunks)
        return "ready"
    
    except Exception as e:
        print(f"Deployment Error: {e}")
        return "failed"