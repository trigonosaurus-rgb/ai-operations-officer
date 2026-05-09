import os
from datetime import datetime
from llama_index.core.tools import FunctionTool
from dotenv import load_dotenv
from sqlalchemy import create_engine

from llama_index.core import SimpleDirectoryReader, VectorStoreIndex, SQLDatabase, Settings
from llama_index.core.query_engine import NLSQLTableQueryEngine
from llama_index.core.tools import QueryEngineTool, ToolMetadata
from llama_index.agent.openai import OpenAIAgent
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# Load environment variables
load_dotenv()

# Initialize LLM
llm = OpenAI(
    model="gpt-4o-mini",
    additional_kwargs={"store": True}
)
Settings.llm = llm


Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")

def create_logistics_agent():
    """Initializes and returns the ReAct Agent with SQL and RAG tools."""
    
    # 1. Initialize RAG Tool (Knowledge Base)
    documents = SimpleDirectoryReader(input_dir="data").load_data()
    vector_index = VectorStoreIndex.from_documents(documents)
    rag_query_engine = vector_index.as_query_engine()

    rag_tool = QueryEngineTool(
        query_engine=rag_query_engine,
        metadata=ToolMetadata(
            name="contract_knowledge_base",
            description=(
                "Useful for finding rules, legal terms, packaging guidelines, "
                "and instructions from the Baker Logistics contract. "
                "Use this tool for text-based policies and operational instructions."
            ),
        ),
    )

    # 2. Initialize SQL Tool (Operational Database)
    engine = create_engine("sqlite:///logistics_data.sqlite")
    sql_database = SQLDatabase(
        engine, 
        include_tables=["rdc_locations", "shipping_rates", "gate_schedule"]
    )
    
    sql_query_engine = NLSQLTableQueryEngine(
        sql_database=sql_database,
        tables=["rdc_locations", "shipping_rates", "gate_schedule"],
        llm=llm
    )

    sql_tool = QueryEngineTool(
        query_engine=sql_query_engine,
        metadata=ToolMetadata(
            name="operational_database",
            description=(
                "Useful for checking gate schedules (availability), "
                "shipping costs in USD, location addresses, and current inventory. "
                "The tables contain precise operational data."
            ),
        ),
    )


    def get_current_date() -> str:
        """Returns the current real-world date and time. Use this to validate dates and resolve relative time like 'tomorrow'."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    calendar_tool = FunctionTool.from_defaults(fn=get_current_date)

    # 3. Create and return the Agent
    agent = OpenAIAgent.from_tools(
        tools=[rag_tool, sql_tool, calendar_tool],
        llm=llm,
        system_prompt=(
            "You are a strict logistics assistant. "
            "1. ALWAYS validate user dates against the calendar tool. Reject non-existent dates. "
            "2. If the SQL database returns an empty result for a specific date, you MUST explicitly state that there are no scheduled operations or flights for that date. Do not invent availability."
        ),
        verbose=True
    )
    
    return agent

# --- Only for direct testing of this layer ---
if __name__ == "__main__":
    agent = create_logistics_agent()
    test_query = (
        "Are the gates available tomorrow between 08:00 and 09:00 at Taft High School? "
        "How much does it cost to send a 5000 lb truck there? "
        "Also, remind me how nurses should return PCR tests according to the contract?"
    )
    response = agent.chat(test_query)
    print(response)