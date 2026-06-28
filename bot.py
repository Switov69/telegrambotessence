import logging
import sqlite3
import asyncio
import sys
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Union

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, 
    KeyboardButton,
    CallbackQuery,
    Message,
    InputMediaPhoto,
    InputMediaVideo
)
from aiogram.exceptions import TelegramBadRequest
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8226412988:AAHokGE_pv-Ou2O5RddrasZeKPWO7xTFzsI"
OWNER_ID = 1746547600
CHANNEL_ID = -1002556198303
CHAT_LINK = "https://t.me/+MbQ0l7cDFzFmM2Yy"
PEREXODNIK_LINK = "https://t.me/sushnostinovika111"
PREDLOZHKA_LINK = "https://t.me/SushnostiNovikabot"

# Настройка логирования
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# --- БАЗА ДАННЫХ ---
class Database:
    def __init__(self, db_path="bot_data.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                is_admin BOOLEAN DEFAULT 0,
                is_banned BOOLEAN DEFAULT 0,
                ban_until DATETIME
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_received INTEGER DEFAULT 0,
                total_approved INTEGER DEFAULT 0,
                total_rejected INTEGER DEFAULT 0
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_posts (
                msg_unique_id TEXT PRIMARY KEY,
                admin_id INTEGER,
                admin_name TEXT,
                status TEXT
            )
        ''')
        # Таблица для хранения медиа постов для последующей публикации
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_posts (
                msg_uid TEXT PRIMARY KEY,
                user_id INTEGER,
                username TEXT,
                caption TEXT,
                media_data TEXT
            )
        ''')
        self.cursor.execute('SELECT COUNT(*) FROM stats')
        if self.cursor.fetchone()[0] == 0:
            self.cursor.execute('INSERT INTO stats (total_received, total_approved, total_rejected) VALUES (0, 0, 0)')
        self.conn.commit()

    def add_user(self, user_id, username, full_name):
        self.cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
        res = self.cursor.fetchone()
        if res:
            self.cursor.execute(
                'UPDATE users SET username = ?, full_name = ? WHERE user_id = ?',
                (username, full_name, user_id)
            )
        else:
            self.cursor.execute(
                'INSERT INTO users (user_id, username, full_name, is_admin) VALUES (?, ?, ?, 0)',
                (user_id, username, full_name)
            )
        self.conn.commit()

    def is_admin(self, user_id):
        if user_id == OWNER_ID: return True
        self.cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
        res = self.cursor.fetchone()
        return bool(res[0]) if res else False

    def get_all_admins(self) -> List[int]:
        self.cursor.execute('SELECT user_id FROM users WHERE is_admin = 1')
        admins = [row[0] for row in self.cursor.fetchall()]
        if OWNER_ID not in admins:
            admins.append(OWNER_ID)
        return list(set(admins))

    def check_ban(self, user_id):
        self.cursor.execute('SELECT is_banned, ban_until FROM users WHERE user_id = ?', (user_id,))
        res = self.cursor.fetchone()
        if not res: return False
        is_banned, until = res
        if is_banned and until:
            if datetime.now() > datetime.fromisoformat(until):
                self.set_ban(user_id, False)
                return False
            return True
        return bool(is_banned)

    def set_ban(self, user_id, status=True, until=None):
        ban_val = 1 if status else 0
        until_val = until.isoformat() if until else None
        self.cursor.execute('UPDATE users SET is_banned = ?, ban_until = ? WHERE user_id = ?', (ban_val, until_val, user_id))
        self.conn.commit()

    def set_admin_status(self, user_id, status=True):
        self.cursor.execute('UPDATE users SET is_admin = ? WHERE user_id = ?', (1 if status else 0, user_id))
        self.conn.commit()

    def update_stats(self, field):
        self.cursor.execute(f'UPDATE stats SET {field} = {field} + 1 WHERE id = 1')
        self.conn.commit()

    def get_admin_stats(self):
        self.cursor.execute('SELECT COUNT(*) FROM users')
        users_count = self.cursor.fetchone()[0]
        self.cursor.execute('SELECT total_received, total_approved, total_rejected FROM stats WHERE id = 1')
        s = self.cursor.fetchone()
        return {"users": users_count, "received": s[0], "approved": s[1], "rejected": s[2]}

    def mark_processed(self, msg_uid, admin_id, admin_name, status):
        self.cursor.execute('INSERT OR REPLACE INTO processed_posts VALUES (?, ?, ?, ?)', (msg_uid, admin_id, admin_name, status))
        self.conn.commit()

    def get_processed(self, msg_uid):
        self.cursor.execute('SELECT admin_name, status FROM processed_posts WHERE msg_unique_id = ?', (msg_uid,))
        return self.cursor.fetchone()

    def save_pending_post(self, msg_uid: str, user_id: int, username: str, caption: str, media_data: str):
        """Сохраняет данные поста (file_id медиа) для публикации в канал после одобрения"""
        self.cursor.execute(
            'INSERT OR REPLACE INTO pending_posts (msg_uid, user_id, username, caption, media_data) VALUES (?, ?, ?, ?, ?)',
            (msg_uid, user_id, username, caption, media_data)
        )
        self.conn.commit()

    def get_pending_post(self, msg_uid: str):
        self.cursor.execute('SELECT user_id, username, caption, media_data FROM pending_posts WHERE msg_uid = ?', (msg_uid,))
        return self.cursor.fetchone()

    def delete_pending_post(self, msg_uid: str):
        self.cursor.execute('DELETE FROM pending_posts WHERE msg_uid = ?', (msg_uid,))
        self.conn.commit()

