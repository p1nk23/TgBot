import asyncio
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from dotenv import load_dotenv
import os
import logging
from db import init_db
from handlers import register_handlers

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))

    # Используем RedisStorage для продакшена или MemoryStorage для разработки
    storage = RedisStorage.from_url(os.getenv("REDIS_URL", "redis://localhost:6379")) if os.getenv("REDIS_URL") else MemoryStorage()
    dp = Dispatcher(storage=storage)

    try:
        pool = await init_db()
        dp["db_pool"] = pool
    except Exception as e:
        logger.error(f"Не удалось инициализировать базу данных: {e}")
        return

    await bot.set_my_commands([
    BotCommand(command="/start", description="Начать работу"),
    BotCommand(command="/ls", description="Показать содержимое текущей папки"),
    BotCommand(command="/cd", description="Перейти в папку по ID"),
    BotCommand(command="/root", description="Вернуться в корень"),
    BotCommand(command="/add", description="Добавить узел"),
    BotCommand(command="/rm", description="Удалить узел по ID"),
    BotCommand(command="/edit", description="Изменить текст узла"),
    BotCommand(command="/search", description="Поиск по заметкам"),
    BotCommand(command="/menu", description="Показать меню действий"),
])

    register_handlers(dp)

    # Регистрируем обработчик ошибок
    dp.errors.register(error_handler)

    try:
        logger.info("Бот запущен")
        await dp.start_polling(bot)
    finally:
        await pool.close()

# Глобальный обработчик ошибок
async def error_handler(update, exception):
    logger.error(f"Произошла ошибка: {exception}")
    # Здесь можно отправить сообщение пользователю об ошибке
    if hasattr(update, 'message') and update.message:
        await update.message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

if __name__ == "__main__":
    asyncio.run(main())