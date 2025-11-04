from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from typing import Optional
import logging

from handlers.states import AddNode, EditNode, SearchQuery

router = Router()
logger = logging.getLogger(__name__)

#ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ


async def get_children(pool, user_id: int, parent_id: Optional[int]):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, content, file_type FROM nodes WHERE user_id = $1 AND parent_id IS NOT DISTINCT FROM $2 ORDER BY id",
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

async def create_node_with_file(pool, user_id: int, parent_id: Optional[int], content: str, file_id: str, file_type: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO nodes (user_id, parent_id, content, file_id, file_type)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            user_id, parent_id, content, file_id, file_type
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

async def build_path_to_node(pool, node_id: int) -> str:
    """Возвращает путь к узлу в виде 'Корень → Папка → Узел'."""
    async with pool.acquire() as conn:
        # Рекурсивный запрос: поднимаемся вверх по parent_id
        path_rows = await conn.fetch("""
            WITH RECURSIVE path AS (
                SELECT id, parent_id, content, 0 AS level
                FROM nodes
                WHERE id = $1
                UNION ALL
                SELECT n.id, n.parent_id, n.content, p.level + 1
                FROM nodes n
                INNER JOIN path p ON n.id = p.parent_id
            )
            SELECT content FROM path
            ORDER BY level DESC
        """, node_id)

        if not path_rows:
            return "Неизвестный путь"

        contents = [row["content"] for row in path_rows]
        return " → ".join(contents)

async def search_nodes(pool, user_id: int, query: str):
    """Ищет узлы пользователя, содержащие query в content (регистронезависимо)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, content
            FROM nodes
            WHERE user_id = $1 AND content ILIKE $2
            ORDER BY id
        """, user_id, f"%{query}%")
        return rows

#СОХРАНЕНИЕ МЕДИА
router.message(F.document)
async def handle_document(message: Message, state: FSMContext, db_pool):
    user_id = message.from_user.id
    file_id = message.document.file_id
    caption = message.caption or "Документ"

    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")

    node_id = await create_node_with_file(
        db_pool, user_id, current_folder_id, caption, file_id, "document"
    )
    await message.answer(f"📎 Документ сохранён! ID: {node_id}")

@router.message(F.photo)
async def handle_photo(message: Message, state: FSMContext, db_pool):
    user_id = message.from_user.id
    file_id = message.photo[-1].file_id  # самый большой размер
    caption = message.caption or "Фото"

    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")

    # Используем функцию с file_type!
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO nodes (user_id, parent_id, content, file_id, file_type)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            user_id, current_folder_id, caption, file_id, "photo"
        )
    node_id = row["id"]
    await message.answer(f"🖼️ Фото сохранено! ID: {node_id}")

@router.message(F.video)
async def handle_video(message: Message, state: FSMContext, db_pool):
    user_id = message.from_user.id
    file_id = message.video.file_id
    caption = message.caption or "Видео"

    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")

    node_id = await create_node_with_file(
        db_pool, user_id, current_folder_id, caption, file_id, "video"
    )
    await message.answer(f"🎥 Видео сохранено! ID: {node_id}")

@router.message(F.audio)
async def handle_audio(message: Message, state: FSMContext, db_pool):
    user_id = message.from_user.id
    file_id = message.audio.file_id
    caption = message.caption or "Аудио"
    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")
    node_id = await create_node_with_file(db_pool, user_id, current_folder_id, caption, file_id, "audio")
    await message.answer(f"🎵 Аудио сохранено! ID: {node_id}")

@router.message(F.voice)
async def handle_voice(message: Message, state: FSMContext, db_pool):
    user_id = message.from_user.id
    file_id = message.voice.file_id
    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")
    node_id = await create_node_with_file(db_pool, user_id, current_folder_id, "Голосовое сообщение", file_id, "voice")
    await message.answer(f"🎤 Голосовое сохранено! ID: {node_id}")

@router.message(F.animation)
async def handle_animation(message: Message, state: FSMContext, db_pool):
    user_id = message.from_user.id
    file_id = message.animation.file_id
    caption = message.caption or "Анимация"
    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")
    node_id = await create_node_with_file(db_pool, user_id, current_folder_id, caption, file_id, "animation")
    await message.answer(f"🎬 Анимация сохранена! ID: {node_id}")

