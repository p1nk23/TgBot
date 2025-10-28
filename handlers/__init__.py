from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from typing import Optional
import logging

router = Router()
logger = logging.getLogger(__name__)

async def get_children(pool, user_id: int, parent_id: Optional[int]):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, content FROM nodes WHERE user_id = $1 AND parent_id IS NOT DISTINCT FROM $2 ORDER BY id",
            user_id, parent_id
        )
        return rows

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.update_data(current_folder_id=None)
    await message.answer(
        "Привет! Ты в корневой папке.\n"
        "Используй /ls — чтобы посмотреть содержимое,\n"
        "/add <текст> — чтобы добавить узел,\n"
        "/cd <ID> — чтобы перейти в папку."
    )

@router.message(Command("ls"))
async def cmd_ls(message: Message, state: FSMContext, db_pool):
    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")  # None = корень

    user_id = message.from_user.id
    children = await get_children(db_pool, user_id, current_folder_id)

    if not children:
        await message.answer("📂 Папка пуста.")
        return

    text = "Содержимое:\n\n"
    buttons = []
    for row in children:
        text += f"📁 {row['id']}: {row['content']}\n"
        buttons.append(
            InlineKeyboardButton(text=f"{row['id']}: {row['content'][:20]}...", callback_data=f"cd_{row['id']}")
        )

    # Группируем кнопки по 1 в ряд
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[btn] for btn in buttons])
    await message.answer(text, reply_markup=keyboard)

@router.callback_query(F.data.startswith("cd_"))
async def cd_callback(callback: CallbackQuery, state: FSMContext, db_pool):
    try:
        folder_id = int(callback.data.split("_")[1])
    except (ValueError, IndexError):
        await callback.answer("Неверный ID папки.", show_alert=True)
        return

    # Проверим, что папка принадлежит пользователю
    user_id = callback.from_user.id
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM nodes WHERE id = $1 AND user_id = $2",
            folder_id, user_id
        )
    if not exists:
        await callback.answer("Папка не найдена или не принадлежит вам.", show_alert=True)
        return

    await state.update_data(current_folder_id=folder_id)
    await callback.message.edit_text(f"✅ Перешёл в папку {folder_id}. Используй /ls для просмотра.")
    await callback.answer()

@router.message(Command("cd"))
async def cmd_cd(message: Message, state: FSMContext, db_pool):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /cd <ID_папки>")
        return

    try:
        folder_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM nodes WHERE id = $1 AND user_id = $2",
            folder_id, user_id
        )
    if not exists:
        await message.answer("Папка не найдена или не принадлежит вам.")
        return

    await state.update_data(current_folder_id=folder_id)
    await message.answer(f"✅ Перешёл в папку {folder_id}. Используй /ls для просмотра.")



def register_handlers(dp):
    dp.include_router(router)