from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from typing import Optional
import logging

from handlers.states import EditNode

router = Router()
logger = logging.getLogger(__name__)

async def get_children(pool, user_id: int, parent_id: Optional[int]):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, content FROM nodes WHERE user_id = $1 AND parent_id IS NOT DISTINCT FROM $2 ORDER BY id",
            user_id, parent_id
        )
        return rows

async def create_node(pool, user_id: int, parent_id: Optional[int], content: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO nodes (user_id, parent_id, content) VALUES ($1, $2, $3) RETURNING id",
            user_id, parent_id, content
        )
        return row["id"]

async def delete_node(pool, user_id: int, node_id: int) -> bool:
    """
    Удаляет узел, если он принадлежит пользователю.
    Возвращает True, если удалён хотя бы один узел.
    """
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM nodes WHERE id = $1 AND user_id = $2",
            node_id, user_id
        )
        # execute возвращает строку вида "DELETE 1" или "DELETE 0"
        return "DELETE 0" not in result

async def update_node_content(pool, user_id: int, node_id: int, new_content: str) -> bool:
    """Обновляет content узла, если он принадлежит пользователю."""
    if not new_content.strip():
        return False  # пустой текст не разрешён
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE nodes SET content = $1 WHERE id = $2 AND user_id = $3",
            new_content.strip(), node_id, user_id
        )
        return "UPDATE 0" not in result

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.update_data(current_folder_id=None)
    await message.answer(
        "Привет! Ты в корневой папке.\n"
        "Используй /ls — чтобы посмотреть содержимое,\n"
        "/add <текст> — чтобы добавить узел,\n"
        "/cd <ID> — чтобы перейти в папку."
    )


@router.callback_query(F.data.startswith("rm_"))
async def rm_callback(callback: CallbackQuery, db_pool):
    try:
        node_id = int(callback.data[3:])
    except ValueError:
        await callback.answer("Неверный ID узла.", show_alert=True)
        return

    user_id = callback.from_user.id
    deleted = await delete_node(db_pool, user_id, node_id)

    if deleted:
        await callback.message.edit_text(f"✅ Узел {node_id} удалён.")
    else:
        await callback.answer("Узел не найден или не принадлежит вам.", show_alert=True)


@router.message(Command("ls"))
async def cmd_ls(message: Message, state: FSMContext, db_pool):
    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")

    user_id = message.from_user.id
    children = await get_children(db_pool, user_id, current_folder_id)

    if not children:
        text = "📂 Папка пуста."
        await message.answer(text)
        return

    text = "Содержимое:\n\n"
    buttons = []
    for row in children:
        text += f"📁 {row['id']}: {row['content']}\n"
        # Кнопки: "Открыть" и "Удалить"
        buttons.append([
            InlineKeyboardButton(text="📂 " + row['content'], callback_data=f"cd_{row['id']}"),
            InlineKeyboardButton(text="✏️", callback_data=f"edit_{row['id']}"),
            InlineKeyboardButton(text="🗑️", callback_data=f"rm_{row['id']}")
        ])

    # Кнопка "В корень", если не в корне
    if current_folder_id is not None:
        buttons.append([InlineKeyboardButton(text="↑ В корень", callback_data="cd_root")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)



# ВОЗВРАТ В КОРЕНЬ
@router.callback_query(F.data == "cd_root")
async def cd_to_root(callback: CallbackQuery, state: FSMContext):
    await state.update_data(current_folder_id=None)
    await callback.message.edit_text("📂 Вы вернулись в корневую папку.")
    await callback.answer()
@router.message(Command("root"))
async def cmd_root(message: Message, state: FSMContext):
    await state.update_data(current_folder_id=None)
    await message.answer("📂 Вы вернулись в корневую папку.")

#ПЕРЕМЕЩЕНИЕ ПО ПАПКАМ
@router.callback_query(F.data.startswith("cd_") & F.data.len() > 3)  # длина > "cd_" (3 символа)
async def cd_to_folder(callback: CallbackQuery, state: FSMContext, db_pool):
    try:
        folder_id = int(callback.data[3:])  # берём всё после "cd_"
    except ValueError:
        await callback.answer("Неверный ID папки.", show_alert=True)
        return

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
#ДОБАВЛЕНИЕ ПАПКИ
@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext, db_pool):
    # Извлекаем аргументы после команды
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /add <текст узла>")
        return

    content = args[1].strip()
    if not content:
        await message.answer("Текст не может быть пустым.")
        return

    user_id = message.from_user.id
    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")  # None = корень

    try:
        node_id = await create_node(db_pool, user_id, current_folder_id, content)
        await message.answer(f"✅ Узел создан! ID: {node_id}")
    except Exception as e:
        logger.exception("Ошибка при создании узла")
        await message.answer("❌ Не удалось создать узел. Попробуйте позже.")

