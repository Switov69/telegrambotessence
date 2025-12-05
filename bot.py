import logging
import sqlite3
import time
import asyncio
import sys
import os
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.error import NetworkError, TimedOut, BadRequest, Forbidden, Conflict
from datetime import datetime

# ====== НАСТРОЙКИ ======
BOT_TOKEN = "8418277065:AAHsRqkGYoqZH2gI68yKRNe-Dp731Qxs4Js"
ADMIN_CHAT_ID = 8069781607  # Ваш chat_id
CHANNEL_CHAT_ID = "-1002556198303"  # ID вашего канала
CHAT_LINK = "https://t.me/+1Es8MH54mf0wNzVi"  # Ссылка на чат
PEREXODNIK_LINK = "https://t.me/sushnostinovika111"  # Ссылка на переходник
PREDLOZHKA_LINK = "https://t.me/SushnostiNovikabot"  # Ссылка на бота предложки

# Состояния для ConversationHandler
WAITING_BROADCAST = 1
WAITING_ADD_ADMIN = 2
WAITING_REMOVE_ADMIN = 3

# ====== ПРОВЕРКА ЗАПУЩЕННЫХ ЭКЗЕМПЛЯРОВ ======
def check_running_instances():
    """Проверяет, есть ли другие запущенные экземпляры бота (только предупреждение)"""
    try:
        lock_file = "bot.lock"
        if os.path.exists(lock_file):
            with open(lock_file, 'r') as f:
                pid = f.read().strip()
            try:
                if os.name != 'nt':
                    os.kill(int(pid), 0)
                print("=" * 60)
                print("⚠️  ВНИМАНИЕ: Обнаружен другой запущенный экземпляр бота!")
                print(f"📌 PID другого процесса: {pid}")
                print("💡 РЕКОМЕНДАЦИЯ:")
                print("   Рекомендуется остановить все экземпляры кроме одного")
                print("   во избежание конфликтов и дублирования сообщений.")
                print("=" * 60)
                return True
            except:
                # Процесс не существует, удаляем старый lock файл
                os.remove(lock_file)
                return False
        
        # Создаем новый lock файл
        with open(lock_file, 'w') as f:
            f.write(str(os.getpid()))
        return False
    except Exception as e:
        logger.warning(f"Ошибка при проверке запущенных экземпляров: {e}")
        return False

def cleanup_lock_file():
    """Удаляет lock-файл при завершении работы"""
    try:
        lock_file = "bot.lock"
        if os.path.exists(lock_file):
            # Проверяем, что удаляем только свой lock файл
            with open(lock_file, 'r') as f:
                pid = f.read().strip()
            if pid == str(os.getpid()):
                os.remove(lock_file)
                logger.info("✅ Lock файл удален")
    except:
        pass
        
# ====== НАСТРОЙКА ЛОГИРОВАНИЯ ======
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# ====== ФУНКЦИИ ЛОГИРОВАНИЯ ======
def log_user_action(user_id: int, username: str, action: str, details: str = ""):
    """Логирует действия пользователей"""
    username_display = f"@{username}" if username else "без username"
    log_message = f"👤 USER ACTION | ID: {user_id} | User: {username_display} | Action: {action}"
    if details:
        log_message += f" | Details: {details}"
    logger.info(log_message)

def log_admin_action(admin_id: int, username: str, action: str, target_user_id: int = None, details: str = ""):
    """Логирует действия администраторов"""
    username_display = f"@{username}" if username else "без username"
    log_message = f"🔧 ADMIN ACTION | Admin: {username_display} (ID: {admin_id}) | Action: {action}"
    if target_user_id:
        log_message += f" | Target: {target_user_id}"
    if details:
        log_message += f" | Details: {details}"
    logger.info(log_message)

def log_suggestion_action(user_id: int, username: str, action: str, suggestion_id: int = None, details: str = ""):
    """Логирует действия с предложениями"""
    username_display = f"@{username}" if username else "без username"
    log_message = f"📨 SUGGESTION | User: {username_display} (ID: {user_id}) | Action: {action}"
    if suggestion_id:
        log_message += f" | Suggestion ID: {suggestion_id}"
    if details:
        log_message += f" | Details: {details}"
    logger.info(log_message)

def log_ban_action(admin_id: int, admin_username: str, action: str, target_user_id: int, reason: str = ""):
    """Логирует действия с банами"""
    admin_display = f"@{admin_username}" if admin_username else "без username"
    log_message = f"🚫 BAN ACTION | Admin: {admin_display} (ID: {admin_id}) | Action: {action} | Target: {target_user_id}"
    if reason:
        log_message += f" | Reason: {reason}"
    logger.info(log_message)

# ====== БАЗА ДАННЫХ ======
def get_db_connection():
    """Создает соединение с базой данных с повторными попытками при блокировке"""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect('suggestions.db', check_same_thread=False, timeout=10)
            return conn
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.1)
                continue
            else:
                logger.error(f"Ошибка подключения к БД: {e}")
                raise e

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                message_text TEXT,
                file_id TEXT,
                file_id_2 TEXT,
                video_id TEXT,
                file_type TEXT DEFAULT 'photo',
                status TEXT DEFAULT 'pending',
                moderated_by INTEGER,
                channel_message_id INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                role TEXT DEFAULT 'user',
                added_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                username TEXT,
                first_name TEXT,
                reason TEXT,
                banned_by INTEGER,
                banned_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name, role) VALUES (?, ?, ?, ?)',
                      (ADMIN_CHAT_ID, "svitbandit", "Главный администратор", "main_admin"))
        
        # Добавляем колонку video_id если она не существует
        try:
            cursor.execute("SELECT video_id FROM suggestions LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE suggestions ADD COLUMN video_id TEXT")
            logger.info("✅ Добавлена колонка video_id в таблицу suggestions")
        
        # Добавляем колонку file_type если она не существует
        try:
            cursor.execute("SELECT file_type FROM suggestions LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE suggestions ADD COLUMN file_type TEXT DEFAULT 'photo'")
            logger.info("✅ Добавлена колонка file_type в таблицу suggestions")
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# ====== ПРОВЕРКА ПРАВ ======
def get_user_role(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else "user"
    except Exception as e:
        logger.error(f"Ошибка получения роли пользователя {user_id}: {e}")
        return "user"

def is_admin(user_id):
    role = get_user_role(user_id)
    return role in ["admin", "main_admin"]

def is_main_admin(user_id):
    return get_user_role(user_id) == "main_admin"

def get_admins():
    """Получает список админов"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE role IN ("admin", "main_admin")')
        admins = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        valid_admins = []
        for admin_id in admins:
            if isinstance(admin_id, int) and admin_id > 0:
                valid_admins.append(admin_id)
        
        return valid_admins
    except Exception as e:
        logger.error(f"Ошибка получения списка админов: {e}")
        return []

def get_all_users():
    """Получает всех пользователей для рассылки"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT user_id FROM users WHERE user_id IS NOT NULL')
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users
    except Exception as e:
        logger.error(f"Ошибка получения списка пользователей: {e}")
        return []

# ====== ФУНКЦИИ ДЛЯ БАНОВ ======
def is_banned(user_id):
    """Проверяет, забанен ли пользователь"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM bans WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"Ошибка проверки бана для пользователя {user_id}: {e}")
        return False

def get_ban_info(user_id):
    """Получает информацию о бане пользователя"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM bans WHERE user_id = ?', (user_id,))
        ban_info = cursor.fetchone()
        conn.close()
        return ban_info
    except Exception as e:
        logger.error(f"Ошибка получения информации о бане {user_id}: {e}")
        return None

def get_banned_users():
    """Получает список забаненных пользователей"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, first_name, reason, banned_by, banned_at FROM bans ORDER BY banned_at DESC')
        banned_users = cursor.fetchall()
        conn.close()
        return banned_users
    except Exception as e:
        logger.error(f"Ошибка получения списка банов: {e}")
        return []

def ban_user(user_id, username, first_name, reason, banned_by):
    """Банит пользователя"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO bans (user_id, username, first_name, reason, banned_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, reason, banned_by))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка бана пользователя {user_id}: {e}")
        return False

