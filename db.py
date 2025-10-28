import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def init_db():
    return await asyncpg.create_pool(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")      
    )