import logging
import sqlite3
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from datetime import datetime

# ====== НАСТРОЙКИ ======
BOT_TOKEN = "8418277065:AAHsRqkGYoqZH2gI68yKRNe-Dp731Qxs4Js"
ADMIN_CHAT_ID = 8069781607  # Ваш chat_id
CHANNEL_CHAT_ID = "-1002556198303"  # ID вашего канала

# ====== НАСТРОЙКА ЛОГИРОВАНИЯ ======
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Уменьшаем спам в консоли от библиотек
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
                raise e

def init_db():
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
            status TEXT DEFAULT 'pending',
            moderated_by INTEGER,
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
    
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name, role) VALUES (?, ?, ?, ?)',
                  (ADMIN_CHAT_ID, "svitbandit", "Главный администратор", "main_admin"))
    
    # Добавляем колонку moderated_by если она не существует
    try:
        cursor.execute("SELECT moderated_by FROM suggestions LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE suggestions ADD COLUMN moderated_by INTEGER")
        logger.info("✅ Добавлена колонка moderated_by в таблицу suggestions")
    
    conn.commit()
    conn.close()

# ====== ПРОВЕРКА ПРАВ ======
def get_user_role(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "user"

def is_admin(user_id):
    role = get_user_role(user_id)
    return role in ["admin", "main_admin"]

def is_main_admin(user_id):
    return get_user_role(user_id) == "main_admin"

def get_admins():
    """Получает список админов"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE role IN ("admin", "main_admin")')
    admins = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    # Фильтруем только существующих админов
    valid_admins = []
    for admin_id in admins:
        if isinstance(admin_id, int) and admin_id > 0:
            valid_admins.append(admin_id)
    
    return valid_admins

# ====== КОМАНДА /START ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    role = get_user_role(user_id)
    
    # Получаем информацию о пользователе для приветствия
    first_name = update.effective_user.first_name
    
    log_user_action(user_id, username, "start_command", f"role: {role}")
    
    if role == "main_admin":
        welcome_text = f"""
🎯 Привет, {first_name}!

⚡ Ваши команды:
/stats - статистика
/admins - список команды

💡 По поводу бота - @markizuw
        """
    elif role == "admin":
        welcome_text = f"""
🎯 Привет, {first_name}!

⚡ Ваши команды:
/stats - статистика
/admins - список команды

💡 По поводу бота - @markizuw
        """
    else:
        welcome_text = f"""
🎯 Привет, {first_name}!

📸 Что можно отправить:
• 1-2 фотографии с текстом

❌ Что нельзя отправлять:
• Только текст без фото
• Только фото без текста
• Более 2 фотографий
        """
    
    await update.message.reply_text(welcome_text)

# ====== ОБРАБОТКА ПРЕДЛОЖЕНИЙ ======
media_groups = {}

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверяем, что update.message существует
    if not update.message:
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # Проверяем команды управления пользователями от главного админа
    if is_main_admin(user_id):
        text = update.message.text.strip()
        
        if ' ' in text:
            try:
                parts = text.split(' ')
                if len(parts) == 2:
                    target_user_id = int(parts[0])
                    role = parts[1].lower()
                    if role in ['admin']:
                        await handle_add_user_command(update, context, target_user_id, role)
                        return
            except ValueError:
                pass
        
        try:
            target_user_id = int(text)
            await handle_remove_user_command(update, context, target_user_id)
            return
        except ValueError:
            pass
    
    # Обработка фото для предложений (только для обычных пользователей)
    if update.message and update.message.photo:
        await handle_photo_message(update, context)
    elif update.message and update.message.text and not update.message.text.startswith('/'):
        # Для админов не показываем ошибку, они могут отправлять текст
        if not is_admin(user_id):
            log_user_action(user_id, username, "text_only_rejection", "пользователь отправил только текст")
            await update.message.reply_text("❌ Нужно отправить фотографии с текстом.\n\nТолько текст не принимается.")

async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name
    
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
            INSERT INTO suggestions (user_id, username, message_text, file_id, file_id_2, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, caption, file_id, None, 'pending'))
        
        suggestion_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        log_suggestion_action(user_id, username, "submitted", suggestion_id, f"текст: {caption[:50]}...")
        
        await forward_to_admins(context, update.message, suggestion_id, username, first_name)
        await update.message.reply_text("✅ Ваше предложение отправлено на модерацию!")

async def process_media_group(context: ContextTypes.DEFAULT_TYPE, media_group_id: str):
    if media_group_id not in media_groups:
        return
    
    group_data = media_groups[media_group_id]
    
    if len(group_data['photos']) < 2 or not group_data['caption']:
        del media_groups[media_group_id]
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO suggestions (user_id, username, message_text, file_id, file_id_2, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (group_data['user_id'], group_data['username'], group_data['caption'], 
          group_data['photos'][0], group_data['photos'][1], 'pending'))
    
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

async def forward_to_admins(context: ContextTypes.DEFAULT_TYPE, message, suggestion_id: int, username: str, first_name: str):
    admins = get_admins()
    
    username_display = f"@{username}" if username else first_name
    
    # Проверяем статус предложения
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем существование колонки moderated_by
    try:
        cursor.execute('SELECT status, moderated_by FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
    except sqlite3.OperationalError:
        # Если колонки moderated_by нет, используем старый запрос
        cursor.execute('SELECT status FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
        if suggestion_data:
            suggestion_data = (suggestion_data[0], None)
    
    conn.close()
    
    status = suggestion_data[0] if suggestion_data else 'pending'
    moderated_by = suggestion_data[1] if suggestion_data else None
    
    if status != 'pending':
        return  # Предложение уже модерировано
    
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

async def send_media_group_to_admins(context: ContextTypes.DEFAULT_TYPE, suggestion_id: int, group_data: dict):
    admins = get_admins()
    
    username_display = f"@{group_data['username']}" if group_data['username'] else group_data['first_name']
    
    # Проверяем статус предложения
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем существование колонки moderated_by
    try:
        cursor.execute('SELECT status, moderated_by FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
    except sqlite3.OperationalError:
        # Если колонки moderated_by нет, используем старый запрос
        cursor.execute('SELECT status FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
        if suggestion_data:
            suggestion_data = (suggestion_data[0], None)
    
    conn.close()
    
    status = suggestion_data[0] if suggestion_data else 'pending'
    moderated_by = suggestion_data[1] if suggestion_data else None
    
    if status != 'pending':
        return  # Предложение уже модерировано
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{suggestion_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{suggestion_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    media_group = [
        InputMediaPhoto(media=group_data['photos'][0], caption=f"📨 Предложение от {username_display}\n\n{group_data['caption']}"),
        InputMediaPhoto(media=group_data['photos'][1])
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

# ====== ОБРАБОТКА КНОПОК ======
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username
    data = query.data
    
    # Убираем query.answer() чтобы избежать таймаутов
    
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

async def approve_suggestion(query, context: ContextTypes.DEFAULT_TYPE):
    suggestion_id = int(query.data.split('_')[1])
    user_id = query.from_user.id
    username = query.from_user.username
    
    # Проверяем, не было ли уже принято решение по этому предложению
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем существование колонки moderated_by
    try:
        cursor.execute('SELECT status, moderated_by FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
    except sqlite3.OperationalError:
        # Если колонки moderated_by нет, используем старый запрос
        cursor.execute('SELECT status FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
        if suggestion_data:
            suggestion_data = (suggestion_data[0], None)
    
    if not suggestion_data:
        try:
            await query.edit_message_text("❌ Предложение не найдено")
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
        conn.close()
        return
    
    status, moderated_by = suggestion_data
    
    if status != 'pending':
        # Предложение уже модерировано
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
    
    # Обновляем статус и записываем кто модерировал
    try:
        cursor.execute('UPDATE suggestions SET status = ?, moderated_by = ? WHERE id = ?', 
                      ('approved', user_id, suggestion_id))
    except sqlite3.OperationalError:
        # Если колонки moderated_by нет, обновляем только статус
        cursor.execute('UPDATE suggestions SET status = ? WHERE id = ?', 
                      ('approved', suggestion_id))
    
    conn.commit()
    
    cursor.execute('SELECT message_text, file_id, file_id_2 FROM suggestions WHERE id = ?', (suggestion_id,))
    suggestion = cursor.fetchone()
    
    if not suggestion:
        try:
            await query.edit_message_text("❌ Предложение не найдено")
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
        conn.close()
        return
    
    message_text, file_id, file_id_2 = suggestion
    
    try:
        if file_id_2:
            media_group = [
                InputMediaPhoto(media=file_id, caption=message_text),
                InputMediaPhoto(media=file_id_2)
            ]
            await context.bot.send_media_group(chat_id=CHANNEL_CHAT_ID, media=media_group)
        else:
            await context.bot.send_photo(chat_id=CHANNEL_CHAT_ID, photo=file_id, caption=message_text)
        
        log_admin_action(user_id, username, "approved_suggestion", details=f"suggestion_id: {suggestion_id}")
        try:
            await query.edit_message_text("✅ Предложение опубликовано в канале!")
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
        
    except Exception as e:
        error_msg = f"❌ Ошибка публикации: {str(e)}"
        log_admin_action(user_id, username, "approve_error", details=f"suggestion_id: {suggestion_id}, error: {str(e)}")
        try:
            await query.edit_message_text(error_msg)
        except Exception as edit_error:
            logger.warning(f"Не удалось отредактировать сообщение: {edit_error}")
    
    conn.close()

async def reject_suggestion(query, context: ContextTypes.DEFAULT_TYPE):
    suggestion_id = int(query.data.split('_')[1])
    user_id = query.from_user.id
    username = query.from_user.username
    
    # Проверяем, не было ли уже принято решение по этому предложению
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверяем существование колонки moderated_by
    try:
        cursor.execute('SELECT status, moderated_by FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
    except sqlite3.OperationalError:
        # Если колонки moderated_by нет, используем старый запрос
        cursor.execute('SELECT status FROM suggestions WHERE id = ?', (suggestion_id,))
        suggestion_data = cursor.fetchone()
        if suggestion_data:
            suggestion_data = (suggestion_data[0], None)
    
    if not suggestion_data:
        try:
            await query.edit_message_text("❌ Предложение не найдено")
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
        conn.close()
        return
    
    status, moderated_by = suggestion_data
    
    if status != 'pending':
        # Предложение уже модерировано
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
    
    # Обновляем статус и записываем кто модерировал
    try:
        cursor.execute('UPDATE suggestions SET status = ?, moderated_by = ? WHERE id = ?', 
                      ('rejected', user_id, suggestion_id))
    except sqlite3.OperationalError:
        # Если колонки moderated_by нет, обновляем только статус
        cursor.execute('UPDATE suggestions SET status = ? WHERE id = ?', 
                      ('rejected', suggestion_id))
    
    conn.commit()
    conn.close()
    
    log_admin_action(user_id, username, "rejected_suggestion", details=f"suggestion_id: {suggestion_id}")
    try:
        await query.edit_message_text("❌ Предложение отклонено")
    except Exception as e:
        logger.warning(f"Не удалось отредактировать сообщение: {e}")

# ====== СКРЫТАЯ КОМАНДА /APPROVE ДЛЯ ГЛАВНОГО АДМИНА ======
async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скрытая команда для главного админа - одобрение через ответ на сообщение"""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    if not is_main_admin(user_id):
        log_user_action(user_id, username, "tried_hidden_approve", "попытка использовать скрытую команду")
        return  # Просто игнорируем для не-главных админов
    
    if not update.message.reply_to_message:
        log_admin_action(user_id, username, "hidden_approve_no_reply", "команда без ответа на сообщение")
        return
    
    # Получаем ID предложения из пересланного сообщения
    reply_msg = update.message.reply_to_message
    
    # Ищем предложение в базе данных по тексту сообщения
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if reply_msg.photo:
        # Если это фото с текстом
        caption = reply_msg.caption or ""
        if "Предложение от" in caption:
            # Это наше служебное сообщение с кнопками
            cursor.execute('SELECT id, status FROM suggestions WHERE message_text LIKE ?', (f"%{caption.split('Предложение от')[-1].strip()}%",))
        else:
            # Это оригинальное сообщение пользователя
            cursor.execute('SELECT id, status FROM suggestions WHERE message_text = ?', (caption,))
    else:
        # Если это текстовое сообщение
        text = reply_msg.text or ""
        if "Одобрить предложение от" in text:
            # Это наше служебное сообщение с кнопками
            username_part = text.split("Одобрить предложение от")[-1].split("?")[0].strip()
            cursor.execute('SELECT id, status FROM suggestions WHERE username = ? OR first_name = ?', 
                          (username_part.replace('@', ''), username_part))
        else:
            # Это оригинальное сообщение пользователя
            cursor.execute('SELECT id, status FROM suggestions WHERE message_text = ?', (text,))
    
    suggestion_data = cursor.fetchone()
    
    if not suggestion_data:
        log_admin_action(user_id, username, "hidden_approve_not_found", "предложение не найдено в базе")
        await update.message.reply_text("❌ Не удалось найти предложение в базе данных")
        conn.close()
        return
    
    suggestion_id, status = suggestion_data
    
    if status == 'approved':
        log_admin_action(user_id, username, "hidden_approve_already_approved", f"suggestion_id: {suggestion_id}")
        await update.message.reply_text("✅ Это предложение уже было одобрено")
        conn.close()
        return
    
    # Одобряем предложение
    cursor.execute('SELECT message_text, file_id, file_id_2 FROM suggestions WHERE id = ?', (suggestion_id,))
    suggestion = cursor.fetchone()
    
    if not suggestion:
        await update.message.reply_text("❌ Предложение не найдено")
        conn.close()
        return
    
    message_text, file_id, file_id_2 = suggestion
    
    try:
        if file_id_2:
            media_group = [
                InputMediaPhoto(media=file_id, caption=message_text),
                InputMediaPhoto(media=file_id_2)
            ]
            await context.bot.send_media_group(chat_id=CHANNEL_CHAT_ID, media=media_group)
        else:
            await context.bot.send_photo(chat_id=CHANNEL_CHAT_ID, photo=file_id, caption=message_text)
        
        # Обновляем статус
        try:
            cursor.execute('UPDATE suggestions SET status = ?, moderated_by = ? WHERE id = ?', 
                          ('approved', user_id, suggestion_id))
        except sqlite3.OperationalError:
            cursor.execute('UPDATE suggestions SET status = ? WHERE id = ?', 
                          ('approved', suggestion_id))
        
        conn.commit()
        
        log_admin_action(user_id, username, "hidden_approve_success", f"suggestion_id: {suggestion_id}")
        await update.message.reply_text("✅ Предложение опубликовано в канале через скрытую команду!")
        
    except Exception as e:
        error_msg = f"❌ Ошибка публикации: {str(e)}"
        log_admin_action(user_id, username, "hidden_approve_error", f"suggestion_id: {suggestion_id}, error: {str(e)}")
        await update.message.reply_text(error_msg)
    
    conn.close()

# ====== АДМИНИСТРИРОВАНИЕ ======
async def admins_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    users_text = "👥 Список команды\n\n"
    
    roles_data = {}
    for user in users_data:
        user_id, username, role, added_date = user
        if role not in roles_data:
            roles_data[role] = []
        roles_data[role].append((user_id, username, added_date))
    
    if "main_admin" in roles_data:
        users_text += "👑 Главный Админ\n"
        for user_id, username, added_date in roles_data["main_admin"]:
            users_text += f"• ID: {user_id}\n"
            username_display = f"@{username}" if username else "Без username"
            users_text += f"• {username_display}\n"
            users_text += f"• Дата: {added_date[:10]}\n\n"
    
    if "admin" in roles_data:
        users_text += "🔧 Администраторы:\n\n"
        for user_id, username, added_date in roles_data["admin"]:
            users_text += "💎 Админ\n"
            users_text += f"• ID: {user_id}\n"
            username_display = f"@{username}" if username else "Без username"
            users_text += f"• {username_display}\n"
            users_text += f"• Дата: {added_date[:10]}\n\n"
    
    if is_main_admin(user_id):
        keyboard = [
            [InlineKeyboardButton("👤 Добавить пользователя", callback_data="add_user")],
            [InlineKeyboardButton("🗑️ Удалить пользователя", callback_data="remove_user")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(users_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(users_text)

async def button_handler_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    username = query.from_user.username
    
    if not is_main_admin(user_id):
        log_user_action(user_id, username, "tried_admin_buttons", "попытка использовать админ-кнопки")
        try:
            await query.edit_message_text("❌ Только главный администратор может управлять пользователями")
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
        return
    
    data = query.data
    
    log_admin_action(user_id, username, "admin_button_click", details=f"button: {data}")
    
    # Убираем query.answer() чтобы избежать таймаутов
    
    if data == "add_user":
        try:
            await query.edit_message_text(
                "👤 Введите ID пользователя и роль в формате:\n"
                "ID РОЛЬ\n\n"
                "Пример:\n"
                "123456789 admin - добавить админа\n\n"
                "Доступные роли:\n"
                "• admin - Администратор"
            )
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")
    
    elif data == "remove_user":
        try:
            await query.edit_message_text("🗑️ Отправьте ID пользователя, которого хотите удалить из команды:")
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение: {e}")

async def handle_add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int, role: str):
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    if not is_main_admin(user_id):
        log_user_action(user_id, username, "tried_add_user", f"попытка добавить пользователя {target_user_id}")
        await update.message.reply_text("❌ Нет прав")
        return
    
    target_username = None
    first_name = "Пользователь"
    user_exists = True
    
    try:
        user_info = await context.bot.get_chat(target_user_id)
        target_username = user_info.username
        first_name = user_info.first_name or "Пользователь"
    except Exception as e:
        logger.error(f"Не удалось получить информацию о пользователе {target_user_id}: {e}")
        user_exists = False
        
        if update.message.reply_to_message and update.message.reply_to_message.forward_from:
            forwarded_user = update.message.reply_to_message.forward_from
            target_username = forwarded_user.username
            first_name = forwarded_user.first_name or "Пользователь"
            user_exists = True
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (user_id, username, first_name, role) VALUES (?, ?, ?, ?)', (target_user_id, target_username, first_name, role))
    conn.commit()
    conn.close()
    
    role_names = {"admin": "💎 Админ"}
    username_display = f"@{target_username}" if target_username else "Без username"
    
    success_message = (
        f"✅ Пользователь успешно добавлен!\n\n"
        f"• ID: {target_user_id}\n"
        f"• Должность: {role_names[role]}\n"
        f"• Username: {username_display}\n"
        f"• Имя: {first_name}"
    )
    
    if not user_exists:
        success_message += f"\n\n⚠️ Не удалось проверить существование пользователя"
    
    log_admin_action(user_id, username, "added_user", target_user_id, f"role: {role}, username: {username_display}")
    await update.message.reply_text(success_message)
    
    notification_sent = False
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"🎉 Вам назначена новая роль: {role_names[role]}!\n\n"
                 f"Используйте /start для просмотра доступных команд.\n\n"
                 f"Ваш ID: {target_user_id}"
        )
        notification_sent = True
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {target_user_id}: {e}")
        error_message = "Неизвестная ошибка"
        if "Chat not found" in str(e):
            error_message = "пользователь не найден (возможно, ID неверный или пользователь никогда не писал боту)"
        elif "bot was blocked" in str(e):
            error_message = "пользователь заблокировал бота"
        elif "user is deactivated" in str(e):
            error_message = "учетная запись пользователя удалена"
        
        await update.message.reply_text(
            f"ℹ️ Не удалось отправить уведомление пользователю:\n"
            f"{target_user_id} - {error_message}\n\n"
            f"Роль назначена, но пользователь не будет уведомлен."
        )
    
    if notification_sent:
        try:
            await update.message.reply_text(f"📨 Уведомление отправлено пользователю {target_user_id}")
        except:
            pass

async def handle_remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int):
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    if not is_main_admin(user_id):
        log_user_action(user_id, username, "tried_remove_user", f"попытка удалить пользователя {target_user_id}")
        await update.message.reply_text("❌ Нет прав")
        return
    
    if target_user_id == ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Нельзя удалить главного администратора")
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT role, username FROM users WHERE user_id = ? AND role != "user"', (target_user_id,))
    user_data = cursor.fetchone()
    
    if not user_data:
        await update.message.reply_text("❌ Пользователь с такой ролью не найден")
        conn.close()
        return
    
    role, target_username = user_data
    cursor.execute('UPDATE users SET role = "user" WHERE user_id = ?', (target_user_id,))
    conn.commit()
    conn.close()
    
    role_names = {"main_admin": "👑 Главный Админ", "admin": "💎 Админ"}
    
    log_admin_action(user_id, username, "removed_user", target_user_id, f"бывшая роль: {role}")
    await update.message.reply_text(
        f"✅ Пользователь удален из команды!\n\n"
        f"• ID: {target_user_id}\n"
        f"• Бывшая должность: {role_names.get(role, role)}"
    )
    
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text="ℹ️ Ваша роль в боте была изменена на обычного пользователя."
        )
    except:
        pass

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    if not is_admin(user_id):
        log_user_action(user_id, username, "tried_stats", "попытка посмотреть статистику")
        await update.message.reply_text("❌ У вас нет прав для просмотра этой команды")
        return
    
    log_admin_action(user_id, username, "viewed_stats")
    
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
    
    conn.close()
    
    stats_text = f"""📊 Статистика

📨 Предложений:
• Всего: {total}
• ⏳ Ожидают: {pending}
• ✅ Опубликовано: {approved}
• ❌ Отклонено: {rejected}

👥 Команда:
• 👑 Главные админы: {main_admins}
• 🔧 Админы: {admins}"""
    
    await update.message.reply_text(stats_text)

