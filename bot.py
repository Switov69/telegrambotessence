import logging
import sqlite3
import time
import asyncio
import sys
import os
import html
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, BotCommand, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.error import NetworkError, TimedOut, BadRequest, Forbidden, Conflict

# ====== НАСТРОЙКИ ======
BOT_TOKEN = "8418277065:AAHsRqkGYoqZH2gI68yKRNe-Dp731Qxs4Js"
ADMIN_CHAT_ID = 1746547600  # Ваш chat_id
CHANNEL_CHAT_ID = "-1002556198303"  # ID вашего канала
CHAT_LINK = "https://t.me/+1Es8MH54mf0wNzVi"  # Ссылка на чат
PEREXODNIK_LINK = "https://t.me/sushnostinovika111"  # Ссылка на переходник
PREDLOZHKA_LINK = "https://t.me/SushnostiNovikabot"  # Ссылка на бота предложки

# Состояния для ConversationHandler
WAITING_BROADCAST = 1
WAITING_ADD_ADMIN = 2
WAITING_REMOVE_ADMIN = 3
WAITING_DELETE_REQUEST = 4

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
    level=logging.DEBUG,  # Измените на DEBUG для более подробных логов
)
logger = logging.getLogger(__name__)

# Включаем DEBUG для telegram.ext чтобы видеть все события
logging.getLogger("telegram.ext").setLevel(logging.DEBUG)
logging.getLogger("telegram").setLevel(logging.DEBUG)

# Убираем лишние логи
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

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
                banned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                ban_type TEXT DEFAULT 'permanent',
                ban_until DATETIME,
                ban_duration TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS delete_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                channel_message_id INTEGER,
                comment TEXT,
                status TEXT DEFAULT 'pending',
                processed_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS unban_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                first_name TEXT,
                reason TEXT,
                ban_until TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                sent INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('INSERT OR IGNORE INTO users (user_id, username, first_name, role) VALUES (?, ?, ?, ?)',
                      (ADMIN_CHAT_ID, "svitbandit", "Главный администратор", "main_admin"))
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

def find_suggestion_by_text(message_text: str):
    """Находит предложение в базе по тексту (с различными вариантами поиска)"""
    try:
        if not message_text or len(message_text.strip()) < 5:
            return None
            
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Очищаем текст от возможных префиксов
        clean_text = message_text.strip()
        
        # Убираем стандартные префиксы
        prefixes = [
            "Предложение от", 
            "Одобрить предложение от", 
            "📨 Предложение от", 
            "📨 Одобрить",
            "Одобрить видео от",
            "📨 Одобрить видео от"
        ]
        
        for prefix in prefixes:
            if prefix in clean_text:
                parts = clean_text.split(prefix, 1)
                if len(parts) > 1:
                    clean_text = parts[1].strip()
        
        # Убираем возможный username в начале (@username)
        if clean_text.startswith("@"):
            if " " in clean_text:
                clean_text = clean_text.split(" ", 1)[1].strip()
            elif "\n" in clean_text:
                clean_text = clean_text.split("\n", 1)[1].strip()
        
        logger.debug(f"Поиск предложения. Оригинал: '{message_text[:50]}...', Очищенный: '{clean_text[:50]}...'")
        
        # 1. Поиск точного совпадения с оригинальным текстом
        cursor.execute('''
            SELECT id, channel_message_id, status FROM suggestions 
            WHERE message_text = ? AND status = 'approved'
            LIMIT 1
        ''', (message_text,))
        
        result = cursor.fetchone()
        
        # 2. Поиск точного совпадения с очищенным текстом
        if not result and clean_text != message_text and len(clean_text) >= 5:
            cursor.execute('''
                SELECT id, channel_message_id, status FROM suggestions 
                WHERE message_text = ? AND status = 'approved'
                LIMIT 1
            ''', (clean_text,))
            result = cursor.fetchone()
        
        # 3. Поиск частичного совпадения (первые 50 символов)
        if not result and len(message_text) > 20:
            search_pattern = f"%{message_text[:50]}%"
            cursor.execute('''
                SELECT id, channel_message_id, status FROM suggestions 
                WHERE message_text LIKE ? AND status = 'approved'
                LIMIT 1
            ''', (search_pattern,))
            result = cursor.fetchone()
        
        # 4. Поиск частичного совпадения с очищенным текстом
        if not result and clean_text != message_text and len(clean_text) > 20:
            search_pattern = f"%{clean_text[:50]}%"
            cursor.execute('''
                SELECT id, channel_message_id, status FROM suggestions 
                WHERE message_text LIKE ? AND status = 'approved'
                LIMIT 1
            ''', (search_pattern,))
            result = cursor.fetchone()
        
        conn.close()
        
        if result:
            suggestion_id, channel_message_id, status = result
            logger.info(f"Найдено предложение в базе: ID={suggestion_id}, channel_msg_id={channel_message_id}")
            return result
        
        logger.info(f"Предложение не найдено по тексту: '{message_text[:50]}...'")
        return None
        
    except Exception as e:
        logger.error(f"Ошибка поиска предложения по тексту: {e}")
        return None

def save_unban_notification(user_id, username, first_name, reason, ban_until):
    """Сохраняет уведомление о разбане для отправки"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Сохраняем уведомление
        cursor.execute('''
            INSERT INTO unban_notifications (user_id, username, first_name, reason, ban_until)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, reason, ban_until))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Сохранено уведомление о разбане для пользователя {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения уведомления о разбане: {e}")

def send_pending_unban_notifications(application):
    """Отправляет все ожидающие уведомления о разбане"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получаем непосланные уведомления
        cursor.execute('''
            SELECT id, user_id, username, first_name, reason, ban_until 
            FROM unban_notifications 
            WHERE sent = 0
        ''')
        notifications = cursor.fetchall()
        
        sent_count = 0
        failed_count = 0
        
        for notification in notifications:
            notif_id, user_id, username, first_name, reason, ban_until = notification
            
            try:
                # Формируем сообщение
                message_text = f"✅ <b>Ваш временный бан истек!</b>\n\n"
                
                if reason:
                    message_text += f"Бан был выдан по причине: {reason}\n"
                
                if ban_until:
                    from datetime import datetime
                    try:
                        ban_until_dt = datetime.strptime(ban_until, '%Y-%m-%d %H:%M:%S')
                        message_text += f"Бан действовал до: {ban_until_dt.strftime('%d.%m.%Y %H:%M')}\n"
                    except:
                        pass
                
                message_text += "\nТеперь вы можете снова отправлять предложения."
                
                # Отправляем сообщение
                asyncio.create_task(
                    application.bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        parse_mode='HTML'
                    )
                )
                
                # Помечаем как отправленное
                cursor.execute('UPDATE unban_notifications SET sent = 1 WHERE id = ?', (notif_id,))
                sent_count += 1
                logger.info(f"Отправлено уведомление о разбане пользователю {user_id}")
                
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление о разбане пользователю {user_id}: {e}")
                failed_count += 1
        
        conn.commit()
        conn.close()
        
        if sent_count > 0:
            logger.info(f"Отправлено {sent_count} уведомлений о разбане")
        
        return sent_count, failed_count
        
    except Exception as e:
        logger.error(f"Ошибка отправки уведомлений о разбане: {e}")
        return 0, 0