#УДАЛЕНИЕ ПАПКИ
@router.message(Command("rm"))
async def cmd_rm(message: Message, db_pool):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /rm <ID_узла>")
        return

    try:
        node_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    user_id = message.from_user.id
    deleted = await delete_node(db_pool, user_id, node_id)

    if deleted:
        await message.answer(f"✅ Узел {node_id} и все его вложенные элементы удалены.")
    else:
        await message.answer("❌ Узел не найден или не принадлежит вам.")

#РЕДАКТИРОВАНИЕ

@router.message(Command("edit"))
async def cmd_edit(message: Message, db_pool):
    parts = message.text.split(maxsplit=2)  # /edit <id> <текст>
    if len(parts) < 3:
        await message.answer("Использование: /edit <ID> <новый текст>")
        return

    try:
        node_id = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return

    new_content = parts[2].strip()
    if not new_content:
        await message.answer("Текст не может быть пустым.")
        return

    user_id = message.from_user.id
    updated = await update_node_content(db_pool, user_id, node_id, new_content)

    if updated:
        await message.answer(f"✅ Узел {node_id} обновлён.")
    else:
        await message.answer("❌ Узел не найден или не принадлежит вам.")

@router.callback_query(F.data.startswith("edit_"))
async def edit_callback(callback: CallbackQuery, state: FSMContext, db_pool):
    try:
        node_id = int(callback.data.split("_", 1)[1])
    except ValueError:
        await callback.answer("Неверный ID узла.", show_alert=True)
        return

    user_id = callback.from_user.id
    # Проверим, существует ли узел и принадлежит ли он пользователю
    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM nodes WHERE id = $1 AND user_id = $2",
            node_id, user_id
        )
    if not exists:
        await callback.answer("Узел не найден или не принадлежит вам.", show_alert=True)
        return

    # Сохраняем ID узла и переходим в состояние ожидания текста
    await state.update_data(editing_node_id=node_id)
    await state.set_state(EditNode.waiting_for_content)
    await callback.message.edit_text(f"✏️ Введите новый текст для узла {node_id}:")
    await callback.answer()

@router.message(EditNode.waiting_for_content)
async def process_edit_content(message: Message, state: FSMContext, db_pool):
    new_content = message.text.strip()
    if not new_content:
        await message.answer("Текст не может быть пустым. Попробуйте снова:")
        return

    data = await state.get_data()
    node_id = data.get("editing_node_id")
    if not node_id:
        await message.answer("Ошибка: ID узла не найден.")
        await state.clear()
        return

    user_id = message.from_user.id
    updated = await update_node_content(db_pool, user_id, node_id, new_content)

    if updated:
        await message.answer(f"✅ Узел {node_id} успешно обновлён!")
    else:
        await message.answer("❌ Не удалось обновить узел (возможно, он был удалён).")

    await state.clear()  # выходим из состояния


def register_handlers(dp):
    dp.include_router(router)