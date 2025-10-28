import asyncio
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import os
from db import init_db
from handlers import register_handlers

load_dotenv()

async def main():
    bot = Bot(token=os.getenv("BOT_TOKEN"))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    pool = await init_db()
    dp["db_pool"] = pool

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

    try:
        await dp.start_polling(bot)
    finally:
        await pool.close()

if __name__ == "__main__":
    asyncio.run(main())