def check_expired_bans():
    """Проверяет и удаляет истекшие баны"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        from datetime import datetime
        now = datetime.now()
        
        # Находим истекшие временные баны
        cursor.execute('SELECT user_id, username, first_name, reason, ban_until FROM bans WHERE ban_type = "temporary" AND ban_until IS NOT NULL')
        temp_bans = cursor.fetchall()
        
        expired_count = 0
        
        for ban in temp_bans:
            user_id, username, first_name, reason, ban_until = ban
            
            try:
                if ban_until:
                    ban_until_dt = datetime.strptime(ban_until, '%Y-%m-%d %H:%M:%S')
                    if now > ban_until_dt:
                        # Удаляем бан и сохраняем уведомление
                        cursor.execute('DELETE FROM bans WHERE user_id = ?', (user_id,))
                        save_unban_notification(user_id, username, first_name, reason, ban_until)
                        expired_count += 1
            except:
                continue
        
        conn.commit()
        conn.close()
        
        if expired_count > 0:
            logger.info(f"Найдено и удалено {expired_count} истекших временных банов")
        
        return expired_count
        
    except Exception as e:
        logger.error(f"Ошибка проверки истекших банов: {e}")
        return 0

# ====== ФУНКЦИИ ДЛЯ БАНОВ ======
def get_banned_users():
    """Получает список забаненных пользователей"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM bans ORDER BY banned_at DESC')
        banned_users = cursor.fetchall()
        conn.close()
        return banned_users
    except Exception as e:
        logger.error(f"Ошибка получения забаненных пользователей: {e}")
        return []

