import os
from dotenv import load_dotenv

load_dotenv()
api = os.getenv("OPENAI_API_KEY")