@router.callback_query(F.data.startswith("view_"))
async def view_media(callback: CallbackQuery, db_pool):
    try:
        node_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Неверный ID узла.", show_alert=True)
        return

    user_id = callback.from_user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT file_id, file_type, content FROM nodes WHERE id = $1 AND user_id = $2",
            node_id, user_id
        )
    if not row:
        await callback.answer("Файл не найден.", show_alert=True)
        return

    file_id = row["file_id"]
    file_type = row["file_type"]
    caption = row["content"]

    try:
        if file_type == "photo":
            await callback.message.answer_photo(photo=file_id, caption=caption)
        elif file_type == "video":
            await callback.message.answer_video(video=file_id, caption=caption)
        elif file_type == "document":
            await callback.message.answer_document(document=file_id, caption=caption)
        elif file_type == "audio":
            await callback.message.answer_audio(audio=file_id, caption=caption)
        elif file_type == "voice":
            await callback.message.answer_voice(voice=file_id)
        elif file_type == "animation":
            await callback.message.answer_animation(animation=file_id, caption=caption)
        else:
            await callback.message.answer("Неизвестный тип файла.")
    except Exception as e:
        logger.exception("Ошибка отправки медиа")
        await callback.message.answer("❌ Не удалось отправить файл.")

    await callback.answer()

#ФУНКЦИЯ СТАРТА
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, db_pool):
    await state.update_data(current_folder_id=None)
    await message.answer(
        "Добро пожаловать в хранилище БРО"
    )
    await cmd_ls(message, state, db_pool)

#УДАЛЕНИЕ ПАПКИ
@router.callback_query(F.data.startswith("rm_"))
async def rm_callback(callback: CallbackQuery, state: FSMContext, db_pool):
    try:
        node_id = int(callback.data[3:])
    except ValueError:
        await callback.answer("Неверный ID узла.", show_alert=True)
        return

    user_id = callback.from_user.id
    deleted = await delete_node(db_pool, user_id, node_id)

    if deleted:
        await callback.message.edit_text(f"✅ Узел {node_id} удалён.")
        await cmd_ls(callback.message, state, db_pool)
        
    else:
        await callback.answer("Узел не найден или не принадлежит вам.", show_alert=True)

#ОТОБРАЖЕНИЕ ДОЧЕРНИХ ПАПОК
@router.message(Command("ls"))
async def cmd_ls(message: Message, state: FSMContext, db_pool):
    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")

    user_id = message.chat.id
    children = await get_children(db_pool, user_id, current_folder_id)

    # === Заголовок: где мы находимся ===
    if current_folder_id is None:
        text = "📂 <b>Корневая папка</b>\n\n"
    else:
        path = await build_path_to_node(db_pool, current_folder_id)
        text = f"📂 <b>Текущая папка:</b>\n{path}\n\n"

    # === Содержимое ===
    node_buttons = []
    if not children:
        text += "Папка пуста."
    else:
        text += "Содержимое:\n\n"
        for row in children:
            node_id = row["id"]
            content = row["content"]
            file_type = row.get("file_type")  # Может быть None

            # Определяем эмодзи по типу
            if file_type == "document":
                prefix = "📎"
            elif file_type == "photo":
                prefix = "🖼️"
            elif file_type == "video":
                prefix = "🎥"
            elif file_type == "audio":
                prefix = "🎵"
            elif file_type == "voice":
                prefix = "🎤"
            elif file_type == "animation":
                prefix = "🎬"
            else:
                prefix = "📁"

            text += f"{prefix} {content}\n"

            # === Кнопки для узла ===
            buttons_row = []

            if file_type is not None:
                # Медиа — можно только просматривать
                buttons_row.append(
                    InlineKeyboardButton(text="👁️ Просмотр", callback_data=f"view_{node_id}")
                )
            else:
                # Текстовый узел — можно открывать (как папку)
                buttons_row.append(
                    InlineKeyboardButton(text= content, callback_data=f"cd_{node_id}")##dxfgsdfgsdfg
                )

            # Редактирование и удаление — для всех
            buttons_row.append(
                InlineKeyboardButton(text="✏️ Ред.", callback_data=f"edit_{node_id}")
            )
            buttons_row.append(
                InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"rm_{node_id}")
            )

            node_buttons.append(buttons_row)

    # === Глобальные действия (внизу) ===
    action_buttons = [
        InlineKeyboardButton(text="➕ Добавить", callback_data="action_add"),
        InlineKeyboardButton(text="🔍 Поиск", callback_data="action_search"),
    ]
    if current_folder_id is not None:
        action_buttons.append(
            InlineKeyboardButton(text="↑ В корень", callback_data="cd_root")
        )

    # Собираем клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=node_buttons + [action_buttons])

    # Отправляем сообщение

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