def get_temp_bans():
    """Получает список временных банов"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM bans WHERE ban_type = "temporary" ORDER BY ban_until')
        temp_bans = cursor.fetchall()
        conn.close()
        return temp_bans
    except Exception as e:
        logger.error(f"Ошибка получения временных банов: {e}")
        return []

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
        logger.error(f"Ошибка получения информации о бане пользователя {user_id}: {e}")
        return None

def ban_user(user_id, username, first_name, reason, banned_by, ban_type='permanent', ban_until=None, ban_duration=None):
    """Блокирует пользователя"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Удаляем старый бан если есть
        cursor.execute('DELETE FROM bans WHERE user_id = ?', (user_id,))
        
        # Добавляем новый бан
        cursor.execute('''
            INSERT INTO bans (user_id, username, first_name, reason, banned_by, ban_type, ban_until, ban_duration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, reason, banned_by, ban_type, ban_until, ban_duration))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Пользователь {user_id} заблокирован")
        return True
    except Exception as e:
        logger.error(f"Ошибка блокировки пользователя {user_id}: {e}")
        return False

def unban_user(user_id):
    """Разблокирует пользователя"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM bans WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        logger.info(f"Пользователь {user_id} разблокирован")
        return True
    except Exception as e:
        logger.error(f"Ошибка разблокировки пользователя {user_id}: {e}")
        return False

def is_banned(user_id):
    """Проверяет, забанен ли пользователь (учитывая временные баны)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT ban_type, ban_until, username, first_name, reason FROM bans WHERE user_id = ?', (user_id,))
        ban_info = cursor.fetchone()
        conn.close()
        
        if not ban_info:
            return False
        
        ban_type, ban_until, username, first_name, reason = ban_info
        
        if ban_type == 'permanent':
            return True
        elif ban_type == 'temporary' and ban_until:
            # Проверяем, не истек ли срок бана
            from datetime import datetime
            try:
                ban_until_dt = datetime.strptime(ban_until, '%Y-%m-%d %H:%M:%S')
                if datetime.now() > ban_until_dt:
                    # Срок бана истек, автоматически разбаниваем
                    unban_user_with_notification(user_id, username, first_name, reason, ban_until)
                    return False
                return True
            except:
                # Если ошибка парсинга даты, считаем бан действующим
                return True
        
        return True
    except Exception as e:
        logger.error(f"Ошибка проверки бана для пользователя {user_id}: {e}")
        return False

def unban_user_with_notification(user_id, username=None, first_name=None, reason=None, ban_until=None):
    """Разбанивает пользователя и отправляет уведомление"""
    try:
        # Разбаниваем пользователя
        success = unban_user(user_id)
        
        if success:
            logger.info(f"Автоматически разбанен пользователь {user_id}")
            
            # Отправляем уведомление (будет отправлено при следующем запуске бота)
            try:
                # Сохраняем информацию для уведомления в отдельной таблице или файле
                save_unban_notification(user_id, username, first_name, reason, ban_until)
            except Exception as e:
                logger.error(f"Не удалось сохранить уведомление о разбане: {e}")
            
            return True
        return False
        
    except Exception as e:
        logger.error(f"Ошибка разбана с уведомлением пользователя {user_id}: {e}")
        return False

def parse_duration(duration_str):
    """Парсит строку длительности и возвращает timedelta и человекочитаемую строку"""
    try:
        duration_str = duration_str.lower().strip()
        
        # Определяем единицу измерения
        if duration_str.endswith('m'):
            minutes = int(duration_str[:-1])
            if minutes <= 0:
                raise ValueError("Длительность должна быть положительной")
            if minutes > 10080:  # Больше 7 дней в минутах
                raise ValueError("Слишком большая длительность для минут")
            return timedelta(minutes=minutes), f"{minutes} минут"
            
        elif duration_str.endswith('h'):
            hours = int(duration_str[:-1])
            if hours <= 0:
                raise ValueError("Длительность должна быть положительной")
            if hours > 168:  # Больше 7 дней в часах
                raise ValueError("Слишком большая длительность для часов")
            return timedelta(hours=hours), f"{hours} часов"
            
        elif duration_str.endswith('d'):
            days = int(duration_str[:-1])
            if days <= 0:
                raise ValueError("Длительность должна быть положительной")
            if days > 30:  # Максимум 30 дней
                raise ValueError("Максимальная длительность - 30 дней")
            return timedelta(days=days), f"{days} дней"
            
        elif duration_str.endswith('w'):
            weeks = int(duration_str[:-1])
            if weeks <= 0:
                raise ValueError("Длительность должна быть положительной")
            if weeks > 4:  # Максимум 4 недели
                raise ValueError("Максимальная длительность - 4 недели")
            return timedelta(weeks=weeks), f"{weeks} недель"
            
        elif duration_str.endswith('mo'):
            months = int(duration_str[:-2])
            if months <= 0:
                raise ValueError("Длительность должна быть положительной")
            if months > 12:  # Максимум 12 месяцев
                raise ValueError("Максимальная длительность - 12 месяцев")
            # Приблизительно 30 дней в месяце
            return timedelta(days=months*30), f"{months} месяцев"
            
        else:
            # Пытаемся интерпретировать как количество минут по умолчанию
            try:
                minutes = int(duration_str)
                if minutes <= 0:
                    raise ValueError("Длительность должна быть положительной")
                if minutes > 10080:
                    raise ValueError("Слишком большая длительность")
                return timedelta(minutes=minutes), f"{minutes} минут"
            except ValueError:
                raise ValueError("Неверный формат длительности. Используйте: 30m, 2h, 1d, 1w, 1mo")
    except ValueError as e:
        raise ValueError(str(e))
    except Exception as e:
        raise ValueError(f"Ошибка парсинга длительности: {str(e)}")

# ====== ПРОВЕРКА ПРАВ ======
def get_user_role(user_id):
    """Получает роль пользователя из базы данных"""
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
    """Проверяет, является ли пользователь главным админом"""
    role = get_user_role(user_id)
    return role == "main_admin"

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
    """Получает ВСЕХ пользователей, которые когда-либо писали боту"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Получаем всех пользователей из таблицы users
        cursor.execute('SELECT DISTINCT user_id FROM users WHERE user_id IS NOT NULL AND user_id > 0')
        users_from_db = [row[0] for row in cursor.fetchall()]
        
        # 2. Получаем всех уникальных авторов предложений
        cursor.execute('SELECT DISTINCT user_id FROM suggestions WHERE user_id IS NOT NULL AND user_id > 0')
        suggestion_authors = [row[0] for row in cursor.fetchall()]
        
        # 3. Получаем всех забаненных пользователей (тоже могли писать)
        cursor.execute('SELECT DISTINCT user_id FROM bans WHERE user_id IS NOT NULL AND user_id > 0')
        banned_users = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        
        # Объединяем все ID, убираем дубли и сортируем
        all_users = set(users_from_db + suggestion_authors + banned_users)
        
        # Убираем None и отрицательные ID (каналы/группы)
        all_users = [user_id for user_id in all_users if user_id and user_id > 0]
        
        logger.info(f"📊 Для рассылки найдено {len(all_users)} пользователей")
        return all_users
        
    except Exception as e:
        logger.error(f"Ошибка получения списка пользователей для рассылки: {e}")
        return []

# ====== КЛАВИАТУРА МЕНЮ ======
def get_main_keyboard(user_id):
    """Возвращает основную клавиатуру в зависимости от роли пользователя"""
    if is_admin(user_id):
        keyboard = [
            [KeyboardButton("📊 Статистика"), KeyboardButton("📋 Правила")],
            [KeyboardButton("📨 Отправить пост"), KeyboardButton("🗑️ Запрос на удаление")],
            [KeyboardButton("💬 Чат")]
        ]
    else:
        keyboard = [
            [KeyboardButton("📋 Правила"), KeyboardButton("📨 Отправить пост")],
            [KeyboardButton("🗑️ Запрос на удаление")],
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
        
        # СБРАСЫВАЕМ флаг запроса на удаление при команде /start
        if context.user_data.get('waiting_delete_request', False):
            context.user_data['waiting_delete_request'] = False
            logger.info(f"Сброшен флаг waiting_delete_request при команде /start")
        
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
        
        # СБРАСЫВАЕМ флаг запроса на удаление при нажатии ЛЮБОЙ другой кнопки
        if context.user_data.get('waiting_delete_request', False):
            context.user_data['waiting_delete_request'] = False
            logger.info(f"Сброшен флаг waiting_delete_request при нажатии кнопки: {text}")
        
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
        
        elif text == "🗑️ Запрос на удаление":
            log_user_action(user_id, username, "delete_request_started")
            
            delete_request_text = """🗑️ <b>Запрос на удаление поста</b>

<b>Как это работает:</b>
Просто перешлите нужный пост из канала в чат с ботом.

<b>⚠️ Внимание:</b>
• Запросы проверяются администраторами
• Злоупотребление функцией может привести к бану

<b>‼️ ФУНКЦИЯ В БЕТА-ТЕСТЕ</b>

Так как пока что функция тестится, могут быть баги.
С случае обнаружения бага вы можете их сообщить в чате,
предварительно отметив одного из модераторов.
Также если что-то не получается, можете
отправить пост скрин с постом из тгк и просьбой удалить."""
            
            await update.message.reply_text(delete_request_text, parse_mode='HTML')
            
            # Устанавливаем флаг ожидания поста для удаления
            context.user_data['waiting_delete_request'] = True
            await update.message.reply_text("📤 <b>Теперь отправьте пост из канала</b>\n\n"
                                          "1. Откройте канал сущностей\n"
                                          "2. Выберите нужный пост\n"
                                          "3. Перешлите в чат с ботом\n\n"
                                          "<i>Для выхода из режима нажмите /start или другую кнопку меню</i>",
                                          parse_mode='HTML')
    
    except Exception as e:
        logger.error(f"Ошибка обработки кнопки клавиатуры: {e}")

# ====== УПРОЩЕННАЯ ФУНКЦИЯ ДОБАВЛЕНИЯ ССЫЛОК ======
def add_links_to_caption(caption):
    """Добавляет ссылки к подписи поста"""
    links_text = f"\n\n<a href='{PEREXODNIK_LINK}'>Переходник</a> | <a href='{PREDLOZHKA_LINK}'>Предложка</a> | <a href='{CHAT_LINK}'>Чат</a>"
    return caption + links_text

# ====== УПРОЩЕННАЯ ОБРАБОТКА ЗАПРОСОВ НА УДАЛЕНИЕ ======
async def handle_delete_request_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает сообщения для запроса на удаление (УПРОЩЕННАЯ ВЕРСИЯ)"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        first_name = update.effective_user.first_name
        
        # Проверяем, ожидаем ли мы запрос на удаление
        if not context.user_data.get('waiting_delete_request', False):
            logger.info(f"Пользователь {user_id} отправил сообщение, но не в режиме запроса удаления")
            return
        
        # Получаем текст или подпись сообщения
        message_text = ""
        if update.message.caption:
            message_text = update.message.caption
        elif update.message.text:
            message_text = update.message.text
        else:
            await update.message.reply_text(
                "❌ Сообщение не содержит текста. Пожалуйста, отправьте пост с текстом."
            )
            return
        
        logger.info(f"Получен текст для поиска: '{message_text[:100]}...'")
        
        # Проверяем, что это похоже на пост из нашего канала
        # Ищем характерные ссылки, которые добавляются во все посты
        if not any(link in message_text for link in ["Переходник", "Предложка", "Чат"]):
            await update.message.reply_text(
                "❌ Это не похоже на пост из нашего канала.\n\n"
                "Пожалуйста, отправьте пост из канала.\n"
                "Все посты в нашем канале содержат ссылки на Переходник, Предложку и Чат."
            )
            context.user_data['waiting_delete_request'] = False
            return
        
        # Очищаем текст от ссылок для поиска в базе
        clean_text = message_text
        
        # Убираем ссылки в конце (они могут быть в разных форматах)
        for link in ["Переходник", "Предложка", "Чат"]:
            if link in clean_text:
                # Ищем первое вхождение ссылки
                link_index = clean_text.find(link)
                if link_index > 0:
                    # Берем текст до первой ссылки
                    clean_text = clean_text[:link_index].strip()
                    break
        
        # Если после удаления ссылок остался только короткий текст или ничего
        if not clean_text or len(clean_text) < 10:
            # Пробуем взять весь текст до 100 символов
            clean_text = message_text[:100]
            
            # Пытаемся найти разделители
            if "\n\n" in clean_text:
                clean_text = clean_text.split("\n\n")[0]
            elif "\n" in clean_text:
                # Берем первую строку
                lines = clean_text.split("\n")
                for line in lines:
                    if line and len(line) > 10 and not any(link in line for link in ["Переходник", "Предложка", "Чат"]):
                        clean_text = line
                        break
        
        if not clean_text or len(clean_text) < 5:
            await update.message.reply_text(
                "❌ Не удалось определить текст поста.\n\n"
                "Пожалуйста, убедитесь что:\n"
                "1. Вы отправляете пост из канала\n"
                "2. Пост содержит текст (а не только фото)\n"
                "3. Пост содержит ссылки 'Переходник | Предложка | Чат'"
            )
            context.user_data['waiting_delete_request'] = False
            return
        
        logger.info(f"Очищенный текст для поиска: '{clean_text[:50]}...' (длина: {len(clean_text)})")
        
        # Ищем в базе данных
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Пытаемся найти пост несколькими способами
        found_suggestion = None
        
        # Способ 1: Поиск по точному совпадению текста (для коротких текстов)
        if len(clean_text) < 200:
            cursor.execute('''
                SELECT id, channel_message_id, user_id, username 
                FROM suggestions 
                WHERE message_text = ? 
                AND status = "approved" 
                AND channel_message_id IS NOT NULL
                LIMIT 1
            ''', (clean_text,))
            found_suggestion = cursor.fetchone()
        
        # Способ 2: Поиск по частичному совпадению
        if not found_suggestion:
            # Ищем по первым 50 символам
            search_text = clean_text[:50]
            cursor.execute('''
                SELECT id, channel_message_id, user_id, username 
                FROM suggestions 
                WHERE (message_text LIKE ? OR message_text LIKE ?) 
                AND status = "approved" 
                AND channel_message_id IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
            ''', (f"{search_text}%", f"%{search_text}%"))
            found_suggestion = cursor.fetchone()
        
        # Способ 3: Поиск по всему тексту сообщения (с ссылками)
        if not found_suggestion:
            # Берем первые 100 символов оригинального текста
            original_search = message_text[:100]
            cursor.execute('''
                SELECT id, channel_message_id, user_id, username 
                FROM suggestions 
                WHERE (message_text LIKE ? OR message_text LIKE ?) 
                AND status = "approved" 
                AND channel_message_id IS NOT NULL
                ORDER BY id DESC
                LIMIT 1
            ''', (f"%{original_search}%", original_search))
            found_suggestion = cursor.fetchone()
        
        if not found_suggestion:
            logger.warning(f"Пост не найден в базе по тексту: '{clean_text[:50]}...'")
            
            # Показываем пользователю, что мы искали
            await update.message.reply_text(
                "❌ Не удалось найти этот пост в базе данных.\n\n"
                "Возможные причины:\n"
                "1. Пост был отправлен через другого бота\n"
                "2. Пост был удален ранее\n"
                "3. В базе данных нет записи об этом посте\n\n"
                f"<i>Поисковый текст: '{clean_text[:100]}...'</i>\n\n"
                "Вы можете:\n"
                "1. Попробовать отправить пост еще раз\n"
                "2. Связаться с администратором в чате",
                parse_mode='HTML'
            )
            context.user_data['waiting_delete_request'] = False
            conn.close()
            return
        
        suggestion_id, channel_message_id, author_id, author_username = found_suggestion
        conn.close()
        
        logger.info(f"Найден пост: suggestion_id={suggestion_id}, channel_msg_id={channel_message_id}")
        
        # Получаем комментарий пользователя (если есть дополнительный текст)
        user_comment = ""
        if update.message.text and len(update.message.text) > len(message_text):
            # Если текст сообщения длиннее найденного текста, возможно это комментарий
            user_comment = update.message.text.replace(message_text, "").strip()
        
        # Сохраняем запрос на удаление в базу данных
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Удаляем старые pending запросы для этого сообщения
        cursor.execute('DELETE FROM delete_requests WHERE channel_message_id = ? AND status = "pending"', (channel_message_id,))
        
        cursor.execute('''
            INSERT INTO delete_requests (user_id, username, first_name, channel_message_id, comment, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, channel_message_id, user_comment, 'pending'))
        
        delete_request_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Отправляем уведомление админам
        admins = get_admins()
        username_display = f"@{username}" if username else first_name
        author_display = f"@{author_username}" if author_username else f"ID: {author_id}"
        
        keyboard = [[InlineKeyboardButton("🗑️ Удалить пост", callback_data=f"delete_post_{delete_request_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        request_text = f"🗑️ <b>Запрос на удаление поста</b>\n\n"
        request_text += f"👤 <b>От пользователя:</b> {username_display}\n"
        request_text += f"🆔 <b>ID пользователя:</b> <code>{user_id}</code>\n"
        request_text += f"📝 <b>Автор поста:</b> {author_display}\n"
        request_text += f"🆔 <b>ID поста в канале:</b> <code>{channel_message_id}</code>\n"
        request_text += f"🆔 <b>ID предложения:</b> <code>{suggestion_id}</code>\n"
        request_text += f"🆔 <b>ID запроса:</b> <code>{delete_request_id}</code>\n"
        
        if user_comment:
            request_text += f"💬 <b>Комментарий:</b> {user_comment}\n"
        
        request_sent = False
        for admin in admins:
            try:
                # Отправляем сообщение админу
                if update.message.photo or update.message.video:
                    # Если есть медиа, пересылаем его
                    await update.message.forward(chat_id=admin)
                
                await context.bot.send_message(
                    chat_id=admin,
                    text=request_text,
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
                request_sent = True
                logger.info(f"Запрос на удаление отправлен админу {admin}")
            except Exception as e:
                logger.error(f"Ошибка отправки админу {admin}: {e}")
        
        if not request_sent:
            await update.message.reply_text("❌ Не удалось отправить запрос администраторам.")
            context.user_data['waiting_delete_request'] = False
            return
        
        # Уведомляем пользователя
        await update.message.reply_text(
            "✅ <b>Ваш запрос на удаление отправлен администраторам!</b>\n\n"
            "Мы рассмотрим ваш запрос в ближайшее время.",
            parse_mode='HTML'
        )
        
        # Сбрасываем состояние
        context.user_data['waiting_delete_request'] = False
        
        # Возвращаем пользователя в главное меню
        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=reply_markup
        )
        
        log_user_action(user_id, username, "sent_delete_request", 
                       f"channel_msg_id={channel_message_id}, suggestion_id={suggestion_id}")
        
    except Exception as e:
        logger.error(f"Ошибка обработки запроса на удаление: {e}")
        try:
            await update.message.reply_text(
                "❌ Произошла ошибка при обработке запроса. Попробуйте еще раз или нажмите /start."
            )
        except:
            pass
        context.user_data['waiting_delete_request'] = False

# ====== ОБРАБОТКА ПРЕДЛОЖЕНИЙ ======
media_groups = {}

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return
        
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        logger.info(f"handle_user_message: text={update.message.text}, caption={update.message.caption}, waiting_delete_request={context.user_data.get('waiting_delete_request', False)}")
        
        # Проверяем, не в режиме ли рассылки
        if context.user_data.get('waiting_broadcast'):
            return
        
        # Проверяем, не в режиме ли запроса на удаление
        if context.user_data.get('waiting_delete_request', False):
            logger.info(f"Пользователь в режиме запроса на удаление, обрабатываем сообщение...")
            await handle_delete_request_message(update, context)
            return
        
        # Обработка медиа для предложений
        if update.message and (update.message.photo or update.message.video):
            await handle_media_message(update, context)
            return
            
        elif update.message and update.message.text:
            # Проверяем, не является ли это кнопкой клавиатуры
            text = update.message.text
            if not (text.startswith("📊") or text.startswith("📋") or text.startswith("📨") or 
                   text.startswith("💬") or text.startswith("🗑️")):
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
        
        logger.info(f"handle_media_message: обработка медиа для предложения, user_id={user_id}")
        
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
        elif data.startswith('delete_post_'):
            if not is_admin(user_id):
                try:
                    await query.edit_message_text("❌ Нет прав для удаления")
                except Exception as e:
                    logger.warning(f"Не удалось отредактировать сообщение: {e}")    
                return
            await delete_post_request(query, context)
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

async def delete_post_request(query, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает запрос на удаление поста"""
    try:
        delete_request_id = int(query.data.split('_')[2])
        user_id = query.from_user.id
        username = query.from_user.username
        
        # Получаем информацию о запросе на удаление
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id, username, first_name, channel_message_id, comment 
            FROM delete_requests 
            WHERE id = ? AND status = "pending"
        ''', (delete_request_id,))
        
        request_data = cursor.fetchone()
        
        if not request_data:
            try:
                await query.edit_message_text("❌ Запрос на удаление не найден или уже обработан")
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение: {e}")
            conn.close()
            return
        
        request_user_id, request_username, request_first_name, channel_message_id, comment = request_data
        
        # Пытаемся удалить сообщение из канала
        try:
            await context.bot.delete_message(
                chat_id=CHANNEL_CHAT_ID,
                message_id=channel_message_id
            )
            
            # Обновляем статус запроса
            cursor.execute('''
                UPDATE delete_requests 
                SET status = "approved", processed_by = ?
                WHERE id = ?
            ''', (user_id, delete_request_id))
            
            conn.commit()
            
            # Обновляем статус соответствующего предложения в базе
            cursor.execute('''
                UPDATE suggestions 
                SET status = "deleted" 
                WHERE channel_message_id = ?
            ''', (channel_message_id,))
            
            conn.commit()
            
            log_admin_action(user_id, username, "approved_delete_request", 
                           target_user_id=request_user_id, 
                           details=f"delete_request_id={delete_request_id}, channel_msg_id={channel_message_id}")
            
            try:
                await query.edit_message_text(
                    f"✅ <b>Пост успешно удален из канала!</b>\n\n"
                    f"🆔 ID запроса: <code>{delete_request_id}</code>\n"
                    f"📝 ID в канале: <code>{channel_message_id}</code>\n"
                    f"👤 Пользователь: {request_first_name} (@{request_username if request_username else 'нет username'})",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение: {e}")
            
            # Уведомляем пользователя об удалении
            try:
                await context.bot.send_message(
                    chat_id=request_user_id,
                    text=f"✅ <b>Ваш запрос на удаление поста был одобрен!</b>\n\n"
                         f"Пост был успешно удален из канала.",
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя {request_user_id}: {e}")
            
        except BadRequest as e:
            error_msg = str(e).lower()
            if "message to delete not found" in error_msg:
                response = "❌ Сообщение уже удалено или не найдено"
            elif "message can't be deleted" in error_msg:
                response = "❌ Нет прав для удаления сообщений в канале"
            else:
                response = f"❌ Ошибка при удалении: {str(e)[:100]}"
            
            await query.edit_message_text(response)
            log_admin_action(user_id, username, "delete_request_error", 
                           details=f"delete_request_id={delete_request_id}, error: {str(e)}")
            
        except Exception as e:
            await query.edit_message_text(f"❌ Произошла ошибка при удалении: {str(e)[:100]}")
            log_admin_action(user_id, username, "delete_request_error", 
                           details=f"delete_request_id={delete_request_id}, error: {str(e)}")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"Ошибка обработки запроса на удаление: {e}")

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
                ban_id, user_id_ban, username_ban, first_name, reason, banned_by, banned_at, ban_type, ban_until, ban_duration = ban
                
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
                bans_text += f"├ Тип: {ban_type or 'permanent'}\n"
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
            
            # Баним пользователя (постоянный бан)
            if ban_user(target_user_id, target_username, first_name, reason, user_id, 'permanent', None, None):
                log_ban_action(user_id, username, "banned_user", target_user_id, reason)
                
                username_display = f"@{target_username}" if target_username else first_name
                
                await update.message.reply_text(
                    f"🚫 <b>Пользователь заблокирован навсегда!</b>\n\n"
                    f"ID: <code>{target_user_id}</code>\n"
                    f"Пользователь: {username_display}\n"
                    f"Причина: {reason}",
                    parse_mode='HTML'
                )
                
                # Уведомляем пользователя о блокировке
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"🚫 <b>Вы были заблокированы в боте навсегда!</b>\n\n"
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
       
# ====== КОМАНДА /TEMPBAN ======
async def tempban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для временной блокировки пользователя"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            log_user_action(user_id, username, "tried_tempban", "попытка использовать команду tempban")
            await update.message.reply_text("❌ У вас нет прав для использования этой команды")
            return
        
        if not context.args or len(context.args) < 3:
            await update.message.reply_text(
                "⏳ <b>Использование команды /tempban</b>\n\n"
                "<b>Формат:</b>\n"
                "<code>/tempban ID_пользователя длительность причина</code>\n\n"
                "<b>Примеры длительности:</b>\n"
                "<code>30m</code> - 30 минут\n"
                "<code>2h</code> - 2 часа\n"
                "<code>1d</code> - 1 день\n"
                "<code>1w</code> - 1 неделя\n"
                "<code>1mo</code> - 1 месяц\n\n"
                "<b>Пример:</b>\n"
                "<code>/tempban 123456789 1d Нарушение правил</code>",
                parse_mode='HTML'
            )
            return
        
        try:
            target_user_id = int(context.args[0])
            duration_str = context.args[1]
            reason = ' '.join(context.args[2:])
            
            # Проверяем, не баним ли мы админа
            if is_admin(target_user_id):
                await update.message.reply_text("❌ Нельзя заблокировать администратора")
                return
            
            # Проверяем, не забанен ли уже пользователь
            if is_banned(target_user_id):
                await update.message.reply_text("❌ Этот пользователь уже заблокирован")
                return
            
            # Парсим длительность
            try:
                duration, human_duration = parse_duration(duration_str)
            except ValueError as e:
                await update.message.reply_text(f"❌ {str(e)}")
                return
            
            # Вычисляем дату окончания бана
            from datetime import datetime
            ban_until = datetime.now() + duration
            ban_until_str = ban_until.strftime('%Y-%m-%d %H:%M:%S')
            
            # Пытаемся получить информацию о пользователе
            try:
                user_info = await context.bot.get_chat(target_user_id)
                target_username = user_info.username
                first_name = user_info.first_name or "Пользователь"
            except Exception as e:
                logger.error(f"Не удалось получить информацию о пользователе {target_user_id}: {e}")
                target_username = None
                first_name = "Пользователь"
            
            # Добавляем временный бан
            success = ban_user(
                user_id=target_user_id,
                username=target_username,
                first_name=first_name,
                reason=reason,
                banned_by=user_id,
                ban_type='temporary',
                ban_until=ban_until_str,
                ban_duration=human_duration
            )
            
            if success:
                log_ban_action(user_id, username, "temp_banned_user", target_user_id, f"{reason} (на {human_duration})")
                
                username_display = f"@{target_username}" if target_username else first_name
                
                await update.message.reply_text(
                    f"⏳ <b>Пользователь заблокирован на {human_duration}!</b>\n\n"
                    f"ID: <code>{target_user_id}</code>\n"
                    f"Пользователь: {username_display}\n"
                    f"Причина: {reason}\n"
                    f"Бан до: {ban_until.strftime('%d.%m.%Y %H:%M')}",
                    parse_mode='HTML'
                )
                
                # Уведомляем пользователя о временной блокировке
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"⏳ <b>Вы были временно заблокированы в боте!</b>\n\n"
                             f"Причина: {reason}\n"
                             f"Длительность: {human_duration}\n"
                             f"Блокировка до: {ban_until.strftime('%d.%m.%Y %H:%M')}\n\n"
                             f"После окончания блокировки вы сможете снова отправлять предложения.",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить пользователя {target_user_id}: {e}")
            else:
                await update.message.reply_text("❌ Произошла ошибка при блокировке пользователя")
                
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. ID должен быть числом.")
        except Exception as e:
            logger.error(f"Ошибка команды tempban: {e}")
            await update.message.reply_text(f"❌ Произошла ошибка: {str(e)}")
            
    except Exception as e:
        logger.error(f"Ошибка команды tempban: {e}")

# ====== КОМАНДА /UNTEMPBAN ======
async def untempban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для снятия временной блокировки пользователя"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            log_user_action(user_id, username, "tried_untempban", "попытка использовать команду untempban")
            await update.message.reply_text("❌ У вас нет прав для использования этой команды")
            return
        
        if not context.args:
            await update.message.reply_text(
                "✅ <b>Использование команды /untempban</b>\n\n"
                "<b>Формат:</b>\n"
                "<code>/untempban ID_пользователя</code>\n\n"
                "<b>Пример:</b>\n"
                "<code>/untempban 123456789</code>",
                parse_mode='HTML'
            )
            return
        
        try:
            target_user_id = int(context.args[0])
            
            # Проверяем, забанен ли пользователь
            ban_info = get_ban_info(target_user_id)
            if not ban_info:
                await update.message.reply_text("❌ Этот пользователь не заблокирован")
                return
            
            # Проверяем, что бан временный
            ban_type = ban_info[7] if len(ban_info) > 7 else 'permanent'
            if ban_type != 'temporary':
                await update.message.reply_text("❌ Этот пользователь заблокирован навсегда. Используйте /unban для разблокировки.")
                return
            
            # Разбаниваем пользователя
            if unban_user(target_user_id):
                log_ban_action(user_id, username, "unbanned_temp_user", target_user_id)
                
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
                    f"✅ <b>Временная блокировка снята!</b>\n\n"
                    f"ID: <code>{target_user_id}</code>\n"
                    f"Пользователь: {username_display}",
                    parse_mode='HTML'
                )
                
                # Уведомляем пользователя о снятии блокировки
                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text="✅ <b>Ваша временная блокировка снята досрочно!</b>\n\n"
                             "Теперь вы можете снова отправлять предложения.",
                        parse_mode='HTML'
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить пользователя {target_user_id}: {e}")
            else:
                await update.message.reply_text("❌ Произошла ошибка при снятии блокировки")
                
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. ID должен быть числом.")
        except Exception as e:
            logger.error(f"Ошибка команды untempban: {e}")
            await update.message.reply_text("❌ Произошла ошибка при выполнении команды")
            
    except Exception as e:
        logger.error(f"Ошибка команды untempban: {e}")

# ====== КОМАНДА /TEMPBANS ======
async def tempbans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список действующих временных банов"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            await update.message.reply_text("❌ Нет прав для этой команды")
            return
        
        temp_bans = get_temp_bans()
        
        if not temp_bans:
            await update.message.reply_text("✅ Нет действующих временных банов")
            return
        
        from datetime import datetime
        
        message_text = f"⏳ <b>Действующие временные баны ({len(temp_bans)}):</b>\n\n"
        
        for i, ban in enumerate(temp_bans, 1):
            user_id_ban, username_ban, first_name, reason, banned_by, banned_at, ban_type, ban_until, ban_duration = ban
            
            username_display = f"@{username_ban}" if username_ban else first_name
            
            # Получаем информацию о админе
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT username FROM users WHERE user_id = ?', (banned_by,))
            admin_info = cursor.fetchone()
            conn.close()
            
            admin_username = admin_info[0] if admin_info else "Неизвестно"
            admin_display = f"@{admin_username}" if admin_username else f"ID: {banned_by}"
            
            # Форматируем даты
            try:
                banned_at_dt = datetime.strptime(banned_at, '%Y-%m-%d %H:%M:%S')
                banned_at_str = banned_at_dt.strftime('%d.%m.%Y %H:%M')
            except:
                banned_at_str = banned_at
            
            try:
                ban_until_dt = datetime.strptime(ban_until, '%Y-%m-%d %H:%M:%S')
                ban_until_str = ban_until_dt.strftime('%d.%m.%Y %H:%M')
                
                # Вычисляем оставшееся время
                time_left = ban_until_dt - datetime.now()
                if time_left.days > 0:
                    time_left_str = f"{time_left.days} дн. {time_left.seconds//3600} ч."
                elif time_left.seconds > 3600:
                    time_left_str = f"{time_left.seconds//3600} ч. {(time_left.seconds%3600)//60} мин."
                else:
                    time_left_str = f"{time_left.seconds//60} мин."
            except:
                ban_until_str = ban_until
                time_left_str = "?"
            
            message_text += f"<b>{i}. {username_display}</b>\n"
            message_text += f"├ ID: <code>{user_id_ban}</code>\n"
            message_text += f"├ Причина: {reason or 'Не указана'}\n"
            message_text += f"├ Длительность: {ban_duration}\n"
            message_text += f"├ Забанен: {admin_display}\n"
            message_text += f"├ С: {banned_at_str}\n"
            message_text += f"├ До: {ban_until_str}\n"
            message_text += f"└ Осталось: {time_left_str}\n\n"
        
        await update.message.reply_text(message_text, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Ошибка команды tempbans: {e}")
        await update.message.reply_text("❌ Ошибка при получении списка временных банов")

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
    """Команда для удаления поста с канала - работает в любых условиях"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            await update.message.reply_text("❌ Нет прав для этой команды")
            return
        
        if not update.message.reply_to_message:
            await update.message.reply_text("❌ Ответьте на сообщение с предложением")
            return
        
        reply_msg = update.message.reply_to_message
        
        # Вариант 1: Если сообщение переслано из канала
        channel_message_id = None
        
        # Проверяем, является ли сообщение пересланным
        if hasattr(reply_msg, 'forward_from_chat') and reply_msg.forward_from_chat:
            try:
                forward_chat_id = str(reply_msg.forward_from_chat.id)
                # Преобразуем CHANNEL_CHAT_ID для сравнения
                target_chat_id = CHANNEL_CHAT_ID
                
                # Если CHANNEL_CHAT_ID начинается с -100, убираем это
                if target_chat_id.startswith('-100'):
                    target_chat_id = target_chat_id[4:]
                elif target_chat_id.startswith('-'):
                    target_chat_id = target_chat_id[1:]
                
                # Сравниваем ID
                if str(forward_chat_id) == str(target_chat_id) or str(-100) + str(forward_chat_id) == CHANNEL_CHAT_ID:
                    channel_message_id = reply_msg.forward_from_message_id
                    logger.info(f"Определил через пересылку: channel_message_id={channel_message_id}, chat_id={forward_chat_id}")
            except Exception as e:
                logger.error(f"Ошибка проверки пересланного сообщения: {e}")
        elif hasattr(reply_msg, 'forward_from_message_id') and reply_msg.forward_from_message_id:
            # Если есть forward_from_message_id, но нет forward_from_chat, возможно сообщение переслано через канал
            channel_message_id = reply_msg.forward_from_message_id
            logger.info(f"Использую forward_from_message_id: {channel_message_id}")
        
        # Вариант 2: Ищем в базе данных
        suggestion_id = None
        search_text = ""
        
        if hasattr(reply_msg, 'caption') and reply_msg.caption:
            search_text = reply_msg.caption
        elif hasattr(reply_msg, 'text') and reply_msg.text:
            search_text = reply_msg.text
        
        if search_text and not channel_message_id:
            result = find_suggestion_by_text(search_text)
            if result:
                suggestion_id, db_channel_message_id, status = result
                if db_channel_message_id:
                    channel_message_id = db_channel_message_id
                    logger.info(f"Нашел в базе: suggestion_id={suggestion_id}, channel_message_id={channel_message_id}")
        
        # Вариант 3: Если все еще нет channel_message_id, но есть suggestion_id
        if suggestion_id and not channel_message_id:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT channel_message_id FROM suggestions WHERE id = ?', (suggestion_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    channel_message_id = row[0]
                    logger.info(f"Получил из базы напрямую: channel_message_id={channel_message_id}")
                conn.close()
            except Exception as e:
                logger.error(f"Ошибка запроса к базе: {e}")
        
        # Если нашли ID сообщения для удаления
        if channel_message_id:
            try:
                # ПРЯМОЕ УДАЛЕНИЕ ИЗ КАНАЛА
                await context.bot.delete_message(
                    chat_id=CHANNEL_CHAT_ID, 
                    message_id=channel_message_id
                )
                
                # Обновляем статус в базе если есть suggestion_id
                if suggestion_id:
                    try:
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            'UPDATE suggestions SET status = ? WHERE id = ?', 
                            ('deleted', suggestion_id)
                        )
                        conn.commit()
                        conn.close()
                        logger.info(f"Обновлен статус в базе: suggestion_id={suggestion_id} -> deleted")
                    except Exception as e:
                        logger.error(f"Не удалось обновить статус: {e}")
                
                # Успешное сообщение
                success_msg = f"✅ <b>Пост удален из канала!</b>\n\nID в канале: <code>{channel_message_id}</code>"
                if suggestion_id:
                    success_msg += f"\nID предложения: <code>{suggestion_id}</code>"
                
                await update.message.reply_text(success_msg, parse_mode='HTML')
                log_admin_action(user_id, username, "delete_success", 
                               details=f"channel_msg_id={channel_message_id}, suggestion_id={suggestion_id}")
                
            except BadRequest as e:
                error_msg = str(e).lower()
                if "message to delete not found" in error_msg:
                    response = "❌ Сообщение уже удалено или не найдено"
                elif "message can't be deleted" in error_msg:
                    response = "❌ Нет прав для удаления сообщений в канале"
                elif "chat not found" in error_msg:
                    response = f"❌ Чат не найден. Проверьте CHANNEL_CHAT_ID в настройках бота."
                else:
                    response = f"❌ Ошибка при удалении: {str(e)[:200]}"
                
                await update.message.reply_text(response)
                log_admin_action(user_id, username, "delete_error", details=str(e))
                
            except Exception as e:
                await update.message.reply_text(f"❌ Произошла ошибка при удалении: {str(e)[:200]}")
                log_admin_action(user_id, username, "delete_error", details=str(e))
        
        else:
            # Не удалось определить что удалять
            response_text = (
                "❌ <b>Не могу определить какой пост удалять</b>\n\n"
                "<b>Как правильно использовать:</b>\n"
                "1. Перешлите сообщение ИЗ КАНАЛА в этот чат\n"
                "2. Ответьте командой /delete на пересланное сообщение\n\n"
                "<b>ИЛИ</b>\n"
                "1. Ответьте командой /delete на сообщение бота с предложением (то, что он вам отправил для модерации)\n\n"
                "<b>Примечание:</b> Бот должен быть админом в канале с правом удаления сообщений."
            )
            
            if search_text:
                response_text += f"\n\n<i>Поисковый текст: '{search_text[:100]}...'</i>"
            
            await update.message.reply_text(response_text, parse_mode='HTML')
            log_admin_action(user_id, username, "delete_not_found", 
                           details=f"search_text: '{search_text[:50]}...'")
            
    except Exception as e:
        logger.error(f"Ошибка команды delete: {e}")
        try:
            await update.message.reply_text("❌ Произошла внутренняя ошибка при выполнении команды.")
        except:
            pass

# ====== КОМАНДА /BROADCAST ======
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает режим рассылки"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            log_user_action(user_id, username, "tried_broadcast", "попытка использовать рассылку")
            await update.message.reply_text("❌ У вас нет прав для использования этой команды")
            return
        
        log_admin_action(user_id, username, "broadcast_started")
        
        # Получаем количество пользователей
        users_count = len(get_all_users())
        
        await update.message.reply_text(
            f"📢 <b>Режим рассылки</b>\n\n"
            f"📊 Всего пользователей для рассылки: <code>{users_count}</code>\n\n"
            f"<b>Отправьте сообщение для рассылки всем пользователям.</b>\n"
            f"Можно отправить:\n"
            f"• Текст\n"
            f"• Фото с текстом\n"
            f"• Видео с текстом\n"
            f"• Документы\n\n"
            f"<b>Для отмены отправьте /cancel</b>",
            parse_mode='HTML'
        )
        
        context.user_data['waiting_broadcast'] = True
        return WAITING_BROADCAST
    except Exception as e:
        logger.error(f"Ошибка начала рассылки: {e}")
        return ConversationHandler.END

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет рассылку всем пользователям"""
    try:
        user_id = update.effective_user.id
        username = update.effective_user.username
        
        if not is_admin(user_id):
            context.user_data['waiting_broadcast'] = False
            return ConversationHandler.END
        
        # Получаем всех пользователей
        users = get_all_users()
        
        if not users:
            await update.message.reply_text("❌ Нет пользователей для рассылки")
            context.user_data['waiting_broadcast'] = False
            return ConversationHandler.END
        
        # Убираем отправителя из рассылки
        users_to_send = [user for user in users if user != user_id]
        
        if not users_to_send:
            await update.message.reply_text("❌ Нет других пользователей для рассылки (кроме вас)")
            context.user_data['waiting_broadcast'] = False
            return ConversationHandler.END
        
        success_count = 0
        fail_count = 0
        blocked_count = 0
        
        # Отправляем статус
        status_msg = await update.message.reply_text(
            f"📢 <b>Начинаю рассылку...</b>\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"• Всего пользователей: <code>{len(users)}</code>\n"
            f"• Для рассылки: <code>{len(users_to_send)}</code> (вы исключены)\n"
            f"• Отправка началась...",
            parse_mode='HTML'
        )
        
        # Отправляем сообщение
        for i, user in enumerate(users_to_send):
            try:
                if update.message.text:
                    await context.bot.send_message(chat_id=user, text=update.message.text)
                    success_count += 1
                    
                elif update.message.photo:
                    await context.bot.send_photo(
                        chat_id=user,
                        photo=update.message.photo[-1].file_id,
                        caption=update.message.caption,
                        parse_mode='HTML' if update.message.caption_html else None
                    )
                    success_count += 1
                    
                elif update.message.video:
                    await context.bot.send_video(
                        chat_id=user,
                        video=update.message.video.file_id,
                        caption=update.message.caption,
                        parse_mode='HTML' if update.message.caption_html else None
                    )
                    success_count += 1
                    
                elif update.message.document:
                    await context.bot.send_document(
                        chat_id=user,
                        document=update.message.document.file_id,
                        caption=update.message.caption,
                        parse_mode='HTML' if update.message.caption_html else None
                    )
                    success_count += 1
                
                # Обновляем статус каждые 10 сообщений
                if i % 10 == 0 and i > 0:
                    try:
                        await status_msg.edit_text(
                            f"📢 <b>Рассылка в процессе...</b>\n\n"
                            f"📊 <b>Прогресс:</b>\n"
                            f"• Отправлено: <code>{i+1}/{len(users_to_send)}</code>\n"
                            f"• ✅ Успешно: <code>{success_count}</code>\n"
                            f"• ❌ Ошибок: <code>{fail_count}</code>\n"
                            f"• 🚫 Заблокировали: <code>{blocked_count}</code>",
                            parse_mode='HTML'
                        )
                    except:
                        pass
                
                # Небольшая задержка
                await asyncio.sleep(0.05)
                
            except Forbidden:
                # Пользователь заблокировал бота
                blocked_count += 1
                
            except BadRequest as e:
                if "Chat not found" in str(e) or "user not found" in str(e):
                    fail_count += 1
                else:
                    fail_count += 1
                    logger.error(f"Ошибка при отправке пользователю {user}: {e}")
                    
            except Exception as e:
                fail_count += 1
                logger.error(f"Ошибка при отправке пользователю {user}: {e}")
        
        log_admin_action(user_id, username, "broadcast_completed", 
                        details=f"success: {success_count}, failed: {fail_count}, blocked: {blocked_count}")
        
        context.user_data['waiting_broadcast'] = False
        
        # Финальный отчет
        await status_msg.edit_text(
            f"✅ <b>Рассылка завершена!</b>\n\n"
            f"📊 <b>Итоговая статистика:</b>\n"
            f"• Всего пользователей: <code>{len(users)}</code>\n"
            f"• Для рассылки: <code>{len(users_to_send)}</code>\n"
            f"• ✅ Успешно отправлено: <code>{success_count}</code>\n"
            f"• 🚫 Заблокировали бота: <code>{blocked_count}</code>\n"
            f"• ❌ Ошибок отправки: <code>{fail_count}</code>\n"
            f"• 👤 Вы исключены из рассылки",
            parse_mode='HTML'
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Ошибка рассылки: {e}")
        context.user_data['waiting_broadcast'] = False
        return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменяет рассылку"""
    try:
        if 'waiting_broadcast' in context.user_data:
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

# ====== ЗАПУСК ======
def main():
    # Проверяем наличие других экземпляров (только для предупреждения)
    has_other_instance = check_running_instances()
    
    import atexit
    atexit.register(cleanup_lock_file)
    
    try:
        init_db()
        
        # Создаем Application с правильной конфигурацией
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Проверяем истекшие баны при запуске
        expired_count = check_expired_bans()
        if expired_count > 0:
            logger.info(f"При запуске удалено {expired_count} истекших временных банов")
        
        # Простая проверка подключения - просто попытка создать бота
        logger.info(f"Запуск бота с токеном: {BOT_TOKEN[:10]}...")
        print("🤖 Запускаю бота...")
        
        application.add_error_handler(error_handler)
        
        # Обработчики в правильном порядке (от самых специфичных к общим)
        
        # 1. Обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stats", show_statistics))
        application.add_handler(CommandHandler("admins", admins_list))
        application.add_handler(CommandHandler("approve", approve_command))
        application.add_handler(CommandHandler("delete", delete_command))
        application.add_handler(CommandHandler("ban", ban_command))
        application.add_handler(CommandHandler("unban", unban_command))
        application.add_handler(CommandHandler("tempban", tempban_command))
        application.add_handler(CommandHandler("untempban", untempban_command))
        application.add_handler(CommandHandler("tempbans", tempbans_command))
        
        # 2. ConversationHandler для рассылки
        broadcast_handler = ConversationHandler(
            entry_points=[CommandHandler("broadcast", broadcast_start)],
            states={
                WAITING_BROADCAST: [
                    MessageHandler(
                        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL,
                        broadcast_message
                    ),
                    CommandHandler("cancel", broadcast_cancel)
                ]
            },
            fallbacks=[CommandHandler("cancel", broadcast_cancel)],
            per_message=False
        )
        application.add_handler(broadcast_handler)
        
        # 3. ConversationHandler для добавления администратора
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
        application.add_handler(add_admin_handler)
        
        # 4. ConversationHandler для удаления администратора
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
        application.add_handler(remove_admin_handler)
        
        # 5. Обработчики кнопок клавиатуры
        application.add_handler(MessageHandler(
            filters.TEXT & filters.Regex(r'^(📊 Статистика|📋 Правила|📨 Отправить пост|🗑️ Запрос на удаление|💬 Чат)$'),
            handle_keyboard_buttons
        ))
        
        # 6. Обработчики кнопок (callback queries)
        application.add_handler(CallbackQueryHandler(button_handler))
        
        # 7. Обработчики медиа сообщений (должен быть ПОСЛЕ текстовых, чтобы не перехватывал)
        application.add_handler(MessageHandler(
            filters.PHOTO | filters.VIDEO, 
            handle_user_message
        ))
        
        # 8. Обработчик текстовых сообщений (не команд)
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, 
            handle_user_message
        ))
        
        # 9. Обработчик неизвестных команд (последний)
        application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
        
        print("=" * 60)
        print("🤖 Бот запущен и готов к работе!")
        print(f"🤖 Token: {BOT_TOKEN[:10]}...")
        print(f"🤖 Admin ID: {ADMIN_CHAT_ID}")
        if has_other_instance:
            print("⚠️  ПРЕДУПРЕЖДЕНИЕ: Возможно есть другие запущенные экземпляры")
        print("=" * 60)
        
        # Запускаем бота с подробными логами
        logger.info("🔄 Запуск polling...")
        
        # Устанавливаем более высокий timeout и включим все обновления
        application.run_polling(
            poll_interval=0.5,  # Более частое опрос
            timeout=30,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
            close_loop=False
        )
        
    except KeyboardInterrupt:
        print("\n\n✅ Бот остановлен пользователем (Ctrl+C)")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}", exc_info=True)
        print(f"❌ Бот остановлен из-за ошибки: {e}")
    finally:
        cleanup_lock_file()