db = Database()

# --- ХРАНИЛИЩА СОСТОЯНИЙ ---
user_last_post: Dict[int, datetime] = {}
user_delete_mode: Dict[int, bool] = {}

# Хранилище для сбора альбомов
# Структура: { media_group_id: [Message, Message, ...] }
media_groups_storage: Dict[str, List[Message]] = {}
# Таймеры на обработку групп, чтобы не запустить два раза
media_group_tasks: Dict[str, bool] = {}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def parse_time(time_str: str) -> Optional[timedelta]:
    if not time_str: return None
    pattern = re.compile(r"(\d+)\s*(сек|мин|час|день|дня|дней)")
    match = pattern.match(time_str.lower())
    if not match: return None
    value = int(match.group(1))
    unit = match.group(2)
    if "сек" in unit: return timedelta(seconds=value)
    if "мин" in unit: return timedelta(minutes=value)
    if "час" in unit: return timedelta(hours=value)
    if "дн" in unit or "день" in unit or "дня" in unit: return timedelta(days=value)
    return None

def get_pretty_time_string(time_str: str) -> str:
    pattern = re.compile(r"(\d+)\s*(сек|мин|час|день|дня|дней)")
    match = pattern.match(time_str.lower())
    if not match: return time_str
    value, unit = match.group(1), match.group(2)
    if "сек" in unit: return f"{value} секунд"
    if "мин" in unit: return f"{value} минут"
    if "час" in unit: return f"{value} часов"
    if "дн" in unit or "день" in unit or "дня" in unit: return f"{value} дней"
    return time_str

# --- КЛАВИАТУРЫ ---