# ВОЗВРАТ В КОРЕНЬ
@router.callback_query(F.data == "cd_root")
async def cd_to_root(callback: CallbackQuery, state: FSMContext, db_pool):
    await state.update_data(current_folder_id=None)
    await cmd_ls(callback.message, state, db_pool)

@router.message(Command("root"))
async def cmd_root(message: Message, state: FSMContext, db_pool):
    await state.update_data(current_folder_id=None)
    await cmd_ls(message, state, db_pool)

#ПЕРЕМЕЩЕНИЕ ПО ПАПКАМ
#Вызывается при переходе в папке по кнопкам
@router.callback_query(F.data.startswith("cd_") & F.data.len() > 3)  # длина > "cd_" (3 символа)
async def cd_to_folder(callback: CallbackQuery, state: FSMContext, db_pool):
    print("cd_to_folder")
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
    await cmd_ls(callback.message, state, db_pool)
    await callback.answer()

#Нафига вообще нужно?
# @router.callback_query(F.data.startswith("cd_"))
# async def cd_callback(callback: CallbackQuery, state: FSMContext, db_pool):
#     print("cd_callback")
#     data = callback.data

#     if data == "cd_root":
#         await state.update_data(current_folder_id=None)
#         await callback.message.edit_text("📂 Вы вернулись в корневую папку.")
#         await callback.answer()
#         return

#     try:
#         folder_id = int(data[3:])
#     except ValueError:
#         await callback.answer("Неверный ID папки.", show_alert=True)
#         return

#     user_id = callback.from_user.id
#     async with db_pool.acquire() as conn:
#         node = await conn.fetchrow(
#             "SELECT file_type FROM nodes WHERE id = $1 AND user_id = $2",
#             folder_id, user_id
#         )
#     if not node:
#         await callback.answer("Папка не найдена или не принадлежит вам.", show_alert=True)
#         return

#     # 🔴 Если это медиа — нельзя заходить внутрь!
#     if node["file_type"] is not None:
#         await callback.answer("❌ Это медиафайл, а не папка. Нажмите «👁️ Просмотр».", show_alert=True)
#         return

#     # Иначе — разрешаем переход
#     await state.update_data(current_folder_id=folder_id)
#     await callback.message.edit_text(f"✅ Перешёл в папку {folder_id}. Используй /ls для просмотра.")
#     await callback.answer()

#Вызывается при вызове через чат
@router.message(Command("cd"))
async def cmd_cd(message: Message, state: FSMContext, db_pool):
    print("cmd_cd")
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
        node = await conn.fetchrow(
            "SELECT file_type FROM nodes WHERE id = $1 AND user_id = $2",
            folder_id, user_id
        )
    if not node:
        await message.answer("Папка не найдена или не принадлежит вам.")
        return

    if node["file_type"] is not None:
        await message.answer("❌ Это медиафайл, а не папка. Используйте кнопку «👁️ Просмотр».")
        return

    await state.update_data(current_folder_id=folder_id)    
    await cmd_ls(message, state, db_pool)


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

#ПОИСК
@router.message(Command("search"))
async def cmd_search(message: Message, db_pool):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /search <текст для поиска>")
        return

    query = args[1].strip()
    if len(query) < 2:
        await message.answer("Поисковый запрос должен содержать минимум 2 символа.")
        return

    user_id = message.from_user.id
    results = await search_nodes(db_pool, user_id, query)

    if not results:
        await message.answer("🔍 Ничего не найдено.")
        return

    response = f"Найдено {len(results)} результатов:\n\n"
    for row in results:
        path = await build_path_to_node(db_pool, row["id"])
        response += f"• ID {row['id']}: {row['content']}\n  Путь: {path}\n\n"

    # Telegram имеет лимит ~4096 символов на сообщение
    # Если ответ слишком длинный — разобьём на части
    MAX_MSG_LEN = 4000
    if len(response) <= MAX_MSG_LEN:
        await message.answer(response)
    else:
        # Простое разбиение по абзацам
        parts = []
        current = ""
        for line in response.split("\n\n"):
            if len(current) + len(line) + 2 > MAX_MSG_LEN:
                parts.append(current)
                current = line
            else:
                current = current + "\n\n" + line if current else line
        if current:
            parts.append(current)

        for part in parts:
            await message.answer(part)

