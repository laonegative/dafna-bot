import os
import json
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")
INVITE_CODE = os.getenv("INVITE_CODE", "DAFNA2024")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://laonegative.github.io/dafna-bot")
DB_PATH = "dafna.db"

MODULE_NAMES = {
    1: "История и стандарты",
    2: "Контакт с клиентом",
    3: "Кресла и стулья",
    4: "Мягкая мебель",
    5: "Корпусная мебель и AIKO",
    6: "Презентация и возражения",
    7: "Жалобы и сервис",
    8: "Допродажи и завершение",
    9: "Финальный тест",
    'final': "🏆 Финальный тест"
}

TOTAL_LESSONS = 18
TOTAL_MODULES = 8

# ─── DATABASE ───
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS employees (
        chat_id TEXT PRIMARY KEY, username TEXT, full_name TEXT,
        joined_at TEXT, showroom TEXT DEFAULT 'Не указан')""")
    c.execute("""CREATE TABLE IF NOT EXISTS progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT,
        module_id TEXT, lesson_id TEXT, action TEXT,
        score INTEGER DEFAULT 0, done_at TEXT)""")
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
    c.execute("INSERT OR IGNORE INTO employees (chat_id,username,full_name,joined_at) VALUES (?,?,?,?)",
              (str(chat_id), username or "—", full_name, now))
    conn.commit()
    conn.close()

def save_progress(chat_id, module_id, lesson_id, action, score=0):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    c.execute("SELECT id FROM progress WHERE chat_id=? AND module_id=? AND lesson_id=? AND action=?",
              (str(chat_id), str(module_id), lesson_id, action))
    exists = c.fetchone()
    is_new = not exists
    if is_new:
        c.execute("INSERT INTO progress (chat_id,module_id,lesson_id,action,score,done_at) VALUES (?,?,?,?,?,?)",
                  (str(chat_id), str(module_id), lesson_id, action, score, now))
    else:
        # Update score if better
        c.execute("UPDATE progress SET score=?,done_at=? WHERE chat_id=? AND module_id=? AND lesson_id=? AND action=?",
                  (score, now, str(chat_id), str(module_id), lesson_id, action))
    conn.commit()
    conn.close()
    return is_new

def get_all_employees():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT chat_id,username,full_name,joined_at,showroom FROM employees ORDER BY joined_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def get_employee_stats(chat_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM progress WHERE chat_id=? AND action='lesson_done'", (str(chat_id),))
    lessons = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM progress WHERE chat_id=? AND action IN ('quiz_done','final_done')", (str(chat_id),))
    quizzes = c.fetchone()[0]
    c.execute("SELECT AVG(score) FROM progress WHERE chat_id=? AND action IN ('quiz_done','final_done')", (str(chat_id),))
    avg = c.fetchone()[0] or 0
    c.execute("SELECT module_id,score,done_at FROM progress WHERE chat_id=? AND action IN ('quiz_done','final_done') ORDER BY module_id", (str(chat_id),))
    quiz_details = c.fetchall()
    c.execute("SELECT done_at FROM progress WHERE chat_id=? ORDER BY done_at DESC LIMIT 1", (str(chat_id),))
    last = c.fetchone()
    conn.close()
    return lessons, quizzes, round(avg), quiz_details, last[0] if last else None

def get_summary_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM employees")
    total_emp = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT chat_id) FROM progress")
    active = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT chat_id) FROM progress WHERE action='final_done'")
    finished = c.fetchone()[0]
    c.execute("SELECT AVG(score) FROM progress WHERE action='final_done'")
    avg_final = c.fetchone()[0] or 0
    # Active today
    today = datetime.now().strftime("%d.%m.%Y")
    c.execute("SELECT COUNT(DISTINCT chat_id) FROM progress WHERE done_at LIKE ?", (today+'%',))
    today_active = c.fetchone()[0]
    conn.close()
    return total_emp, active, finished, round(avg_final), today_active

# ─── HANDLERS ───
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    args = context.args

    if args and args[0] == INVITE_CODE:
        employee = get_employee(chat_id)
        if not employee:
            context.user_data['awaiting_name'] = True
            context.user_data['invite_verified'] = True
            await update.message.reply_text(
                "👋 Добро пожаловать в *Академию DAFNA*!\n\n"
                "Пожалуйста, напишите ваше *полное имя* (Имя Фамилия):",
                parse_mode="Markdown")
        else:
            await show_main_menu(update, context)
    else:
        employee = get_employee(chat_id)
        if employee:
            await show_main_menu(update, context)
        else:
            await update.message.reply_text(
                "🔒 Доступ только по ссылке-приглашению.\n"
                "Обратитесь к вашему стор-менеджеру.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    text = update.message.text.strip()

    if context.user_data.get('awaiting_name') and context.user_data.get('invite_verified'):
        full_name = text
        register_employee(chat_id, user.username, full_name)
        context.user_data['awaiting_name'] = False
        context.user_data['invite_verified'] = False

        now = datetime.now().strftime("%d.%m.%Y в %H:%M")
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"🆕 *Новый сотрудник!*\n\n👤 {full_name}\n💬 @{user.username or '—'}\n🆔 `{chat_id}`\n🕐 {now}",
                parse_mode="Markdown")
        except: pass

        await update.message.reply_text(
            f"✅ Отлично, *{full_name}*! Вы зарегистрированы в Академии DAFNA! 🎓",
            parse_mode="Markdown")
        await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    employee = get_employee(chat_id)
    if not employee: return
    lessons, quizzes, avg, _, last_active = get_employee_stats(chat_id)
    name = employee[2]
    pct = round(lessons / TOTAL_LESSONS * 100)

    bar_filled = round(pct / 10)
    progress_bar = '█' * bar_filled + '░' * (10 - bar_filled)

    keyboard = [
        [InlineKeyboardButton("📚 Открыть обучение", web_app={"url": f"{WEBAPP_URL}?uid={chat_id}"})],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="my_progress"),
         InlineKeyboardButton("🏆 Рейтинг", callback_data="rating")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")],
    ]

    text = (f"👋 Привет, *{name}*!\n\n"
            f"`{progress_bar}` {pct}%\n\n"
            f"📚 Уроков: *{lessons}/{TOTAL_LESSONS}*\n"
            f"✅ Тестов: *{quizzes}*\n"
            f"⭐️ Балл: *{avg}%*\n\n"
            f"Нажмите кнопку чтобы начать обучение 👇")

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard))

async def my_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    lessons, quizzes, avg, quiz_details, last = get_employee_stats(chat_id)
    pct = round(lessons / TOTAL_LESSONS * 100)

    modules_text = ""
    done_mods = {str(qd[0]): qd[1] for qd in quiz_details}
    for i in range(1, 10):
        mid = str(i)
        name = MODULE_NAMES.get(i, f"Модуль {i}")
        if i == 9:
            name = "🏆 Финальный тест"
            mid = 'final'
        if mid in done_mods:
            s = done_mods[mid]
            e = "✅" if s >= 70 else "⚠️"
            modules_text += f"{e} {name}: *{s}%*\n"
        else:
            modules_text += f"🔒 {name}\n"

    text = (f"📊 *Мой прогресс*\n\n"
            f"📚 Уроков: *{lessons}/{TOTAL_LESSONS}* ({pct}%)\n"
            f"✅ Тестов сдано: *{quizzes}*\n"
            f"⭐️ Средний балл: *{avg}%*\n"
            f"🕐 Последняя активность: {last or 'нет данных'}\n\n"
            f"*По модулям:*\n{modules_text}")

    kb = [[InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))

async def show_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    employees = get_all_employees()
    rows = []
    for emp in employees:
        cid, uname, fname, joined, _ = emp
        l, q, avg, _, _ = get_employee_stats(cid)
        pct = round(l / TOTAL_LESSONS * 100)
        rows.append((pct, avg, fname, l, q))
    rows.sort(reverse=True)

    medals = ['🥇', '🥈', '🥉']
    text = "🏆 *Рейтинг сотрудников*\n\n"
    for i, (pct, avg, name, lessons, quizzes) in enumerate(rows[:10]):
        m = medals[i] if i < 3 else f"{i+1}."
        text += f"{m} *{name}*\n   📚 {lessons} ур. · ✅ {quizzes} тестов · ⭐️ {avg}%\n\n"

    kb = [[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = ("ℹ️ *Помощь*\n\n"
            "1. Нажмите «Открыть обучение»\n"
            "2. Изучайте уроки по порядку\n"
            "3. После каждого модуля — тест\n"
            "4. В конце — финальный тест из 15 вопросов\n\n"
            "❓ Проблемы? Обратитесь к стор-менеджеру")
    kb = [[InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")]]
    await query.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "main_menu": await show_main_menu(update, context)
    elif data == "my_progress": await my_progress(update, context)
    elif data == "rating": await show_rating(update, context)
    elif data == "help": await help_handler(update, context)
    elif data.startswith("emp_"): await show_employee_detail(update, context)

# ─── ADMIN COMMANDS ───
def is_admin(chat_id):
    return str(chat_id) == str(ADMIN_CHAT_ID)

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔️ Нет доступа.")
        return

    total, active, finished, avg_final, today = get_summary_stats()
    employees = get_all_employees()

    text = (f"📊 *Статистика Академии DAFNA*\n\n"
            f"👥 Всего зарегистрировано: *{total}*\n"
            f"📚 Начали обучение: *{active}*\n"
            f"🏆 Завершили программу: *{finished}*\n"
            f"⭐️ Средний балл финала: *{avg_final}%*\n"
            f"🟢 Активны сегодня: *{today}*\n\n"
            f"*Сотрудники:*\n")

    keyboard = []
    for emp in employees[:15]:
        cid, uname, fname, joined, _ = emp
        l, q, avg, _, last = get_employee_stats(cid)
        pct = round(l / TOTAL_LESSONS * 100)
        bar = '█' * round(pct/10) + '░' * (10-round(pct/10))
        text += f"\n👤 *{fname}* (@{uname})\n`{bar}` {pct}% · ✅{q} · ⭐️{avg}%\n"
        keyboard.append([InlineKeyboardButton(
            f"👤 {fname} — {pct}%",
            callback_data=f"emp_{cid}")])

    keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="refresh_stats")])
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard))

async def show_employee_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_chat.id): return

    cid = query.data.replace("emp_", "")
    emp = get_employee(cid)
    if not emp:
        await query.edit_message_text("Сотрудник не найден")
        return

    cid_val, uname, fname, joined, showroom = emp
    lessons, quizzes, avg, quiz_details, last = get_employee_stats(cid_val)
    pct = round(lessons / TOTAL_LESSONS * 100)
    bar = '█' * round(pct/10) + '░' * (10-round(pct/10))

    modules_text = ""
    done_mods = {str(qd[0]): (qd[1], qd[2]) for qd in quiz_details}
    for i in range(1, 10):
        mid = 'final' if i == 9 else str(i)
        mname = MODULE_NAMES.get(i, f"Модуль {i}")
        if mid in done_mods:
            s, dt = done_mods[mid]
            e = "✅" if s >= 60 else "⚠️"
            modules_text += f"{e} {mname}: *{s}%* ({dt})\n"
        else:
            modules_text += f"🔒 {mname}\n"

    text = (f"👤 *{fname}*\n"
            f"💬 @{uname}\n"
            f"📅 Зарегистрирован: {joined}\n"
            f"🕐 Последняя активность: {last or 'нет'}\n\n"
            f"`{bar}` *{pct}%*\n"
            f"📚 Уроков: {lessons}/{TOTAL_LESSONS} · ✅ Тестов: {quizzes} · ⭐️ {avg}%\n\n"
            f"*Прогресс по модулям:*\n{modules_text}")

    kb = [[InlineKeyboardButton("⬅️ К списку", callback_data="back_to_stats")]]
    await query.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))

async def admin_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔️ Нет доступа.")
        return
    bot_username = (await context.bot.get_me()).username
    invite_link = f"https://t.me/{bot_username}?start={INVITE_CODE}"
    await update.message.reply_text(
        f"🔗 *Ссылка для новых сотрудников:*\n\n`{invite_link}`\n\n"
        f"Отправьте эту ссылку новому сотруднику.",
        parse_mode="Markdown")

async def admin_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export all stats as CSV"""
    if not is_admin(update.effective_chat.id):
        await update.message.reply_text("⛔️ Нет доступа.")
        return

    employees = get_all_employees()
    lines = ["Имя,Telegram,Дата регистрации,Уроков,Тестов,Средний балл,%% прогресса,Финальный тест"]
    for emp in employees:
        cid, uname, fname, joined, _ = emp
        l, q, avg, quiz_details, _ = get_employee_stats(cid)
        pct = round(l / TOTAL_LESSONS * 100)
        final = next((f"{qd[1]}%" for qd in quiz_details if str(qd[0])=='final'), "Не сдан")
        lines.append(f"{fname},@{uname},{joined},{l},{q},{avg}%,{pct}%,{final}")

    csv_content = "\n".join(lines)
    from io import BytesIO
    bio = BytesIO(csv_content.encode('utf-8-sig'))
    bio.name = f"dafna_stats_{datetime.now().strftime('%d%m%Y')}.csv"
    await update.message.reply_document(document=bio,
        filename=bio.name, caption="📊 Статистика Академии DAFNA")