def get_main_keyboard(user_id: int):
    buttons = []
    if db.is_admin(user_id):
        buttons.append([KeyboardButton(text="⚙️ Админ-панель"), KeyboardButton(text="📋 Правила")])
    else:
        buttons.append([KeyboardButton(text="📋 Правила")])
    buttons.append([KeyboardButton(text="🗑 Удалить пост"), KeyboardButton(text="💬 Чат")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    db.add_user(user.id, user.username, user.full_name)
    user_delete_mode[user.id] = False
    welcome_text = (
        f"👋 Привет, <b>{user.first_name}</b>!\n\n"
        "Это бот для анонимного мнения. Чтобы отправить пост, просто пришли мне сообщение с <b>текстом и медиа</b>.\n\n"
        "Воспользуйся меню ниже для навигации:"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(user.id), parse_mode="HTML")

@dp.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject):
    if not db.is_admin(message.from_user.id): return
    if not command.args:
        return await message.answer("⚠️ Формат: <code>/ban [ID] [время] [причина]</code>", parse_mode="HTML")
    try:
        args = command.args.split()
        target_id = int(args[0])
        duration_str, reason = None, "Не указана"
        if len(args) > 1:
            time_delta = parse_time(args[1])
            if time_delta:
                duration_str = args[1]
                if len(args) > 2: reason = " ".join(args[2:])
            else: reason = " ".join(args[1:])
        until = None
        duration_text_user = "навсегда"
        if duration_str:
            delta = parse_time(duration_str)
            if delta:
                until = datetime.now() + delta
                duration_text_user = get_pretty_time_string(duration_str)
        db.set_ban(target_id, True, until)
        current_date = datetime.now().strftime("%d.%m.%Y %H:%M")
        ban_msg_user = (
            "🚫 <b>Вы были заблокированы.</b>\n"
            f"• Срок бана: <b>{duration_text_user}</b>\n"
            f"• Причина: <b>{reason}</b>\n"
            f"• Дата бана: <b>{current_date}</b>"
        )
        try: await bot.send_message(target_id, ban_msg_user, parse_mode="HTML")
        except: pass
        await message.answer(f"✅ Пользователь <code>{target_id}</code> заблокирован <b>{duration_text_user}</b>.\nПричина: {reason}", parse_mode="HTML")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}", parse_mode="HTML")

@dp.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject):
    if not db.is_admin(message.from_user.id): return
    if not command.args: return await message.answer("⚠️ Формат: <code>/unban ID</code>", parse_mode="HTML")
    try:
        target_id = int(command.args.split()[0])
        db.set_ban(target_id, False)
        try: await bot.send_message(target_id, "✅ Вы были разблокированы администратором.")
        except: pass
        await message.answer(f"✅ Пользователь <code>{target_id}</code> разблокирован.", parse_mode="HTML")
    except: await message.answer("❌ Ошибка в ID.", parse_mode="HTML")

@dp.message(Command("addadmin"))
async def cmd_addadmin(message: Message, command: CommandObject):
    if message.from_user.id != OWNER_ID: return
    if not command.args: return
    try:
        target_id = int(command.args)
        if db.is_admin(target_id) and target_id != OWNER_ID:
            return await message.answer("⚠️ Этот пользователь уже является администратором.", parse_mode="HTML")
        db.set_admin_status(target_id, True)
        await message.answer(f"✅ Пользователь <code>{target_id}</code> назначен администратором.", parse_mode="HTML")
        try: await bot.send_message(target_id, "🔧 Вам выданы права администратора.", reply_markup=get_main_keyboard(target_id))
        except: pass
    except: await message.answer("❌ Неверный формат ID.", parse_mode="HTML")

@dp.message(Command("deladmin"))
async def cmd_deladmin(message: Message, command: CommandObject):
    if message.from_user.id != OWNER_ID: return
    if not command.args: return
    try:
        target_id = int(command.args)
        if target_id == OWNER_ID: return await message.answer("❌ Нельзя снять права с создателя.", parse_mode="HTML")
        if not db.is_admin(target_id): return await message.answer("⚠️ Этот пользователь не является администратором.", parse_mode="HTML")
        db.set_admin_status(target_id, False)
        await message.answer(f"✅ Пользователь <code>{target_id}</code> снят с поста администратора.", parse_mode="HTML")
        try: await bot.send_message(target_id, "🚫 Ваши права администратора были сняты.", reply_markup=get_main_keyboard(target_id))
        except: pass
    except: await message.answer("❌ Неверный формат ID.", parse_mode="HTML")

