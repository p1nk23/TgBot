import asyncpg
import os
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger(__name__)

async def init_db():
    try:
        pool = await asyncpg.create_pool(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", 5432),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "postgres"),
            min_size=5,
            max_size=20,
            command_timeout=60
        )

        # Проверяем соединение
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")

        logger.info("База данных успешно подключена")
        return pool
    except Exception as e:
        logger.error(f"Ошибка подключения к базе данных: {e}")
        raise