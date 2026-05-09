# Logistics AI Agent: Operations Assistant

A professional AI-driven application designed to automate logistics operations. It combines Text-to-SQL (for querying operational databases) and RAG (Retrieval-Augmented Generation for PDF contracts) into a single, cohesive intelligent agent.

## Overview
This project features a dual-layer architecture:
1.  Backend (FastAPI): An AI Agent server that orchestrates data retrieval and reasoning.
2.  Frontend (Streamlit): A user-friendly chat interface for real-time interaction.

The agent can simultaneously check warehouse schedules in an SQL database and verify packaging requirements from PDF contracts to answer complex operational queries.

## Tech Stack
* LLM: OpenAI gpt-4o-mini (with store=True for optimized cost/testing).
* Orchestration: LlamaIndex (FunctionCallingAgent & SQL/Vector indices).
* Embeddings: HuggingFace (Local model: bge-small-en-v1.5) — zero-cost document processing.
* Database: SQLite (Relational data for schedules and pricing).
* API Framework: FastAPI (RESTful API).
* UI: Streamlit (Modern dashboard).

## Features
* Autonomous Routing: Automatically decides whether to query the SQL database or the RAG knowledge base.
* Conversational Memory: Remembers context throughout the session.
* Local Processing: Uses local embedding models to reduce API costs and improve privacy.
* Swagger Documentation: Fully documented API endpoints at /docs.

## Installation and Setup

1.  Clone the repository:
    ```bash
    git clone [https://github.com/trigonosaurus-rgb/ai-operations-officer.git](https://github.com/trigonosaurus-rgb/ai-operations-officer.git)
    cd ai-operations-officer
    ```

2.  Create and activate a virtual environment:
    ```bash
    python -m venv venv
    # On Windows:
    venv\Scripts\activate
    # On macOS/Linux:
    source venv/bin/activate
    ```

3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

4.  Configure environment variables:
    Create a .env file in the root directory:
    ```env
    OPENAI_API_KEY=your_openai_api_key_here
    ```

5.  Initialize the database:
    ```bash
    python scripts/setup_db.py
    ```

## Running the Application

You need to run two services simultaneously in separate terminals:

1. Start the Backend (API)
```bash
uvicorn main:app --reload