# --- ОБРАБОТЧИКИ МЕНЮ ---

@dp.message(F.text == "💬 Чат")
async def chat_button(message: types.Message):
    user_delete_mode[message.from_user.id] = False
    await message.answer(f"🗨 Наш чат сущностей: {CHAT_LINK}", disable_web_page_preview=True)

@dp.message(F.text == "📋 Правила")
async def rules_button(message: types.Message):
    user_delete_mode[message.from_user.id] = False
    rules_text = (
        "📜 <b>Правила публикации:</b>\n\n"
        "1. Сообщение должно содержать медиа.\n"
        "— 2 фото либо 1 видео\n"
        "2. Обязательно наличие текста под медиа.\n"
        "— без текста нельзя.\n"
        "3. Запрещен спам постами\n"
        "— Бан на 2 часа.\n"
        "4. Запрещена реклама/продажа в предложении.\n"
        "— Бан на 1 день.\n"
        "5. Запрещен любой контент 18+\n"
        "— Бан на 3 часа.\n"
        "6. Запрещен слив личной информации\n"
        "— Бан на 3 дня.\n"
        " \n"
        "ℹ️ Все посты публикуются анонимно."
    )
    await message.answer(rules_text, parse_mode="HTML")

@dp.message(F.text == "⚙️ Админ-панель")
async def admin_button(message: types.Message):
    if not db.is_admin(message.from_user.id): return
    user_delete_mode[message.from_user.id] = False
    stats = db.get_admin_stats()
    admin_text = (
        "⚙️ <b>Админ-панель</b>\n\n"
        f"👥 Всего пользователей: <code>{stats['users']}</code>\n"
        f"📥 Принято предложек: <code>{stats['received']}</code>\n"
        f"✅ Опубликовано: <code>{stats['approved']}</code>\n"
        f"❌ Отклонено: <code>{stats['rejected']}</code>\n\n"
        "Для управления используйте команды:\n"
        "<code>/ban [ID] [время] [причина]</code>\n"
        "<code>формат времени: 1сек/мин/час/дней</code>\n"
        "<code>/unban [ID]</code>\n"
    )
    await message.answer(admin_text, parse_mode="HTML")

@dp.message(F.text == "🗑 Удалить пост")
async def delete_request_info(message: types.Message):
    user_delete_mode[message.from_user.id] = True
    await message.answer("⚠️ Чтобы отправить запрос на удаление поста модерации, <b>перешлите нужный пост из канала</b> в чат с ботом.", parse_mode="HTML")

# --- ЛОГИКА ПРЕДЛОЖКИ ---

