# CogniGen Backend

FastAPI backend for CogniGen, an adaptive RAG-based cognitive assessment platform. The backend handles authentication, document ingestion, book processing, retrieval, question generation, evaluation, and quiz workflows for the React frontend.

## Highlights

- Retrieval-augmented question generation from uploaded learning material.
- Multi-hop reasoning prompts for higher-order assessment questions.
- Evaluation module for answer quality and question validation.
- FastAPI service structure with schemas, models, auth, and database modules.
- Designed to pair with the `cognigen-frontend` React application.

## Tech Stack

- Python
- FastAPI
- SQLAlchemy
- RAG / LLM orchestration
- ChromaDB-style local retrieval store

## Run Locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Create a local `.env` file for secrets and API keys. Do not commit `.env`.