def unban_user(user_id):
    """Разбанивает пользователя"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM bans WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Ошибка разбана пользователя {user_id}: {e}")
        return False

# ====== КЛАВИАТУРА МЕНЮ ======
def get_main_keyboard(user_id):
    """Возвращает основную клавиатуру в зависимости от роли пользователя"""
    if is_admin(user_id):
        keyboard = [
            [KeyboardButton("📊 Статистика"), KeyboardButton("📋 Правила")],
            [KeyboardButton("📨 Отправить пост"), KeyboardButton("💬 Чат")]
        ]
    else:
        keyboard = [
            [KeyboardButton("📋 Правила"), KeyboardButton("📨 Отправить пост")],
            [KeyboardButton("💬 Чат")]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ====== НАСТРОЙКА МЕНЮ КОМАНД ======
async def setup_commands(application):
    """Настраивает меню команд для разных типов пользователей"""
    try:
        # Команды для ОБЫЧНЫХ пользователей
        user_commands = [
            BotCommand("start", "Запустить бота"),
        ]
        
        # Команды для АДМИНОВ
        admin_commands = [
            BotCommand("start", "Запустить бота"),
            BotCommand("stats", "Статистика"),
            BotCommand("admins", "Список команды"),
            BotCommand("approve", "Одобрить (ответ)"),
        ]
        
        # Устанавливаем команды для всех пользователей
        await application.bot.set_my_commands(user_commands)
        
        # Дополнительно для админов (нужен user_id админа)
        # await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
        
        logger.info("✅ Меню команд настроено")
    except Exception as e:
        logger.error(f"Ошибка настройки команд: {e}")

# ====== КОМАНДА /START ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        role = get_user_role(user_id)
        
        # Сохраняем информацию о пользователе
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name, role) VALUES (?, ?, ?, ?)',
                      (user_id, username, first_name, 'user'))
        conn.commit()
        conn.close()
        
        log_user_action(user_id, username, "start_command", f"role: {role}")
        
        # Приветственное сообщение
        if role in ["main_admin", "admin"]:
            welcome_text = f"""🎯 <b>Добро пожаловать, {first_name}!</b>

Вы вошли как администратор.

Используйте меню ниже для навигации.

💡 По всем вопросам: @markizuw"""
        else:
            welcome_text = f"""🎯 <b>Привет, {first_name}!</b>

Добро пожаловать в бота для публикации постов в канале.

Используйте меню ниже для навигации."""
        
        # Отправляем сообщение с клавиатурой
        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка в команде /start: {e}")

# ====== ОБРАБОТКА КНОПОК КЛАВИАТУРЫ ======
async def handle_keyboard_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия на кнопки клавиатуры"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        text = update.message.text
        
        if text == "📊 Статистика":
            if not is_admin(user_id):
                log_user_action(user_id, username, "tried_stats", "попытка посмотреть статистику")
                await update.message.reply_text("❌ У вас нет прав для просмотра статистики")
                return
            
            await show_statistics(update, context)
        
        elif text == "📋 Правила":
            log_user_action(user_id, username, "viewed_rules_keyboard")
            
            rules_text = """📋 <b>Правила публикации</b>

<b>❌ Что запрещено:</b>
• Реклама в предложении
• Материалы 18+
• Слив личной информации

<b>⏳ Модерация:</b>
За несоблюдение правил - выдается бан в боте.
Все предложения проверяются администраторами.
Вы получите уведомление о результате.
Все анонимно."""
            
            await update.message.reply_text(rules_text, parse_mode='HTML')
        
        elif text == "📨 Отправить пост":
            log_user_action(user_id, username, "started_post_submission")
            
            post_instructions = """📨 <b>Отправка поста</b>

<b>📝 Формат отправки:</b>
1. Прикрепите 1-2 фотографии ИЛИ одно видео
2. Добавьте текст к вложениям
3. Отправьте и ожидайте 👇"""
            
            await update.message.reply_text(post_instructions, parse_mode='HTML')
        
        elif text == "💬 Чат":
            log_user_action(user_id, username, "viewed_chat_keyboard")
            
            chat_text = """💬 <b>Чат нашего канала</b>

Присоединяйтесь к нашему чату для общения!

