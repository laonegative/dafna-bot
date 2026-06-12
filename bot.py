import os
import json
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

# ─────────────────────────────────────────────
#  НАСТРОЙКИ — заполните своими данными
# ─────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_СЮДА")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "ВАШ_CHAT_ID_СЮДА")  # ваш личный chat_id
INVITE_CODE = os.getenv("INVITE_CODE", "DAFNA2024")  # секретный код для входа
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://ваш-сайт.railway.app")  # URL мини-приложения

# ─────────────────────────────────────────────
#  БАЗА ДАННЫХ (SQLite — файл на сервере)
# ─────────────────────────────────────────────
DB_PATH = "dafna.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Таблица сотрудников
    c.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            chat_id     TEXT PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            joined_at   TEXT,
            showroom    TEXT DEFAULT 'Не указан'
        )
    """)
    
    # Таблица прогресса
    c.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     TEXT,
            module_id   INTEGER,
            lesson_id   TEXT,
            action      TEXT,  -- 'lesson_done' или 'quiz_done'
            score       INTEGER DEFAULT 0,
            done_at     TEXT,
            FOREIGN KEY (chat_id) REFERENCES employees(chat_id)
        )
    """)
    
    conn.commit()
    conn.close()

def get_employee(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM employees WHERE chat_id=?", (str(chat_id),))
    row = c.fetchone()
    conn.close()
    return row

def register_employee(chat_id, username, full_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    c.execute("""
        INSERT OR IGNORE INTO employees (chat_id, username, full_name, joined_at)
        VALUES (?, ?, ?, ?)
    """, (str(chat_id), username or "—", full_name, now))
    conn.commit()
    conn.close()

def save_progress(chat_id, module_id, lesson_id, action, score=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    # Проверяем, нет ли уже такой записи
    c.execute("""
        SELECT id FROM progress 
        WHERE chat_id=? AND module_id=? AND lesson_id=? AND action=?
    """, (str(chat_id), module_id, lesson_id, action))
    exists = c.fetchone()
    if not exists:
        c.execute("""
            INSERT INTO progress (chat_id, module_id, lesson_id, action, score, done_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (str(chat_id), module_id, lesson_id, action, score, now))
        conn.commit()
    conn.close()
    return not exists  # True если это новое достижение

def get_all_progress(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT module_id, lesson_id, action, score, done_at
        FROM progress WHERE chat_id=?
        ORDER BY done_at DESC
    """, (str(chat_id),))
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_employees():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id, username, full_name, joined_at, showroom FROM employees ORDER BY joined_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_employee_stats(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM progress WHERE chat_id=? AND action='lesson_done'", (str(chat_id),))
    lessons = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM progress WHERE chat_id=? AND action='quiz_done'", (str(chat_id),))
    quizzes = c.fetchone()[0]
    c.execute("SELECT AVG(score) FROM progress WHERE chat_id=? AND action='quiz_done'", (str(chat_id),))
    avg_score = c.fetchone()[0]
    conn.close()
    return lessons, quizzes, round(avg_score or 0)

# ─────────────────────────────────────────────
#  HANDLERS — реакции на команды
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start — точка входа"""
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args  # аргументы после /start

    # Проверяем код приглашения
    if args and args[0] == INVITE_CODE:
        employee = get_employee(chat_id)
        if not employee:
            # Новый сотрудник — просим представиться
            context.user_data['awaiting_name'] = True
            context.user_data['invite_verified'] = True
            await update.message.reply_text(
                "👋 Добро пожаловать в *Академию DAFNA*!\n\n"
                "Пожалуйста, напишите ваше *полное имя* (Имя Фамилия):",
                parse_mode="Markdown"
            )
        else:
            # Уже зарегистрирован — сразу в обучение
            await show_main_menu(update, context)
    else:
        # Нет кода — проверяем, зарегистрирован ли
        employee = get_employee(chat_id)
        if employee:
            await show_main_menu(update, context)
        else:
            await update.message.reply_text(
                "🔒 Доступ только по ссылке-приглашению.\n\n"
                "Обратитесь к вашему стор-менеджеру для получения ссылки."
            )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений (ввод имени при регистрации)"""
    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()

    if context.user_data.get('awaiting_name') and context.user_data.get('invite_verified'):
        # Сохраняем имя и регистрируем
        full_name = text
        username = user.username or "—"
        register_employee(chat_id, username, full_name)
        context.user_data['awaiting_name'] = False
        context.user_data['invite_verified'] = False

        # Уведомляем администратора
        now = datetime.now().strftime("%d.%m.%Y в %H:%M")
        admin_msg = (
            f"🆕 *Новый сотрудник зарегистрировался!*\n\n"
            f"👤 Имя: {full_name}\n"
            f"💬 Telegram: @{username}\n"
            f"🆔 Chat ID: `{chat_id}`\n"
            f"🕐 Время: {now}"
        )
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_msg,
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Не смог отправить уведомление админу: {e}")

        await update.message.reply_text(
            f"✅ Отлично, *{full_name}*! Вы зарегистрированы.\n\n"
            f"Добро пожаловать в Академию DAFNA! 🎓",
            parse_mode="Markdown"
        )
        await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню после входа"""
    chat_id = update.effective_chat.id
    employee = get_employee(chat_id)
    if not employee:
        return

    lessons, quizzes, avg = get_employee_stats(chat_id)
    name = employee[2]  # full_name

    keyboard = [
        [InlineKeyboardButton(
            "📚 Открыть обучение",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}?uid={chat_id}")
        )],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="my_progress")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"👋 Привет, *{name}*!\n\n"
        f"📚 Академия DAFNA — ваш учебный центр\n\n"
        f"📈 *Ваша статистика:*\n"
        f"• Уроков пройдено: *{lessons}*\n"
        f"• Тестов сдано: *{quizzes}*\n"
        f"• Средний балл: *{avg}%*\n\n"
        f"Нажмите кнопку ниже, чтобы начать обучение 👇"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальный прогресс сотрудника"""
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    lessons, quizzes, avg = get_employee_stats(chat_id)
    progress = get_all_progress(chat_id)

    # Подсчёт по модулям
    modules_done = set()
    quiz_results = {}
    for row in progress:
        mod_id, les_id, action, score, done_at = row
        modules_done.add(mod_id)
        if action == 'quiz_done':
            quiz_results[mod_id] = score

    MODULE_NAMES = {
        1: "Добро пожаловать в DAFNA",
        2: "Контакт с клиентом",
        3: "Ассортимент: кресла и стулья",
        4: "Презентация и возражения",
        5: "Допродажи и завершение"
    }

    modules_text = ""
    for mid, mname in MODULE_NAMES.items():
        if mid in quiz_results:
            score = quiz_results[mid]
            emoji = "✅" if score >= 60 else "⚠️"
            modules_text += f"{emoji} {mname}: *{score}%*\n"
        elif mid in modules_done:
            modules_text += f"📖 {mname}: в процессе\n"
        else:
            modules_text += f"🔒 {mname}: не начат\n"

    text = (
        f"📊 *Ваш прогресс*\n\n"
        f"📚 Уроков пройдено: *{lessons}*\n"
        f"✅ Тестов сдано: *{quizzes}* из 5\n"
        f"⭐️ Средний балл: *{avg}%*\n\n"
        f"*По модулям:*\n{modules_text}"
    )

    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "ℹ️ *Помощь*\n\n"
        "📚 *Как пользоваться:*\n"
        "1. Нажмите «Открыть обучение»\n"
        "2. Изучайте уроки по порядку\n"
        "3. После каждого модуля — тест\n"
        "4. Ваш прогресс сохраняется автоматически\n\n"
        "❓ *Проблемы?*\n"
        "Обратитесь к стор-менеджеру"
    )
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data == "main_menu":
        await show_main_menu(update, context)
    elif data == "my_progress":
        await my_progress(update, context)
    elif data == "help":
        await help_handler(update, context)

# ─────────────────────────────────────────────
#  WEBHOOK от Web App — прогресс из браузера
# ─────────────────────────────────────────────
async def webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем данные о прогрессе из мини-приложения"""
    chat_id = update.effective_chat.id
    employee = get_employee(chat_id)
    if not employee:
        return

    try:
        data = json.loads(update.effective_message.web_app_data.data)
        action = data.get("action")
        module_id = data.get("module_id")
        lesson_id = data.get("lesson_id", "")
        score = data.get("score", 0)
        name = employee[2]

        is_new = save_progress(chat_id, module_id, lesson_id, action, score)

        if is_new:
            MODULE_NAMES = {
                1: "Добро пожаловать в DAFNA",
                2: "Контакт с клиентом",
                3: "Ассортимент: кресла и стулья",
                4: "Презентация и возражения",
                5: "Допродажи и завершение"
            }
            mod_name = MODULE_NAMES.get(int(module_id), f"Модуль {module_id}")
            now = datetime.now().strftime("%d.%m.%Y %H:%M")

            if action == "lesson_done":
                admin_msg = (
                    f"📖 *Урок пройден*\n\n"
                    f"👤 {name}\n"
                    f"📚 {mod_name}\n"
                    f"📝 Урок: {lesson_id}\n"
                    f"🕐 {now}"
                )
                await update.message.reply_text(f"✅ Урок сохранён! Отличная работа, {name.split()[0]}!")

            elif action == "quiz_done":
                emoji = "🏆" if score >= 80 else ("✅" if score >= 60 else "📝")
                result = "Отлично!" if score >= 80 else ("Зачёт!" if score >= 60 else "Нужно повторить")
                admin_msg = (
                    f"{emoji} *Тест сдан*\n\n"
                    f"👤 {name}\n"
                    f"📚 {mod_name}\n"
                    f"⭐️ Результат: *{score}%* — {result}\n"
                    f"🕐 {now}"
                )
                await update.message.reply_text(
                    f"{emoji} Тест завершён!\n"
                    f"Ваш результат: *{score}%* — {result}",
                    parse_mode="Markdown"
                )

            # Уведомляем администратора
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=admin_msg,
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Ошибка уведомления: {e}")

    except Exception as e:
        print(f"Ошибка обработки данных webapp: {e}")

# ─────────────────────────────────────────────
#  КОМАНДЫ ДЛЯ АДМИНИСТРАТОРА
# ─────────────────────────────────────────────

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /stats — только для администратора"""
    chat_id = str(update.effective_chat.id)
    if chat_id != str(ADMIN_CHAT_ID):
        await update.message.reply_text("⛔️ Нет доступа.")
        return

    employees = get_all_employees()
    if not employees:
        await update.message.reply_text("Пока нет зарегистрированных сотрудников.")
        return

    text = f"👥 *Сотрудники DAFNA* ({len(employees)} чел.)\n\n"
    for emp in employees:
        eid, uname, fname, joined, showroom = emp
        lessons, quizzes, avg = get_employee_stats(eid)
        text += (
            f"👤 *{fname}*\n"
            f"   @{uname} · {joined}\n"
            f"   📚 {lessons} уроков · ✅ {quizzes}/5 тестов · ⭐️ {avg}%\n\n"
        )

    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /link — генерация ссылки приглашения"""
    chat_id = str(update.effective_chat.id)
    if chat_id != str(ADMIN_CHAT_ID):
        await update.message.reply_text("⛔️ Нет доступа.")
        return

    bot_username = (await context.bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start={INVITE_CODE}"

    await update.message.reply_text(
        f"🔗 *Ссылка для новых сотрудников:*\n\n"
        f"`{invite_link}`\n\n"
        f"Отправьте эту ссылку новому сотруднику. "
        f"После перехода он пройдёт регистрацию и начнёт обучение.",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────────
#  ЗАПУСК БОТА
# ─────────────────────────────────────────────
def main():
    init_db()
    print("🚀 Бот DAFNA запускается...")

    app = Application.builder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("link", admin_link))

    # Кнопки
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Данные из мини-приложения
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_data))

    # Ввод текста (имя при регистрации)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("✅ Бот запущен! Нажмите Ctrl+C для остановки.")
    app.run_polling()

if __name__ == "__main__":
    main()
