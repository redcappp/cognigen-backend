from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Production engine with resilience against serverless connection drops
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,            # Auto-reconnect on dropped SSL
    pool_size=10,                  # Keeps 10 connections warm
    max_overflow=20,               # Burst handling
    connect_args={"sslmode": "require"}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()