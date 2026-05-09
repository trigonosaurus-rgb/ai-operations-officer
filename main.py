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
    """
    Endpoint to interact with the AI Agent.
    Takes a JSON body with the 'query' and returns the agent's answer.
    """
    try:
        # Pass the user query to our agent layer
        response = logistics_agent.chat(user_query.query)
        return {"answer": str(response)}
    
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