@dp.message(F.chat.type == "private")
async def handle_all_logic(message: Message):
    user_id = message.from_user.id
    is_in_del_mode = user_delete_mode.get(user_id, False)
    
    if message.text and (message.text.startswith("/") or message.text in ["💬 Чат", "📋 Правила", "⚙️ Админ-панель", "🗑 Удалить пост"]):
        return

    if db.check_ban(user_id):
        await message.answer("❌ Вы заблокированы.", parse_mode="HTML")
        return

    # Логика удаления
    if message.forward_from_chat or message.forward_date:
        if not is_in_del_mode:
            await message.answer("⚠️ Чтобы удалить пост, сначала нажмите кнопку «🗑 Удалить пост» в меню.", parse_mode="HTML")
            return
        if not message.forward_from_chat or message.forward_from_chat.id != CHANNEL_ID:
            await message.answer("❌ Ошибка! Нужно переслать пост именно из нашего телеграм канала.", parse_mode="HTML")
            return
        admins = db.get_all_admins()
        for adm in admins:
            try:
                sent_fwd = await message.forward(adm)
                del_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Удалить пост из канала", callback_data=f"confirm_del_{message.forward_from_message_id}")]
                ])
                await bot.send_message(adm, f"🗑 <b>Запрос на удаление поста</b>\nОт пользователя: <code>{user_id}</code>", reply_to_message_id=sent_fwd.message_id, reply_markup=del_kb, parse_mode="HTML")
            except: continue
        await message.answer("✅ Запрос на удаление отправлен модераторам.", parse_mode="HTML")
        user_delete_mode[user_id] = False 
        return

    # ЛОГИКА СБОРА МЕДИАГРУПП (Альбомов)
    if message.media_group_id:
        mg_id = message.media_group_id
        if mg_id not in media_groups_storage:
            media_groups_storage[mg_id] = []
        
        media_groups_storage[mg_id].append(message)

        # Запускаем таймер только один раз на группу
        if mg_id not in media_group_tasks:
            media_group_tasks[mg_id] = True
            asyncio.create_task(process_media_group(mg_id, user_id))
        return

    # Логика для одиночных файлов
    if message.photo or message.video:
        if not (message.caption or message.text):
            return await message.answer("⚠️ Пожалуйста, добавьте <b>текстовое описание</b> к вашему медиа-файлу.", parse_mode="HTML")
        
        if not check_flood(user_id):
            return await message.answer("⚠️ Пожалуйста, подождите 15 секунд перед следующей отправкой.", parse_mode="HTML")
        
        await send_to_moderation(user_id, [message])
    else:
        await message.answer("⚠️ Необходимо отправить <b>фото/видео вместе с текстом</b>.", parse_mode="HTML")

def check_flood(user_id: int) -> bool:
    last_post_time = user_last_post.get(user_id)
    if last_post_time and (datetime.now() - last_post_time).total_seconds() < 15:
        return False
    user_last_post[user_id] = datetime.now()
    return True

async def process_media_group(mg_id: str, user_id: int):
    """Ждет завершения загрузки всех частей альбома и обрабатывает их"""
    await asyncio.sleep(1.0)  # Немного увеличено для надёжности сбора всех частей
    
    messages = media_groups_storage.pop(mg_id, [])
    media_group_tasks.pop(mg_id, None)
    
    if not messages: return

    # Сортируем по ID сообщения для правильного порядка
    messages.sort(key=lambda x: x.message_id)

    # Текст берём из первого сообщения с caption
    caption = next((m.caption for m in messages if m.caption), None)
    if not caption:
        await bot.send_message(user_id, "⚠️ Пожалуйста, добавьте <b>текстовое описание</b> к вашему альбому.", parse_mode="HTML")
        return

    photos = [m for m in messages if m.photo]
    videos = [m for m in messages if m.video]

    if len(photos) > 2:
        await bot.send_message(user_id, "⚠️ Можно отправить не более 2-х фото.", parse_mode="HTML")
        return
    if len(videos) > 1:
        await bot.send_message(user_id, "⚠️ Вы можете отправить только одно видео в одном сообщении.", parse_mode="HTML")
        return
    if len(photos) > 0 and len(videos) > 0:
        await bot.send_message(user_id, "⚠️ Нельзя смешивать фото и видео в одном посте.", parse_mode="HTML")
        return

    if not check_flood(user_id):
        await bot.send_message(user_id, "⚠️ Пожалуйста, подождите 15 секунд перед следующей отправкой.", parse_mode="HTML")
        return

    await send_to_moderation(user_id, messages)