<b>👇 Нажмите на кнопку ниже, чтобы присоединиться:</b>"""
            
            keyboard = [[InlineKeyboardButton("💬 Перейти в чат", url=CHAT_LINK)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(chat_text, reply_markup=reply_markup, parse_mode='HTML')
    
    except Exception as e:
        logger.error(f"Ошибка обработки кнопки клавиатуры: {e}")

# ====== ФУНКЦИЯ ДОБАВЛЕНИЯ ССЫЛОК ======
def add_links_to_caption(caption):
    """Добавляет ссылки к подписи поста"""
    links_text = f"\n\n<a href='{PEREXODNIK_LINK}'>Переходник</a> | <a href='{PREDLOZHKA_LINK}'>Предложка</a> | <a href='{CHAT_LINK}'>Чат</a>"
    return caption + links_text

# ====== ОБРАБОТКА ПРЕДЛОЖЕНИЙ ======
media_groups = {}

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return
        
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        # Проверяем, не в режиме ли рассылки
        if context.user_data.get('waiting_broadcast'):
            return
        
        # Обработка медиа для предложений
        if update.message and (update.message.photo or update.message.video):
            await handle_media_message(update, context)
        elif update.message and update.message.text:
            # Проверяем, не является ли это кнопкой клавиатуры
            text = update.message.text
            if not (text.startswith("📊") or text.startswith("📋") or text.startswith("📨") or text.startswith("💬")):
                # Если это не кнопка и не команда (не начинается с /) - это обычный текст
                if not update.message.text.startswith('/'):
                    log_user_action(user_id, username, "text_only_rejection", "пользователь отправил только текст")
                    await update.message.reply_text("❌ Нужно отправить фотографии или видео с текстом.\n\nТолько текст не принимается.")
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")

async def handle_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        
        # Проверяем, не забанен ли пользователь
        if is_banned(user_id):
            log_user_action(user_id, username, "banned_user_tried_to_submit", "забаненный пользователь попытался отправить пост")
            
            ban_info = get_ban_info(user_id)
            if ban_info:
                ban_id, _, _, _, reason, banned_by, banned_at = ban_info
                await update.message.reply_text(
                    f"🚫 <b>Вы заблокированы!</b>\n\n"
                    f"Причина: {reason}\n"
                    f"Дата блокировки: {banned_at}\n\n"
                    f"Вы не можете отправлять новые предложения.",
                    parse_mode='HTML'
                )
            else:
                await update.message.reply_text("🚫 Вы заблокированы и не можете отправлять предложения.")
            return
        
        # Обработка видео
        if update.message.video:
            if not update.message.caption:
                log_user_action(user_id, username, "video_only_rejection", "пользователь отправил только видео")
                await update.message.reply_text("❌ Добавьте текст к видео.\n\nТолько видео без текста не принимается.")
                return
            
            caption = update.message.caption.strip()
            video_id = update.message.video.file_id
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO suggestions (user_id, username, message_text, video_id, file_type, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, username, caption, video_id, 'video', 'pending'))
            
            suggestion_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            log_suggestion_action(user_id, username, "submitted_video", suggestion_id, f"текст: {caption[:50]}...")
            
            await forward_video_to_admins(context, update.message, suggestion_id, username, first_name)
            await update.message.reply_text("✅ Ваше видео отправлено на модерацию!")
            return
        
        # Обработка фото
        if update.message.photo:
            if update.message.media_group_id:
                media_group_id = update.message.media_group_id
                
                if media_group_id not in media_groups:
                    media_groups[media_group_id] = {
                        'photos': [],
                        'caption': '',
                        'user_id': user_id,
                        'username': username,
                        'first_name': first_name,
                    }
                
                media_groups[media_group_id]['photos'].append(update.message.photo[-1].file_id)
                
                if update.message.caption:
                    media_groups[media_group_id]['caption'] = update.message.caption.strip()
                
                if len(media_groups[media_group_id]['photos']) == 2:
                    await process_media_group(context, media_group_id)
                
                return
            
            else:
                if not update.message.caption:
                    log_user_action(user_id, username, "photo_only_rejection", "пользователь отправил только фото")
                    await update.message.reply_text("❌ Добавьте текст к фотографии.\n\nТолько фото без текста не принимается.")
                    return
                
                caption = update.message.caption.strip()
                file_id = update.message.photo[-1].file_id
                
                conn = get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT INTO suggestions (user_id, username, message_text, file_id, file_type, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, username, caption, file_id, 'photo', 'pending'))
                
                suggestion_id = cursor.lastrowid
                conn.commit()
                conn.close()
                
                log_suggestion_action(user_id, username, "submitted_photo", suggestion_id, f"текст: {caption[:50]}...")
                
                await forward_to_admins(context, update.message, suggestion_id, username, first_name)
                await update.message.reply_text("✅ Ваше предложение отправлено на модерацию!")
    except Exception as e:
        logger.error(f"Ошибка обработки медиа: {e}")
        try:
            await update.message.reply_text("❌ Произошла ошибка при обработке медиа. Попробуйте еще раз.")
        except:
            pass

async def process_media_group(context: ContextTypes.DEFAULT_TYPE, media_group_id: str):
    try:
        if media_group_id not in media_groups:
            return
        
        group_data = media_groups[media_group_id]
        
        # Проверяем, не забанен ли пользователь
        if is_banned(group_data['user_id']):
            try:
                await context.bot.send_message(
                    chat_id=group_data['user_id'],
                    text="🚫 Вы заблокированы и не можете отправлять предложения."
                )
            except:
                pass
            del media_groups[media_group_id]
            return
        
        if len(group_data['photos']) < 1 or not group_data['caption']:
            del media_groups[media_group_id]
            return
        
        if len(group_data['photos']) > 2:
            try:
                await context.bot.send_message(
                    chat_id=group_data['user_id'],
                    text="❌ Можно отправить максимум 2 фотографии."
                )
            except:
                pass
            del media_groups[media_group_id]
            return
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if len(group_data['photos']) == 2:
            cursor.execute('''
                INSERT INTO suggestions (user_id, username, message_text, file_id, file_id_2, file_type, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (group_data['user_id'], group_data['username'], group_data['caption'], 
                  group_data['photos'][0], group_data['photos'][1], 'photo', 'pending'))
        else:
            cursor.execute('''
                INSERT INTO suggestions (user_id, username, message_text, file_id, file_type, status)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (group_data['user_id'], group_data['username'], group_data['caption'], 
                  group_data['photos'][0], 'photo', 'pending'))
        
        suggestion_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        log_suggestion_action(group_data['user_id'], group_data['username'], "submitted_media_group", suggestion_id, f"текст: {group_data['caption'][:50]}...")
        
        await send_media_group_to_admins(context, suggestion_id, group_data)
        
        try:
            await context.bot.send_message(
                chat_id=group_data['user_id'],
                text="✅ Ваше предложение отправлено на модерацию!"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя: {e}")
        
        del media_groups[media_group_id]
    except Exception as e:
        logger.error(f"Ошибка обработки медиагруппы: {e}")

async def forward_to_admins(context: ContextTypes.DEFAULT_TYPE, message, suggestion_id: int, username: str, first_name: str):
    try:
        admins = get_admins()
        
        username_display = f"@{username}" if username else first_name
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT status FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
        conn.close()
        
        status = suggestion_data[0] if suggestion_data else 'pending'
        
        if status != 'pending':
            return
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{suggestion_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{suggestion_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for admin in admins:
            try:
                forwarded_msg = await message.forward(chat_id=admin)
                await context.bot.send_message(
                    chat_id=admin,
                    text=f"📨 Одобрить предложение от {username_display}?",
                    reply_to_message_id=forwarded_msg.message_id,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка отправки админу {admin}: {e}")
    except Exception as e:
        logger.error(f"Ошибка пересылки админам: {e}")

async def forward_video_to_admins(context: ContextTypes.DEFAULT_TYPE, message, suggestion_id: int, username: str, first_name: str):
    try:
        admins = get_admins()
        
        username_display = f"@{username}" if username else first_name
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT status FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
        conn.close()
        
        status = suggestion_data[0] if suggestion_data else 'pending'
        
        if status != 'pending':
            return
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{suggestion_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{suggestion_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for admin in admins:
            try:
                forwarded_msg = await message.forward(chat_id=admin)
                await context.bot.send_message(
                    chat_id=admin,
                    text=f"📨 Одобрить видео от {username_display}?",
                    reply_to_message_id=forwarded_msg.message_id,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка отправки админу {admin}: {e}")
    except Exception as e:
        logger.error(f"Ошибка пересылки видео админам: {e}")

async def send_media_group_to_admins(context: ContextTypes.DEFAULT_TYPE, suggestion_id: int, group_data: dict):
    try:
        admins = get_admins()
        
        username_display = f"@{group_data['username']}" if group_data['username'] else group_data['first_name']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT status FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
        conn.close()
        
        status = suggestion_data[0] if suggestion_data else 'pending'
        
        if status != 'pending':
            return
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{suggestion_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{suggestion_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if len(group_data['photos']) == 2:
            media_group = [
                InputMediaPhoto(media=group_data['photos'][0], caption=f"📨 Предложение от {username_display}\n\n{group_data['caption']}"),
                InputMediaPhoto(media=group_data['photos'][1])
            ]
        else:
            media_group = [
                InputMediaPhoto(media=group_data['photos'][0], caption=f"📨 Предложение от {username_display}\n\n{group_data['caption']}")
            ]
        
        for admin in admins:
            try:
                sent_messages = await context.bot.send_media_group(chat_id=admin, media=media_group)
                await context.bot.send_message(
                    chat_id=admin,
                    text=f"📨 Одобрить предложение от {username_display}?",
                    reply_to_message_id=sent_messages[0].message_id,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Ошибка отправки админу {admin}: {e}")
    except Exception as e:
        logger.error(f"Ошибка отправки медиагруппы админам: {e}")

# ====== ОБРАБОТКА КНОПОК ======
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        user_id = query.from_user.id
        username = query.from_user.username
        data = query.data
        
        # Логируем нажатие кнопки для отладки
        logger.info(f"🔘 Кнопка нажата: user_id={user_id}, username={username}, data={data}")
        
        # ВАЖНО: Обязательно отвечаем на callback_query перед обработкой
        await query.answer()
        
        if data.startswith('approve_'):
            if not is_admin(user_id):
                try:
                    await query.edit_message_text("❌ Нет прав для модерации")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")
                return
            await approve_suggestion(query, context)
        elif data.startswith('reject_'):
            if not is_admin(user_id):
                try:
                    await query.edit_message_text("❌ Нет прав для модерации")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")
                return
            await reject_suggestion(query, context)
        elif data == "show_bans_details":
            if not is_admin(user_id):
                await query.answer("❌ Нет прав", show_alert=True)
                return
            await show_bans_details(query, context)
        elif data == "back_to_stats":
            if not is_admin(user_id):
                await query.answer("❌ Нет прав", show_alert=True)
                return
            
            # Показываем статистику
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM suggestions')
            total = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM suggestions WHERE status = "pending"')
            pending = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM suggestions WHERE status = "approved"')
            approved = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM suggestions WHERE status = "rejected"')
            rejected = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM users WHERE role = "main_admin"')
            main_admins = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM users WHERE role = "admin"')
            admins = cursor.fetchone()[0]
            
            cursor.execute('SELECT COUNT(*) FROM bans')
            banned_count = cursor.fetchone()[0]
            
            conn.close()
            
            stats_text = f"""📊 <b>Статистика</b>

📨 <b>Предложения:</b>
• Всего: <code>{total}</code>
• ⏳ Ожидают: <code>{pending}</code>
• ✅ Опубликовано: <code>{approved}</code>
• ❌ Отклонено: <code>{rejected}</code>

👥 <b>Команда:</b>
• 👑 Главные админы: <code>{main_admins}</code>
• 🔧 Админы: <code>{admins}</code>