async def webapp_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    employee = get_employee(chat_id)
    if not employee: return
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        action = data.get("action")
        module_id = str(data.get("module_id", ""))
        lesson_id = data.get("lesson_id", "")
        score = int(data.get("score", 0))
        name = employee[2]

        is_new = save_progress(chat_id, module_id, lesson_id, action, score)
        if not is_new: return

        mod_name = MODULE_NAMES.get(int(module_id) if module_id.isdigit() else module_id, f"Модуль {module_id}")
        now = datetime.now().strftime("%d.%m.%Y %H:%M")

        if action == "lesson_done":
            admin_msg = (f"📖 *Урок пройден*\n👤 {name}\n📚 {mod_name}\n📝 {lesson_id}\n🕐 {now}")
        elif action in ("quiz_done", "final_done"):
            emoji = "🏆" if score >= 80 else ("✅" if score >= 60 else "📝")
            result = "Отлично!" if score >= 80 else ("Зачёт!" if score >= 60 else "Нужно повторить")
            admin_msg = (f"{emoji} *{'Финальный тест' if action=='final_done' else 'Тест'} сдан*\n"
                        f"👤 {name}\n📚 {mod_name}\n⭐️ *{score}%* — {result}\n🕐 {now}")
            resp_text = f"{emoji} Результат: *{score}%* — {result}"
            if action == "final_done" and score >= 70:
                resp_text += "\n\n🎉 Поздравляем! Вы прошли программу обучения DAFNA!"
            await update.message.reply_text(resp_text, parse_mode="Markdown")
        else:
            return

        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode="Markdown")
        except Exception as e:
            print(f"Admin notify error: {e}")
    except Exception as e:
        print(f"Webapp data error: {e}")

def main():
    init_db()
    print("🚀 Бот DAFNA Academy запускается...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("link", admin_link))
    app.add_handler(CommandHandler("export", admin_export))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("✅ Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