async def send_to_moderation(user_id: int, messages: List[Message]):
    """Отправляет накопленные медиа администраторам"""
    import json

    db.update_stats("total_received")
    
    sender = messages[0].from_user
    username = f"@{sender.username}" if sender.username else sender.full_name
    msg_uid = f"{user_id}_{messages[0].message_id}"
    caption = next((m.caption for m in messages if m.caption), "") or ""

    # --- Собираем file_id всех медиафайлов для последующей публикации в канал ---
    media_entries = []
    for m in messages:
        if m.photo:
            media_entries.append({"type": "photo", "file_id": m.photo[-1].file_id})
        elif m.video:
            media_entries.append({"type": "video", "file_id": m.video.file_id})

    # Сохраняем пост в БД для публикации после одобрения
    db.save_pending_post(msg_uid, user_id, username, caption, json.dumps(media_entries))

    admins = db.get_all_admins()

    mod_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"ap_{msg_uid}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"re_{msg_uid}")
        ]
    ])

    for adm in admins:
        try:
            if len(media_entries) > 1:
                # Альбом из нескольких медиа
                media_list = []
                for i, entry in enumerate(media_entries):
                    cap = caption if i == 0 else None
                    if entry["type"] == "photo":
                        media_list.append(InputMediaPhoto(media=entry["file_id"], caption=cap, parse_mode="HTML"))
                    elif entry["type"] == "video":
                        media_list.append(InputMediaVideo(media=entry["file_id"], caption=cap, parse_mode="HTML"))

                sent_msgs = await bot.send_media_group(chat_id=adm, media=media_list)
                # Сообщение с кнопками отправляем как ответ на ПЕРВОЕ сообщение альбома
                await bot.send_message(
                    adm,
                    f"📨 Новый пост от {username}\nID: <code>{user_id}</code>",
                    reply_to_message_id=sent_msgs[0].message_id,
                    reply_markup=mod_kb,
                    parse_mode="HTML"
                )
            else:
                # Одиночное медиа
                entry = media_entries[0]
                if entry["type"] == "photo":
                    sent = await bot.send_photo(adm, entry["file_id"], caption=caption, parse_mode="HTML")
                else:
                    sent = await bot.send_video(adm, entry["file_id"], caption=caption, parse_mode="HTML")
                await bot.send_message(
                    adm,
                    f"📨 Новый пост от {username}\nID: <code>{user_id}</code>",
                    reply_to_message_id=sent.message_id,
                    reply_markup=mod_kb,
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.error(f"Ошибка отправки admin {adm}: {e}")
    
    await bot.send_message(user_id, "✅ Ваше мнение отправлено на модерацию!", parse_mode="HTML")

# --- CALLBACKS ---

@dp.callback_query()
async def process_callbacks(callback: CallbackQuery):
    import json

    data = callback.data
    admin_id = callback.from_user.id
    admin_name = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name
    
    if not db.is_admin(admin_id): return

    if data.startswith(("ap_", "re_")):
        parts = data.split("_")
        action = parts[0]
        target_user_id = int(parts[1])
        msg_uid = f"{parts[1]}_{parts[2]}"
        
        processed = db.get_processed(msg_uid)
        if processed:
            p_admin, p_status = processed
            # ИСПРАВЛЕНИЕ: toast вместо alert (show_alert=False)
            await callback.answer(f"❗ Этот пост уже {p_status}", show_alert=False)
            return

        if action == "ap":
            footer = f"\n\n<a href='{PEREXODNIK_LINK}'>Переходник</a> | <a href='{PREDLOZHKA_LINK}'>Предложка</a> | <a href='{CHAT_LINK}'>Чат</a>"

            # Берём сохранённые данные поста из БД
            pending = db.get_pending_post(msg_uid)
            if not pending:
                await callback.answer("❌ Данные поста не найдены. Возможно, он уже был обработан.", show_alert=False)
                return

            _, _, caption, media_data_raw = pending
            try:
                media_entries = json.loads(media_data_raw)
            except Exception:
                await callback.answer("❌ Ошибка чтения данных поста.", show_alert=False)
                return

            try:
                if len(media_entries) > 1:
                    # Публикуем альбом в канал
                    media_list = []
                    for i, entry in enumerate(media_entries):
                        cap = (caption + footer) if i == 0 else None
                        if entry["type"] == "photo":
                            media_list.append(InputMediaPhoto(media=entry["file_id"], caption=cap, parse_mode="HTML"))
                        elif entry["type"] == "video":
                            media_list.append(InputMediaVideo(media=entry["file_id"], caption=cap, parse_mode="HTML"))
                    await bot.send_media_group(chat_id=CHANNEL_ID, media=media_list)
                else:
                    entry = media_entries[0]
                    cap = caption + footer
                    if entry["type"] == "photo":
                        await bot.send_photo(CHANNEL_ID, entry["file_id"], caption=cap, parse_mode="HTML")
                    elif entry["type"] == "video":
                        await bot.send_video(CHANNEL_ID, entry["file_id"], caption=cap, parse_mode="HTML")

                db.update_stats("total_approved")
                db.mark_processed(msg_uid, admin_id, admin_name, "ОДОБРЕН")
                db.delete_pending_post(msg_uid)

                # ИСПРАВЛЕНИЕ: в статусе не упоминается имя админа, но username/ID отправителя сохраняются
                pending_full = db.get_pending_post(msg_uid)  # уже удалён, берём из callback
                # Получаем username из сохранённого pending до удаления
                # (мы уже сделали delete_pending_post выше, поэтому username берём из pending)
                sender_username_raw = pending[1] if pending else "неизвестен"
                sender_id_raw = pending[0] if pending else target_user_id

                await callback.message.edit_text(
                    f"✅ <b>Пост одобрен</b>\n\n"
                    f"👤 От: {sender_username_raw}\n"
                    f"🆔 ID: <code>{sender_id_raw}</code>",
                    parse_mode="HTML"
                )
                # toast-уведомление для админа
                await callback.answer("✅ Пост опубликован в канале", show_alert=False)
                try: await bot.send_message(target_user_id, "🎉 Ваш пост опубликован в канале!", parse_mode="HTML")
                except: pass

            except Exception as e:
                logger.error(f"Ошибка публикации: {e}")
                await callback.answer(f"❌ Ошибка публикации: {e}", show_alert=False)
        else:
            # Отклонение
            pending = db.get_pending_post(msg_uid)
            sender_username_raw = pending[1] if pending else "неизвестен"
            sender_id_raw = pending[0] if pending else target_user_id

            db.update_stats("total_rejected")
            db.mark_processed(msg_uid, admin_id, admin_name, "ОТКЛОНЕН")
            if pending:
                db.delete_pending_post(msg_uid)

            await callback.message.edit_text(
                f"❌ <b>Пост отклонён</b>\n\n"
                f"👤 От: {sender_username_raw}\n"
                f"🆔 ID: <code>{sender_id_raw}</code>",
                parse_mode="HTML"
            )
            # toast-уведомление для админа
            await callback.answer("❌ Пост отклонён", show_alert=False)
            try: await bot.send_message(target_user_id, "😔 Ваш пост был отклонен модерацией.", parse_mode="HTML")
            except: pass

    elif data.startswith("confirm_del_"):
        post_id = int(data.split("_")[2])
        try:
            await bot.delete_message(CHANNEL_ID, post_id)
            await callback.message.edit_text(f"🗑 Пост <code>#{post_id}</code> успешно удален из канала.", parse_mode="HTML")
            await callback.answer("🗑 Пост удалён из канала", show_alert=False)
        except Exception as e:
            await callback.answer(f"Не удалось удалить: {e}", show_alert=False)
    else:
        await callback.answer()
        
# --- САЙТ ДЛЯ ПИНГА ---
async def handle_ping(request):
    return web.Response(text="Bot is running smoothly!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Порт 10000 часто используется по умолчанию на Render, 
    # но лучше брать его из переменных окружения хостинга
    import os
    port = int(os.environ.get("PORT", 10000))
    
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"веб-сервер запущен на порту {port}")

async def main():
    print("--- БОТ ЗАПУЩЕН (aiogram 3.x) ---")
    asyncio.create_task(start_web_server())
    try: await dp.start_polling(bot, skip_updates=True)
    finally: await bot.session.close()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: sys.exit(0)