🚫 <b>Заблокированные пользователи:</b>
• Всего: <code>{banned_count}</code>"""
            
            keyboard = [[InlineKeyboardButton("📋 Детали банов", callback_data="show_bans_details")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='HTML')
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение: {e}")
        elif data == "add_admin":
            if not is_main_admin(user_id):
                await query.answer("❌ Только главный админ может добавлять администраторов", show_alert=True)
                return
            await query.edit_message_text(
                "👤 <b>Добавление администратора</b>\n\n"
                "Введите ID пользователя, которого хотите назначить администратором.\n\n"
                "<b>Пример:</b>\n"
                "<code>123456789</code>",
                parse_mode='HTML'
            )
            return WAITING_ADD_ADMIN
        elif data == "remove_admin":
            if not is_main_admin(user_id):
                await query.answer("❌ Только главный админ может удалять администраторов", show_alert=True)
                return
            await query.edit_message_text(
                "🗑️ <b>Удаление администратора</b>\n\n"
                "Введите ID администратора, которого хотите удалить.\n\n"
                "<b>Пример:</b>\n"
                "<code>123456789</code>",
                parse_mode='HTML'
            )
            return WAITING_REMOVE_ADMIN
    except Exception as e:
        logger.error(f"Ошибка обработки кнопки: {e}")

async def approve_suggestion(query, context: ContextTypes.DEFAULT_TYPE):
    try:
        suggestion_id = int(query.data.split('_')[1])
        user_id = query.from_user.id
        username = query.from_user.username
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT status, user_id, username, file_type, message_text FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
        
        if not suggestion_data:
            try:
                await query.edit_message_text("❌ Предложение не найдено")
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение: {e}")
            conn.close()
            return
        
        status, author_id, author_username, file_type, message_text = suggestion_data
        
        if status != 'pending':
            if status == 'approved':
                try:
                    await query.edit_message_text("✅ Это предложение уже было одобрено другим администратором")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")
            elif status == 'rejected':
                try:
                    await query.edit_message_text("❌ Это предложение уже было отклонено другим администратором")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")
            conn.close()
            return
        
        cursor.execute('UPDATE suggestions SET status = ?, moderated_by = ? WHERE id = ?', 
                      ('approved', user_id, suggestion_id))
        
        conn.commit()
        
        if file_type == 'video':
            cursor.execute('SELECT video_id FROM suggestions WHERE id = ?', (suggestion_id,))
            suggestion = cursor.fetchone()
            
            if not suggestion:
                try:
                    await query.edit_message_text("❌ Предложение не найдено")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")
                conn.close()
                return
            
            video_id = suggestion[0]
            
            try:
                # Добавляем ссылки к подписи
                caption_with_links = add_links_to_caption(message_text)
                sent_message = await context.bot.send_video(chat_id=CHANNEL_CHAT_ID, video=video_id, caption=caption_with_links, parse_mode='HTML')
                channel_message_id = sent_message.message_id
                
                cursor.execute('UPDATE suggestions SET channel_message_id = ? WHERE id = ?', 
                              (channel_message_id, suggestion_id))
                conn.commit()
                
                log_admin_action(user_id, username, "approved_video", details=f"suggestion_id: {suggestion_id}")
                
                author_info = f"{author_id}"
                if author_username:
                    author_info += f" | @{author_username}"
                
                try:
                    await query.edit_message_text(
                        f"✅ <b>Видео опубликовано в канале!</b>\n\n"
                        f"📋 ID предложения: <code>{suggestion_id}</code>\n"
                        f"👤 Автор: <code>{author_info}</code>",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")
                
                # Уведомляем пользователя
                try:
                    await context.bot.send_message(
                        chat_id=author_id,
                        text=f"🎉 <b>Ваше предложение одобрено и опубликовано в канале!</b>\n\n",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить пользователя {author_id}: {e}")
                
            except Exception as e:
                error_msg = f"❌ Ошибка публикации видео: {str(e)}"
                log_admin_action(user_id, username, "approve_video_error", details=f"suggestion_id: {suggestion_id}, error: {str(e)}")
                try:
                    await query.edit_message_text(error_msg)
                except Exception as edit_error:
                    logger.warning(f"Не удалось отредактировать сообщение: {edit_error}")
        
        else:
            cursor.execute('SELECT file_id, file_id_2 FROM suggestions WHERE id = ?', (suggestion_id,))
            suggestion = cursor.fetchone()
            
            if not suggestion:
                try:
                    await query.edit_message_text("❌ Предложение не найдено")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")
                conn.close()
                return
            
            file_id, file_id_2 = suggestion
            
            try:
                if file_id_2:
                    # Добавляем ссылки к подписи для медиагруппы
                    caption_with_links = add_links_to_caption(message_text)
                    media_group = [
                        InputMediaPhoto(media=file_id, caption=caption_with_links, parse_mode='HTML'),
                        InputMediaPhoto(media=file_id_2)
                    ]
                    sent_messages = await context.bot.send_media_group(chat_id=CHANNEL_CHAT_ID, media=media_group)
                    channel_message_id = sent_messages[0].message_id
                else:
                    # Добавляем ссылки к подписи для одиночного фото
                    caption_with_links = add_links_to_caption(message_text)
                    sent_message = await context.bot.send_photo(chat_id=CHANNEL_CHAT_ID, photo=file_id, caption=caption_with_links, parse_mode='HTML')
                    channel_message_id = sent_message.message_id
                
                cursor.execute('UPDATE suggestions SET channel_message_id = ? WHERE id = ?', 
                              (channel_message_id, suggestion_id))
                conn.commit()
                
                log_admin_action(user_id, username, "approved_suggestion", details=f"suggestion_id: {suggestion_id}")
                
                author_info = f"{author_id}"
                if author_username:
                    author_info += f" | @{author_username}"
                
                try:
                    await query.edit_message_text(
                        f"✅ <b>Предложение опубликовано в канале!</b>\n\n"
                        f"📋 ID предложения: <code>{suggestion_id}</code>\n"
                        f"👤 Автор: <code>{author_info}</code>",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")
                
                # Уведомляем пользователя
                try:
                    await context.bot.send_message(
                        chat_id=author_id,
                        text=f"🎉 <b>Ваше предложение одобрено и опубликовано в канале!</b>\n\n",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить пользователя {author_id}: {e}")
                
            except Exception as e:
                error_msg = f"❌ Ошибка публикации: {str(e)}"
                log_admin_action(user_id, username, "approve_error", details=f"suggestion_id: {suggestion_id}, error: {str(e)}")
                try:
                    await query.edit_message_text(error_msg)
                except Exception as edit_error:
                    logger.warning(f"Не удалось отредактировать сообщение: {edit_error}")
        
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка одобрения предложения: {e}")

async def reject_suggestion(query, context: ContextTypes.DEFAULT_TYPE):
    try:
        suggestion_id = int(query.data.split('_')[1])
        user_id = query.from_user.id
        username = query.from_user.username
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT status, user_id, username FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
        
        if not suggestion_data:
            try:
                await query.edit_message_text("❌ Предложение не найдено")
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение: {e}")
            conn.close()
            return
        
        status, author_id, author_username = suggestion_data
        
        if status != 'pending':
            if status == 'approved':
                try:
                    await query.edit_message_text("✅ Это предложение уже было одобрено другим администратором")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")
            elif status == 'rejected':
                try:
                    await query.edit_message_text("❌ Это предложение уже было отклонено другим администратором")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")
            conn.close()
            return
        
        cursor.execute('UPDATE suggestions SET status = ?, moderated_by = ? WHERE id = ?', 
                      ('rejected', user_id, suggestion_id))
        
        conn.commit()
        conn.close()
        
        log_admin_action(user_id, username, "rejected_suggestion", details=f"suggestion_id: {suggestion_id}")
        
        author_info = f"{author_id}"
        if author_username:
            author_info += f" | @{author_username}"
        
        try:
            await query.edit_message_text(
                f"❌ <b>Предложение отклонено</b>\n\n"
                f"📋 ID предложения: <code>{suggestion_id}</code>\n"
                f"👤 Автор: <code>{author_info}</code>",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
        
        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=author_id,
                text=f"😔 <b>Ваше предложение было отклонено модератором.</b>\n\n"
                     f"Вы можете отправить новое предложение, соблюдая правила публикации.",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {author_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка отклонения предложения: {e}")

# ====== КОМАНДА /STATS ======
async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            log_user_action(user_id, username, "tried_stats", "попытка посмотреть статистику")
            await update.message.reply_text("❌ У вас нет прав для просмотра этой команды")
            return
        
        log_admin_action(user_id, username, "viewed_stats")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Статистика предложений
        cursor.execute('SELECT COUNT(*) FROM suggestions')
        total = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM suggestions WHERE status = "pending"')
        pending = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM suggestions WHERE status = "approved"')
        approved = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM suggestions WHERE status = "rejected"')
        rejected = cursor.fetchone()[0]
        
        # Статистика команды
        cursor.execute('SELECT COUNT(*) FROM users WHERE role = "main_admin"')
        main_admins = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM users WHERE role = "admin"')
        admins = cursor.fetchone()[0]
        
        # Статистика банов
        cursor.execute('SELECT COUNT(*) FROM bans')
        banned_count = cursor.fetchone()[0]
        
        conn.close()
        
        stats_text = f"""📊 <b>Статистика</b>