# ====== ЗАПУСК ======
def main():
    try:
        init_db()
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Команды
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("admins", admins_list))
        application.add_handler(CommandHandler("approve", approve_command))  # Скрытая команда
        
        # Обработчики сообщений
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message))
        application.add_handler(MessageHandler(filters.PHOTO, handle_user_message))
        
        # Обработчики кнопок
        application.add_handler(CallbackQueryHandler(button_handler_admin, pattern='^(add_user|remove_user)$'))
        application.add_handler(CallbackQueryHandler(button_handler, pattern='^(approve_|reject_)'))
        
        print("🤖 Бот запущен и готов к работе!")
        print("🔧 ОСНОВНЫЕ ФУНКЦИИ:")
        print("   ✅ Модерация предложений (фото + текст)")
        print("   ✅ Защита от повторной модерации")
        print("   ✅ Скрытая команда /approve для главного админа")
        print("   ✅ Подробное логирование всех действий")
        print("")
        print("📝 ЛОГИРОВАНИЕ ВКЛЮЧЕНО:")
        print("   👤 Действия пользователей")
        print("   🔧 Действия администраторов")
        print("   📨 Действия с предложениями")
        print("")
        print("⚡ СКРЫТАЯ КОМАНДА:")
        print("   /approve - ответьте на предложение этой командой для принудительной публикации")
        
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")

if __name__ == '__main__':
    import asyncio

    main()