@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, db_pool):
    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")

    text = "퀵-меню действий:\n\n"

    if current_folder_id is None:
        text += "📍 Вы в корневой папке.\n"
    else:
        path = await build_path_to_node(db_pool, current_folder_id)
        text += f"📍 Текущая папка: {path}\n"

    buttons = [
        [
            InlineKeyboardButton(text="➕ Добавить узел", callback_data="action_add"),
            InlineKeyboardButton(text="🔍 Поиск", callback_data="action_search"),
        ],
        [
            InlineKeyboardButton(text="📂 Показать содержимое", callback_data="action_ls"),
        ]
    ]

    if current_folder_id is not None:
        buttons.append([
            InlineKeyboardButton(text="↑ В корень", callback_data="cd_root"),
        ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(text, reply_markup=keyboard)

@router.callback_query(F.data == "action_add")
async def action_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddNode.waiting_for_content)
    await callback.message.answer("✏️ Введите текст нового узла:")
    await callback.answer()

@router.callback_query(F.data == "action_search")
async def action_search(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SearchQuery.waiting_for_query)
    await callback.message.answer("🔍 Введите текст для поиска:")
    await callback.answer()

@router.callback_query(F.data == "action_ls")
async def action_ls(callback: CallbackQuery, state: FSMContext, db_pool):
    # Просто вызовем логику /ls
    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")
    user_id = callback.from_user.id
    children = await get_children(db_pool, user_id, current_folder_id)

    text = "Содержимое:\n\n"
    if not children:
        text = "Папка пуста."
    else:
        for row in children:
            text += f"📁 {row['id']}: {row['content']}\n"

    await callback.message.answer(text)
    await callback.answer()

@router.message(AddNode.waiting_for_content)
async def process_add_content(message: Message, state: FSMContext, db_pool):
    content = message.text.strip()
    if not content:
        await message.answer("Текст не может быть пустым. Попробуйте снова:")
        return

    user_id = message.from_user.id
    data = await state.get_data()
    current_folder_id = data.get("current_folder_id")  # из Navigation

    try:
        node_id = await create_node(db_pool, user_id, current_folder_id, content)
        await message.answer(f"✅ Узел создан! ID: {node_id}")
        await cmd_ls(message, state, db_pool)

    except Exception as e:
        logger.exception("Ошибка при создании узла")
        await message.answer("❌ Не удалось создать узел.")

    await state.clear()  # выходим из состояния добавления

@router.message(SearchQuery.waiting_for_query)
async def process_search_query(message: Message, state: FSMContext, db_pool):
    query = message.text.strip()
    if len(query) < 2:
        await message.answer("Запрос должен содержать минимум 2 символа. Попробуйте снова:")
        return

    user_id = message.from_user.id
    results = await search_nodes(db_pool, user_id, query)

    if not results:
        await message.answer("🔍 Ничего не найдено.")
    else:
        response = f"Найдено {len(results)} результатов:\n\n"
        for row in results:
            path = await build_path_to_node(db_pool, row["id"])
            response += f"• ID {row['id']}: {row['content']}\n  Путь: {path}\n\n"

        MAX_MSG_LEN = 4000
        if len(response) <= MAX_MSG_LEN:
            await message.answer(response)
        else:
            parts = []
            current = ""
            for line in response.split("\n\n"):
                if len(current) + len(line) + 2 > MAX_MSG_LEN:
                    parts.append(current)
                    current = line
                else:
                    current = current + "\n\n" + line if current else line
            if current:
                parts.append(current)
            for part in parts:
                await message.answer(part)

    await state.clear()  # выходим из состояния поиска

def register_handlers(dp):
    dp.include_router(router)