📨 <b>Предложения:</b>
• Всего: <code>{total}</code>
• ⏳ Ожидают: <code>{pending}</code>
• ✅ Опубликовано: <code>{approved}</code>
• ❌ Отклонено: <code>{rejected}</code>

👥 <b>Команда:</b>
• 👑 Главные админы: <code>{main_admins}</code>
• 🔧 Админы: <code>{admins}</code>

🚫 <b>Заблокированные пользователи:</b>
• Всего: <code>{banned_count}</code>"""
        
        keyboard = [[InlineKeyboardButton("📋 Детали банов", callback_data="show_bans_details")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(stats_text, reply_markup=reply_markup, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка команды stats: {e}")

async def show_bans_details(query, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную информацию о банах"""
    try:
        user_id = query.from_user.id
        username = query.from_user.username
        
        if not is_admin(user_id):
            await query.answer("❌ Нет прав", show_alert=True)
            return
        
        banned_users = get_banned_users()
        
        if not banned_users:
            bans_text = "🚫 <b>Нет заблокированных пользователей</b>"
        else:
            bans_text = f"🚫 <b>Заблокированные пользователи ({len(banned_users)}):</b>\n\n"
            
            for i, ban in enumerate(banned_users, 1):
                ban_id, user_id_ban, username_ban, first_name, reason, banned_by, banned_at = ban
                
                username_display = f"@{username_ban}" if username_ban else first_name
                
                # Получаем информацию о админе
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT username FROM users WHERE user_id = ?', (banned_by,))
                admin_info = cursor.fetchone()
                conn.close()
                
                admin_username = admin_info[0] if admin_info else "Неизвестно"
                admin_display = f"@{admin_username}" if admin_username else f"ID: {banned_by}"
                
                bans_text += f"<b>{i}. {username_display}</b>\n"
                bans_text += f"├ ID: <code>{user_id_ban}</code>\n"
                bans_text += f"├ Причина: {reason or 'Не указана'}\n"
                bans_text += f"├ Забанен: {admin_display}\n"
                bans_text += f"└ Дата: {banned_at}\n\n"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад к статистике", callback_data="back_to_stats")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(bans_text, reply_markup=reply_markup, parse_mode='HTML')
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
    except Exception as e:
        logger.error(f"Ошибка показа деталей банов: {e}")

