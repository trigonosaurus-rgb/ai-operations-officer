# main.py
from fastapi import FastAPI
from pydantic import BaseModel
from core.agent import create_logistics_agent

# Initialize FastAPI application
app = FastAPI(
    title="Logistics AI Agent API",
    description="An AI agent combining SQL operational data with RAG knowledge base.",
    version="1.0.0"
)

# Initialize the agent once when the server starts
logistics_agent = create_logistics_agent()

# Define the expected JSON payload format
class UserQuery(BaseModel):
    query: str

@app.get("/")
def read_root():
    return {"status": "AI Agent Server is running"}

@app.post("/ask_agent")
def ask_agent(user_query: UserQuery):
    try:
        response = logistics_agent.chat(user_query.query)
        
        # 1. Extract and format sources
        sources = []
        
        # Check for RAG source nodes (PDF files)
        if hasattr(response, 'source_nodes'):
            for node in response.source_nodes:
                file_name = node.metadata.get("file_name", "Unknown Document")
                page = node.metadata.get("page_label", "N/A")
                source_str = f"📄 {file_name} (Page {page})"
                if source_str not in sources:
                    sources.append(source_str)
        
        # Check for specific Tool usage (SQL or Calendar)
        for source in response.sources:
            if source.tool_name == "operational_database":
                sources.append("🗄️ SQL Database (Operational Data)")
            elif source.tool_name == "get_current_date":
                sources.append("📅 System Calendar")

        return {
            "answer": str(response),
            "sources": sources
        }

    except Exception as e:
        return {"error": str(e)}
    
@app.post("/clear_memory")
def clear_memory():
    """
    Endpoint to reset the agent's conversational memory.
    Useful when starting a new chat session from the frontend.
    """
    try:
        logistics_agent.memory.reset()
        return {"status": "Memory cleared successfully"}
    except Exception as e:
        return {"error": str(e)}

# To run this server, you would type in the terminal:
# uvicorn main:app --reload