# ====== АДМИНИСТРИРОВАНИЕ ======
async def admins_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            log_user_action(user_id, username, "tried_admins_list", "попытка просмотреть список админов")
            await update.message.reply_text("❌ У вас нет прав для просмотра этой команды")
            return
        
        log_admin_action(user_id, username, "viewed_admins_list")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, role, added_date FROM users WHERE role != "user" ORDER BY role, added_date')
        users_data = cursor.fetchall()
        conn.close()
        
        if not users_data:
            await update.message.reply_text("❌ Нет назначенных пользователей")
            return
        
        users_text = "👥 <b>Список админов</b>\n\n"
        
        roles_data = {}
        for user in users_data:
            user_id_db, username_db, role, added_date = user
            if role not in roles_data:
                roles_data[role] = []
            roles_data[role].append((user_id_db, username_db, added_date))
        
        if "main_admin" in roles_data:
            users_text += "👑 <b>Главный Админ</b>\n"
            for user_id_db, username_db, added_date in roles_data["main_admin"]:
                users_text += f"├ ID: <code>{user_id_db}</code>\n"
                username_display = f"@{username_db}" if username_db else "Без username"
                users_text += f"├ {username_display}\n"
                users_text += f"└ Дата: <code>{added_date[:10]}</code>\n\n"
        
        if "admin" in roles_data:
            users_text += "🔧 <b>Администраторы:</b>\n\n"
            for user_id_db, username_db, added_date in roles_data["admin"]:
                users_text += "💎 <b>Админ</b>\n"
                users_text += f"├ ID: <code>{user_id_db}</code>\n"
                username_display = f"@{username_db}" if username_db else "Без username"
                users_text += f"├ {username_display}\n"
                users_text += f"└ Дата: <code>{added_date[:10]}</code>\n\n"
        
        if is_main_admin(user_id):
            keyboard = [
                [InlineKeyboardButton("👤 Добавить администратора", callback_data="add_admin")],
                [InlineKeyboardButton("🗑️ Удалить администратора", callback_data="remove_admin")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(users_text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await update.message.reply_text(users_text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка команды admins: {e}")

async def handle_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает добавление администратора"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_main_admin(user_id):
            log_user_action(user_id, username, "tried_add_admin", "попытка добавить администратора")
            await update.message.reply_text("❌ Нет прав")
            return ConversationHandler.END
        
        text = update.message.text.strip()
        
        try:
            target_user_id = int(text)
            
            # Проверяем, существует ли уже такой администратор
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT role FROM users WHERE user_id = ?', (target_user_id,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                if existing_user[0] in ['admin', 'main_admin']:
                    await update.message.reply_text("❌ Этот пользователь уже является администратором")
                    conn.close()
                    return ConversationHandler.END
                else:
                    # Обновляем роль существующего пользователя
                    cursor.execute('UPDATE users SET role = "admin" WHERE user_id = ?', (target_user_id,))
            else:
                # Пытаемся получить информацию о пользователе
                try:
                    user_info = await context.bot.get_chat(target_user_id)
                    target_username = user_info.username
                    first_name = user_info.first_name or "Пользователь"
                except Exception as e:
                    logger.error(f"Не удалось получить информацию о пользователе {target_user_id}: {e}")
                    target_username = None
                    first_name = "Пользователь"
                
                cursor.execute('INSERT INTO users (user_id, username, first_name, role) VALUES (?, ?, ?, ?)',
                             (target_user_id, target_username, first_name, 'admin'))
            
            conn.commit()
            conn.close()
            
            log_admin_action(user_id, username, "added_admin", target_user_id)
            
            await update.message.reply_text(
                f"✅ <b>Администратор успешно добавлен!</b>\n\n"
                f"ID: <code>{target_user_id}</code>",
                parse_mode='HTML'
            )
            
            # Уведомляем нового администратора
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🎉 <b>Вам назначена новая роль: Администратор!</b>\n\n"
                         f"Используйте /start для просмотра доступных функций.\n\n"
                         f"Ваш ID: <code>{target_user_id}</code>",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя {target_user_id}: {e}")
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. ID должен быть числом.")
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка добавления администратора: {e}")
        return ConversationHandler.END

async def handle_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает удаление администратора"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_main_admin(user_id):
            log_user_action(user_id, username, "tried_remove_admin", "попытка удалить администратора")
            await update.message.reply_text("❌ Нет прав")
            return ConversationHandler.END
        
        text = update.message.text.strip()
        
        try:
            target_user_id = int(text)
            
            if target_user_id == ADMIN_CHAT_ID:
                await update.message.reply_text("❌ Нельзя удалить главного администратора")
                return ConversationHandler.END
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT role, username, first_name FROM users WHERE user_id = ? AND role = "admin"', (target_user_id,))
            user_data = cursor.fetchone()
            
            if not user_data:
                await update.message.reply_text("❌ Администратор с таким ID не найден")
                conn.close()
                return ConversationHandler.END
            
            role, target_username, first_name = user_data
            cursor.execute('UPDATE users SET role = "user" WHERE user_id = ?', (target_user_id,))
            conn.commit()
            conn.close()
            
            username_display = f"@{target_username}" if target_username else first_name
            
            log_admin_action(user_id, username, "removed_admin", target_user_id)
            
            await update.message.reply_text(
                f"✅ <b>Администратор удален из команды!</b>\n\n"
                f"ID: <code>{target_user_id}</code>\n"
                f"Пользователь: {username_display}",
                parse_mode='HTML'
            )
            
            # Уведомляем бывшего администратора
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text="ℹ️ Ваша роль в боте была изменена на обычного пользователя."
                )
            except:
                pass
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. ID должен быть числом.")
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка удаления администратора: {e}")
        return ConversationHandler.END

# ====== КОМАНДА /BAN ======
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для блокировки пользователя"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            log_user_action(user_id, username, "tried_ban", "попытка использовать команду ban")
            await update.message.reply_text("❌ У вас нет прав для использования этой команды")
            return
        
        if not context.args:
            await update.message.reply_text(
                "🚫 <b>Использование команды /ban</b>\n\n"
                "<b>Формат:</b>\n"
                "<code>/ban ID_пользователя причина</code>\n\n"
                "<b>Пример:</b>\n"
                "<code>/ban 123456789 Нарушение правил сообщества</code>",
                parse_mode='HTML'
            )
            return
        
        if len(context.args) < 2:
            await update.message.reply_text("❌ Укажите ID пользователя и причину бана")
            return
        
        try:
            target_user_id = int(context.args[0])
            reason = ' '.join(context.args[1:])
            
            # Проверяем, не баним ли мы админа
            if is_admin(target_user_id):
                await update.message.reply_text("❌ Нельзя заблокировать администратора")
                return
            
            # Проверяем, не забанен ли уже пользователь
            if is_banned(target_user_id):
                await update.message.reply_text("❌ Этот пользователь уже заблокирован")
                return
            
            # Пытаемся получить информацию о пользователе
            try:
                user_info = await context.bot.get_chat(target_user_id)
                target_username = user_info.username
                first_name = user_info.first_name or "Пользователь"
            except Exception as e:
                logger.error(f"Не удалось получить информацию о пользователе {target_user_id}: {e}")
                target_username = None
                first_name = "Пользователь"
            
            # Баним пользователя
            if ban_user(target_user_id, target_username, first_name, reason, user_id):
                log_ban_action(user_id, username, "banned_user", target_user_id, reason)
                
                username_display = f"@{target_username}" if target_username else first_name
                
                await update.message.reply_text(
                    f"🚫 <b>Пользователь заблокирован!</b>\n\n"
                    f"ID: <code>{target_user_id}</code>\n"
                    f"Пользователь: {username_display}\n"
                    f"Причина: {reason}",
                    parse_mode='HTML'
                )
                
                # Уведомляем пользователя о блокировке
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"🚫 <b>Вы были заблокированы в боте!</b>\n\n"
                             f"Причина: {reason}\n"
                             f"Вы не можете отправлять новые предложения.\n\n"
                             f"По вопросам обращайтесь к администраторам.",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить пользователя {target_user_id}: {e}")
            else:
                await update.message.reply_text("❌ Произошла ошибка при блокировке пользователя")
                
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. ID должен быть числом.")
        except Exception as e:
            logger.error(f"Ошибка команды ban: {e}")
            await update.message.reply_text("❌ Произошла ошибка при выполнении команды")
            
    except Exception as e:
        logger.error(f"Ошибка команды ban: {e}")

# ====== КОМАНДА /UNBAN ======
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для разблокировки пользователя"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            log_user_action(user_id, username, "tried_unban", "попытка использовать команду unban")
            await update.message.reply_text("❌ У вас нет прав для использования этой команды")
            return
        
        if not context.args:
            await update.message.reply_text(
                "✅ <b>Использование команды /unban</b>\n\n"
                "<b>Формат:</b>\n"
                "<code>/unban ID_пользователя</code>\n\n"
                "<b>Пример:</b>\n"
                "<code>/unban 123456789</code>",
                parse_mode='HTML'
            )
            return
        
        try:
            target_user_id = int(context.args[0])
            
            # Проверяем, забанен ли пользователь
            if not is_banned(target_user_id):
                await update.message.reply_text("❌ Этот пользователь не заблокирован")
                return
            
            # Разбаниваем пользователя
            if unban_user(target_user_id):
                log_ban_action(user_id, username, "unbanned_user", target_user_id)
                
                # Получаем информацию о пользователе
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT username, first_name FROM users WHERE user_id = ?', (target_user_id,))
                user_info = cursor.fetchone()
                conn.close()
                
                if user_info:
                    target_username, first_name = user_info
                    username_display = f"@{target_username}" if target_username else first_name
                else:
                    username_display = f"ID: {target_user_id}"
                
                await update.message.reply_text(
                    f"✅ <b>Пользователь разблокирован!</b>\n\n"
                    f"ID: <code>{target_user_id}</code>\n"
                    f"Пользователь: {username_display}",
                    parse_mode='HTML'
                )
                
                # Уведомляем пользователя о разблокировке
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text="✅ <b>Ваша блокировка в боте снята!</b>\n\n"
                             "Теперь вы можете снова отправлять предложения.",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить пользователя {target_user_id}: {e}")
            else:
                await update.message.reply_text("❌ Произошла ошибка при разблокировке пользователя")
                
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. ID должен быть числом.")
        except Exception as e:
            logger.error(f"Ошибка команды unban: {e}")
            await update.message.reply_text("❌ Произошла ошибка при выполнении команды")
            
    except Exception as e:
        logger.error(f"Ошибка команды unban: {e}")

# ====== КОМАНДА /APPROVE ======
async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скрытая команда для админов - одобрение через ответ на сообщение"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            log_user_action(user_id, username, "tried_hidden_approve", "попытка использовать скрытую команду")
            await update.message.reply_text("❌ У вас нет прав для использования этой команды")
            return
        
        if not update.message.reply_to_message:
            log_admin_action(user_id, username, "hidden_approve_no_reply", "команда без ответа на сообщение")
            await update.message.reply_text("❌ Ответьте на сообщение с предложением для его одобрения")
            return
        
        reply_msg = update.message.reply_to_message
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if reply_msg.photo:
            caption = reply_msg.caption or ""
            if "Предложение от" in caption:
                cursor.execute('SELECT id, status, file_type FROM suggestions WHERE message_text LIKE ?', (f"%{caption.split('Предложение от')[-1].strip()}%",))
            else:
                cursor.execute('SELECT id, status, file_type FROM suggestions WHERE message_text = ?', (caption,))
        elif reply_msg.video:
            caption = reply_msg.caption or ""
            cursor.execute('SELECT id, status, file_type FROM suggestions WHERE message_text = ?', (caption,))
        else:
            text = reply_msg.text or ""
            if "Одобрить предложение от" in text:
                username_part = text.split("Одобрить предложение от")[-1].split("?")[0].strip()
                cursor.execute('SELECT id, status, file_type FROM suggestions WHERE username = ? OR first_name = ?', 
                              (username_part.replace('@', ''), username_part))
            else:
                cursor.execute('SELECT id, status, file_type FROM suggestions WHERE message_text = ?', (text,))
        
        suggestion_data = cursor.fetchone()
        
        if not suggestion_data:
            log_admin_action(user_id, username, "hidden_approve_not_found", "предложение не найдено в базе")
            await update.message.reply_text("❌ Не удалось найти предложение в базе данных")
            conn.close()
            return
        
        suggestion_id, status, file_type = suggestion_data
        
        if status == 'approved':
            log_admin_action(user_id, username, "hidden_approve_already_approved", f"suggestion_id: {suggestion_id}")
            await update.message.reply_text("✅ Это предложение уже было одобрено")
            conn.close()
            return
        
        if file_type == 'video':
            cursor.execute('SELECT message_text, video_id, user_id, username FROM suggestions WHERE id = ?', (suggestion_id,))
            suggestion = cursor.fetchone()
            
            if not suggestion:
                await update.message.reply_text("❌ Предложение не найдено")
                conn.close()
                return
            
            message_text, video_id, author_id, author_username = suggestion
            
            try:
                # Добавляем ссылки к подписи
                caption_with_links = add_links_to_caption(message_text)
                sent_message = await context.bot.send_video(chat_id=CHANNEL_CHAT_ID, video=video_id, caption=caption_with_links, parse_mode='HTML')
                channel_message_id = sent_message.message_id
                
                cursor.execute('UPDATE suggestions SET status = ?, moderated_by = ?, channel_message_id = ? WHERE id = ?', 
                              ('approved', user_id, channel_message_id, suggestion_id))
                
                conn.commit()
                
                log_admin_action(user_id, username, "hidden_approve_video_success", f"suggestion_id: {suggestion_id}")
                await update.message.reply_text("✅ Видео опубликовано в канале через скрытую команду!")
                
                # Уведомляем пользователя
                try:
                    await context.bot.send_message(
                        chat_id=author_id,
                        text=f"🎉 <b>Ваше предложение одобрено и опубликовано в канале!</b>\n\n"
                             f"ID предложения: <code>{suggestion_id}</code>",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить пользователя {author_id}: {e}")
                
            except Exception as e:
                error_msg = f"❌ Ошибка публикации видео: {str(e)}"
                log_admin_action(user_id, username, "hidden_approve_video_error", f"suggestion_id: {suggestion_id}, error: {str(e)}")
                await update.message.reply_text(error_msg)
        
        else:
            cursor.execute('SELECT message_text, file_id, file_id_2, user_id, username FROM suggestions WHERE id = ?', (suggestion_id,))
            suggestion = cursor.fetchone()
            
            if not suggestion:
                await update.message.reply_text("❌ Предложение не найдено")
                conn.close()
                return
            
            message_text, file_id, file_id_2, author_id, author_username = suggestion
            
            try:
                if file_id_2:
                    # Добавляем ссылки к подписи для медиагруппы
                    caption_with_links = add_links_to_caption(message_text)
                    media_group = [
                        InputMediaPhoto(media=file_id, caption=caption_with_links, parse_mode='HTML'),
                        InputMediaPhoto(media=file_id_2)
                    ]
                    sent_messages = await context.bot.send_media_group(chat_id=CHANNEL_CHAT_ID, media=media_group)
                    channel_message_id = sent_messages[0].message_id
                else:
                    # Добавляем ссылки к подписи для одиночного фото
                    caption_with_links = add_links_to_caption(message_text)
                    sent_message = await context.bot.send_photo(chat_id=CHANNEL_CHAT_ID, photo=file_id, caption=caption_with_links, parse_mode='HTML')
                    channel_message_id = sent_message.message_id
                
                cursor.execute('UPDATE suggestions SET status = ?, moderated_by = ?, channel_message_id = ? WHERE id = ?', 
                              ('approved', user_id, channel_message_id, suggestion_id))
                
                conn.commit()
                
                log_admin_action(user_id, username, "hidden_approve_success", f"suggestion_id: {suggestion_id}")
                await update.message.reply_text("✅ Предложение опубликовано в канале через скрытую команду!")
                
                # Уведомляем пользователя
                try:
                    await context.bot.send_message(
                        chat_id=author_id,
                        text=f"🎉 <b>Ваше предложение одобрено и опубликовано в канале!</b>\n\n"
                             f"ID предложения: <code>{suggestion_id}</code>",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить пользователя {author_id}: {e}")
                
            except Exception as e:
                error_msg = f"❌ Ошибка публикации: {str(e)}"
                log_admin_action(user_id, username, "hidden_approve_error", f"suggestion_id: {suggestion_id}, error: {str(e)}")
                await update.message.reply_text(error_msg)
        
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка скрытой команды approve: {e}")

# ====== КОМАНДА /DELETE ======
async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для удаления поста с канала"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            log_user_action(user_id, username, "tried_hidden_delete", "попытка использовать скрытую команду")
            await update.message.reply_text("❌ У вас нет прав для использования этой команды")
            return
        
        if not update.message.reply_to_message:
            log_admin_action(user_id, username, "hidden_delete_no_reply", "команда без ответа на сообщение")
            await update.message.reply_text("❌ Ответьте на сообщение с предложением для его удаления")
            return
        
        reply_msg = update.message.reply_to_message
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if reply_msg.photo:
            caption = reply_msg.caption or ""
            if "Предложение от" in caption:
                cursor.execute('SELECT id, channel_message_id, status FROM suggestions WHERE message_text LIKE ?', 
                              (f"%{caption.split('Предложение от')[-1].strip()}%",))
            else:
                cursor.execute('SELECT id, channel_message_id, status FROM suggestions WHERE message_text = ?', 
                              (caption,))
        elif reply_msg.video:
            caption = reply_msg.caption or ""
            cursor.execute('SELECT id, channel_message_id, status FROM suggestions WHERE message_text = ?', 
                          (caption,))
        else:
            text = reply_msg.text or ""
            if "Одобрить предложение от" in text:
                username_part = text.split("Одобрить предложение от")[-1].split("?")[0].strip()
                cursor.execute('SELECT id, channel_message_id, status FROM suggestions WHERE username = ? OR first_name = ?', 
                              (username_part.replace('@', ''), username_part))
            else:
                cursor.execute('SELECT id, channel_message_id, status FROM suggestions WHERE message_text = ?', 
                              (text,))
        
        suggestion_data = cursor.fetchone()
        
        if not suggestion_data:
            log_admin_action(user_id, username, "hidden_delete_not_found", "предложение не найдено в базе")
            await update.message.reply_text("❌ Не удалось найти предложение в базе данных")
            conn.close()
            return
        
        suggestion_id, channel_message_id, status = suggestion_data
        
        if status != 'approved':
            log_admin_action(user_id, username, "hidden_delete_not_approved", f"suggestion_id: {suggestion_id}")
            await update.message.reply_text("❌ Это предложение не было опубликовано в канале")
            conn.close()
            return
        
        if not channel_message_id:
            await update.message.reply_text("❌ ID сообщения в канале не найден")
            conn.close()
            return
        
        try:
            await context.bot.delete_message(chat_id=CHANNEL_CHAT_ID, message_id=channel_message_id)
            
            cursor.execute('UPDATE suggestions SET status = ? WHERE id = ?', ('deleted', suggestion_id))
            conn.commit()
            
            log_admin_action(user_id, username, "hidden_delete_success", f"suggestion_id: {suggestion_id}")
            await update.message.reply_text(
                f"✅ <b>Пост удален с канала!</b>\n\n"
                f"📋 ID предложения: <code>{suggestion_id}</code>\n"
                f"🗑️ Статус изменен на: <code>deleted</code>",
                parse_mode='HTML'
            )
            
        except Exception as e:
            error_msg = f"❌ Ошибка удаления: {str(e)}"
            log_admin_action(user_id, username, "hidden_delete_error", f"suggestion_id: {suggestion_id}, error: {str(e)}")
            await update.message.reply_text(error_msg)
        
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка команды delete: {e}")

# ====== КОМАНДА /BROADCAST ======
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            log_user_action(user_id, username, "tried_broadcast", "попытка использовать рассылку")
            await update.message.reply_text("❌ У вас нет прав для использования этой команды")
            return
        
        log_admin_action(user_id, username, "broadcast_started")
        
        await update.message.reply_text(
            "📢 <b>Режим рассылки</b>\n\n"
            "Отправьте сообщение для рассылки всем пользователям.\n"
            "Можно отправить:\n"
            "• Текст\n"
            "• Фото с текстом\n"
            "• Видео с текстом\n"
            "• Документы\n\n"
            "Для отмены отправьте /cancel",
            parse_mode='HTML'
        )
        
        context.user_data['waiting_broadcast'] = True
        return WAITING_BROADCAST
    except Exception as e:
        logger.error(f"Ошибка начала рассылки: {e}")
        return ConversationHandler.END

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            context.user_data['waiting_broadcast'] = False
            return ConversationHandler.END
        
        users = get_all_users()
        success_count = 0
        fail_count = 0
        
        if not users:
            await update.message.reply_text("❌ Нет пользователей для рассылки")
            context.user_data['waiting_broadcast'] = False
            return ConversationHandler.END
        
        status_msg = await update.message.reply_text(
            f"📢 <b>Начинаю рассылку...</b>\n\n"
            f"Всего пользователей: <code>{len(users)}</code>\n"
            f"Отправитель (вы) исключен из рассылки.",
            parse_mode='HTML'
        )
        
        for user in users:
            # Исключаем отправителя из рассылки
            if user == user_id:
                continue
                
            try:
                if update.message.text:
                    await context.bot.send_message(chat_id=user, text=update.message.text)
                elif update.message.photo:
                    await context.bot.send_photo(
                        chat_id=user,
                        photo=update.message.photo[-1].file_id,
                        caption=update.message.caption
                    )
                elif update.message.video:
                    await context.bot.send_video(
                        chat_id=user,
                        video=update.message.video.file_id,
                        caption=update.message.caption
                    )
                elif update.message.document:
                    await context.bot.send_document(
                        chat_id=user,
                        document=update.message.document.file_id,
                        caption=update.message.caption
                    )
                success_count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                fail_count += 1
                logger.warning(f"Не удалось отправить пользователю {user}: {e}")
        
        log_admin_action(user_id, username, "broadcast_completed", 
                        details=f"success: {success_count}, failed: {fail_count}")
        
        context.user_data['waiting_broadcast'] = False
        
        await status_msg.edit_text(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"📊 Статистика:\n"
            f"✅ Успешно: <code>{success_count}</code>\n"
            f"❌ Ошибок: <code>{fail_count}</code>\n"
            f"👤 Отправитель исключен из рассылки.",
            parse_mode='HTML'
        )
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка рассылки: {e}")
        context.user_data['waiting_broadcast'] = False
        return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['waiting_broadcast'] = False
        await update.message.reply_text("❌ Рассылка отменена")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Ошибка отмены рассылки: {e}")
        return ConversationHandler.END

# ====== ОБРАБОТЧИК НЕИЗВЕСТНЫХ КОМАНД ======
async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает неизвестные команды"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        # Получаем текст команды
        command_text = update.message.text
        
        # Проверяем, является ли это командой
        if command_text.startswith('/'):
            # Логируем попытку использовать неизвестную команду
            log_user_action(user_id, username, "unknown_command", f"команда: {command_text}")
            
            # Проверяем, является ли это админской командой
            if command_text in ['/stats', '/admins', '/approve', '/delete', '/ban', '/unban', '/broadcast']:
                # Если пользователь не админ, сообщаем об отсутствии прав
                if not is_admin(user_id):
                    await update.message.reply_text("❌ У вас нет прав для использования этой команды")
                    return
                else:
                    # Админ пытается использовать команду, которая должна быть в меню
                    # Просто пропускаем - команда уже обрабатывается в своих обработчиках
                    return
            
            # Для всех остальных неизвестных команд
            await update.message.reply_text("❌ Неизвестная команда. Используйте /start для начала работы.")
    except Exception as e:
        logger.error(f"Ошибка обработки неизвестной команды: {e}")

# ====== ОБРАБОТЧИКИ ОШИБОК ======
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает все неперехваченные ошибки"""
    try:
        error = context.error
        
        if isinstance(error, Conflict):
            logger.warning("⚠️ Конфликт: Возможно запущено несколько экземпляров бота")
            return
        
        if isinstance(error, (NetworkError, TimedOut)):
            logger.warning(f"⚠️ Сетевая ошибка: {type(error).__name__}")
            # Добавляем небольшую задержку при сетевых ошибках
            await asyncio.sleep(2)
            return
        
        logger.error(f"Ошибка при обработке обновления {update}: {error}")
        
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "❌ Произошла ошибка. Пожалуйста, попробуйте позже."
                )
            except:
                pass
    except Exception as e:
        logger.error(f"Ошибка в обработчике ошибок: {e}")

# ====== НАСТРОЙКА КОМАНД ======
async def set_bot_commands_simple():
    """Простая настройка команд бота без использования Application"""
    try:
        # Команды для всех пользователей
        user_commands = [
            BotCommand("start", "Запустить бота"),
        ]
        
        # Создаем временный бот для настройки команд
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        await bot.set_my_commands(user_commands)
        await bot.close()
        
        logger.info("✅ Команды бота настроены")
    except Exception as e:
        logger.warning(f"Не удалось настроить команды бота: {e}")

# ====== ЗАПУСК ======
def main():
    # Проверяем наличие других экземпляров (только для предупреждения)
    has_other_instance = check_running_instances()
    
    import atexit
    atexit.register(cleanup_lock_file)
    
    try:
        init_db()
        
        # Создаем и запускаем event loop для настройки команд
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(set_bot_commands_simple())
        
        # Закрываем loop после использования
        loop.close()
        
        # Теперь создаем и запускаем основное приложение
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_error_handler(error_handler)
        
        # Conversation handler для рассылки
        broadcast_handler = ConversationHandler(
            entry_points=[CommandHandler("broadcast", broadcast_start)],
            states={
                WAITING_BROADCAST: [
                    MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL, broadcast_message),
                    CommandHandler("cancel", broadcast_cancel)
                ]
            },
            fallbacks=[CommandHandler("cancel", broadcast_cancel)],
            per_message=False
        )
        
        # Conversation handler для добавления администратора
        add_admin_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern='^add_admin$')],
            states={
                WAITING_ADD_ADMIN: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_admin)
                ]
            },
            fallbacks=[CommandHandler("cancel", broadcast_cancel)],
            per_message=False
        )
        
        # Conversation handler для удаления администратора
        remove_admin_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(button_handler, pattern='^remove_admin$')],
            states={
                WAITING_REMOVE_ADMIN: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_admin)
                ]
            },
            fallbacks=[CommandHandler("cancel", broadcast_cancel)],
            per_message=False
        )
        
        application.add_handler(broadcast_handler)
        application.add_handler(add_admin_handler)
        application.add_handler(remove_admin_handler)
        
        # Команды
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stats", show_statistics))
        application.add_handler(CommandHandler("admins", admins_list))
        application.add_handler(CommandHandler("approve", approve_command))
        application.add_handler(CommandHandler("delete", delete_command))
        application.add_handler(CommandHandler("ban", ban_command))
        application.add_handler(CommandHandler("unban", unban_command))
        
        # Обработчик неизвестных команд (должен быть ПОСЛЕ всех известных команд)
        application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
        
        # Обработчики кнопок клавиатуры
        application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^(📊 Статистика|📋 Правила|📨 Отправить пост|💬 Чат)$'), handle_keyboard_buttons))
        
        # Обработчики медиа сообщений
        application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_user_message))
        
        # Обработчики текстовых сообщений (не команд)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))
        
        # Обработчики кнопок (модерация и другие)
        application.add_handler(CallbackQueryHandler(button_handler))
        
        print("=" * 60)
        print("🤖 Бот запущен и готов к работе!")
        if has_other_instance:
            print("⚠️  ПРЕДУПРЕЖДЕНИЕ: Возможно есть другие запущенные экземпляры")
            print("   Это может вызвать конфликты при обработке сообщений!")
        print("=" * 60)
        print("🔧 ОСНОВНЫЕ ФУНКЦИИ:")
        print("   ✅ Модерация предложений (фото/видео + текст)")
        print("   ✅ Постоянное меню с кнопками в поле сообщения")
        print("   ✅ Поддержка фото (1-2) и видео (1)")
        print("   ✅ Правила публикации через кнопку")
        print("   ✅ Чат канала через кнопку")
        print("   ✅ Ссылки в постах: Переходник | Предложка | Чат")
        print("   ✅ Система банов пользователей")
        print("   ✅ Уведомления пользователям о результатах модерации")
        print("   ✅ Управление администраторов (для главного админа)")
        print("   ✅ Рассылка с исключением отправителя")
        print("")
        print("📝 МЕНЮ КОМАНД:")
        print("   Для всех пользователей: только /start")
        print("   Команды админов (вводятся вручную):")
        print("   /stats - статистика")
        print("   /admins - список команды")
        print("   /approve - одобрить (ответ на сообщение)")
        print("   /delete - удалить с канала (ответ на сообщение)")
        print("   /ban - заблокировать пользователя")
        print("   /unban - разблокировать пользователя")
        print("   /broadcast - рассылка сообщений")
        print("")
        print("🔗 ССЫЛКИ В ПОСТАХ:")
        print(f"   Переходник: {PEREXODNIK_LINK}")
        print(f"   Предложка: {PREDLOZHKA_LINK}")
        print(f"   Чат: {CHAT_LINK}")
        print("")
        print("🚫 СИСТЕМА БАНОВ:")
        print("   /ban ID_пользователя причина - заблокировать")
        print("   /unban ID_пользователя - разблокировать")
        print("   Пользователи получают уведомления о бане/разбане")
        print("   Статистика банов доступна в /stats")
        print("")
        print("👥 УПРАВЛЕНИЕ АДМИНАМИ (только главный админ):")
        print("   Кнопки 'Добавить администратора' и 'Удалить администратора'")
        print("   в списке команды (/admins)")
        print("")
        print("💡 Для остановки бота нажмите Ctrl+C")
        print("=" * 60)
        
        application.run_polling(
            poll_interval=1.0,
            timeout=20,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
        print(f"❌ Бот остановлен из-за ошибки: {e}")
    finally:
        cleanup_lock_file()

if __name__ == '__main__':
    main()
