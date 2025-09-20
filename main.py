import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from datetime import datetime
import sqlite3
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация БД
def init_db():
    conn = sqlite3.connect('tasks.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            closed_at DATETIME,
            time_spent REAL,
            is_closed BOOLEAN DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

# Главное меню с кнопками
MAIN_MENU_KEYBOARD = [
    ["➕ Добавить задачу", "✅ Закрыть задачу"],
    ["📋 Показать все", "🗑️ Удалить задачу"],
    ["🕗 Настроить отчёт"]
]

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)

# Команда /start — показываем меню
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context)

# Обработка нажатий на основные кнопки
async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "➕ Добавить задачу":
        await update.message.reply_text("Введите описание задачи:")
        context.user_data['awaiting_task_description'] = True
    elif text == "✅ Закрыть задачу":
        await show_open_tasks_for_closing(update, context)
    elif text == "📋 Показать все":
        await show_task_filters(update, context)
    elif text == "🗑️ Удалить задачу":
        await update.message.reply_text("Введите ID задачи для удаления:")
        context.user_data['awaiting_delete_id'] = True
    elif text == "🕗 Настроить отчёт":
        await set_daily(update, context)
    else:
        await update.message.reply_text("Неизвестная команда. Используйте кнопки.")

# Добавление задачи через текст
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_task_description'):
        description = update.message.text
        conn = sqlite3.connect('tasks.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO tasks (description) VALUES (?)', (description,))
        conn.commit()
        task_id = cursor.lastrowid
        conn.close()

        await update.message.reply_text(f"✅ Задача добавлена!\nID: {task_id}\nОписание: {description}")
        context.user_data['awaiting_task_description'] = False
        await show_main_menu(update, context)

    elif context.user_data.get('awaiting_time_input'):
        await handle_time_input(update, context)

    elif context.user_data.get('awaiting_delete_id'):
        await handle_delete_task(update, context)

    elif context.user_data.get('awaiting_edit_id'):
        await handle_edit_description(update, context)

    else:
        await update.message.reply_text("Не понимаю. Выберите действие через кнопки.")

# Показать фильтры при показе задач
async def show_task_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("⏳ Только открытые", callback_data="filter_open"),
            InlineKeyboardButton("✅ Только закрытые", callback_data="filter_closed"),
        ],
        [
            InlineKeyboardButton("👁️ Все задачи", callback_data="filter_all")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите фильтр:", reply_markup=reply_markup)

# Показать задачи по фильтру
async def show_tasks_by_filter(update: Update, context: ContextTypes.DEFAULT_TYPE, filter_type="all"):
    query = update.callback_query
    await query.answer()

    conn = sqlite3.connect('tasks.db')
    cursor = conn.cursor()

    if filter_type == "open":
        cursor.execute('SELECT id, description, created_at, closed_at, time_spent, is_closed FROM tasks WHERE is_closed = 0 ORDER BY id DESC')
        title = "⏳ ОТКРЫТЫЕ ЗАДАЧИ"
    elif filter_type == "closed":
        cursor.execute('SELECT id, description, created_at, closed_at, time_spent, is_closed FROM tasks WHERE is_closed = 1 ORDER BY id DESC')
        title = "✅ ЗАКРЫТЫЕ ЗАДАЧИ"
    else:
        cursor.execute('SELECT id, description, created_at, closed_at, time_spent, is_closed FROM tasks ORDER BY id DESC')
        title = "📋 ВСЕ ЗАДАЧИ"

    tasks = cursor.fetchall()
    conn.close()

    if not tasks:
        await query.edit_message_text(f"📭 {title}: задач нет.")
        return

    await query.edit_message_text(f"👇 {title}:")

    for t in tasks:
        status = "✅ ЗАКРЫТА" if t[5] else "⏳ ОТКРЫТА"
        msg = f"🔖 ID: {t[0]}\n📝 {t[1]}\n📆 Создана: {t[2]}\n{status}"

        if t[5]:
            msg += f"\n🕒 Закрыта: {t[3]}\n⏱️ Потрачено: {t[4]} ч."

        # Кнопки под каждой задачей
        keyboard = [
            [
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{t[0]}"),
                InlineKeyboardButton("🗑️ Удалить", callback_data=f"delete_{t[0]}"),
            ]
        ]
        if not t[5]:  # если открыта — показываем "Закрыть"
            keyboard[0].insert(0, InlineKeyboardButton("✅ Закрыть", callback_data=f"close_{t[0]}"))

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_chat.send_message(msg, reply_markup=reply_markup)

# Показать открытые задачи для закрытия (с кнопками)
async def show_open_tasks_for_closing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('tasks.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, description FROM tasks WHERE is_closed = 0 ORDER BY id')
    open_tasks = cursor.fetchall()
    conn.close()

    if not open_tasks:
        await update.message.reply_text("📭 Нет открытых задач для закрытия.")
        return

    keyboard = []
    for task in open_tasks:
        keyboard.append([
            InlineKeyboardButton(f"ID {task[0]}: {task[1][:30]}...", callback_data=f"close_{task[0]}")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите задачу для закрытия:", reply_markup=reply_markup)

# Обработка нажатия кнопки "Закрыть задачу"
async def handle_close_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    task_id = int(query.data.split('_')[1])
    context.user_data['closing_task_id'] = task_id

    await query.edit_message_text(text=f"Вы выбрали задачу ID {task_id}. Введите потраченное время (в часах):")
    context.user_data['awaiting_time_input'] = True

# Обработка ввода времени для закрытия задачи
async def handle_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_time_input'):
        try:
            time_spent = float(update.message.text)
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите число (например, 2.5).")
            return

        task_id = context.user_data['closing_task_id']

        conn = sqlite3.connect('tasks.db')
        cursor = conn.cursor()
        cursor.execute('SELECT description, is_closed FROM tasks WHERE id = ?', (task_id,))
        task = cursor.fetchone()

        if not task:
            await update.message.reply_text(f"Задача с ID {task_id} не найдена.")
            return
        if task[1]:
            await update.message.reply_text("Задача уже закрыта!")
            return

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            UPDATE tasks
            SET closed_at = ?, time_spent = ?, is_closed = 1
            WHERE id = ?
        ''', (now, time_spent, task_id))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"✅ Задача \"{task[0]}\" закрыта.\nПотрачено времени: {time_spent} ч.")
        context.user_data['awaiting_time_input'] = False
        await show_main_menu(update, context)

# Удаление задачи по ID (через текст)
async def handle_delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        task_id = int(update.message.text)
    except ValueError:
        await update.message.reply_text("ID должен быть числом!")
        return

    conn = sqlite3.connect('tasks.db')
    cursor = conn.cursor()
    cursor.execute('SELECT description FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()

    if not task:
        await update.message.reply_text(f"Задача с ID {task_id} не найдена.")
        return

    cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"🗑️ Задача \"{task[0]}\" удалена.")
    context.user_data['awaiting_delete_id'] = False
    await show_main_menu(update, context)

# Обработка удаления через кнопку под карточкой
async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    task_id = int(query.data.split('_')[1])

    conn = sqlite3.connect('tasks.db')
    cursor = conn.cursor()
    cursor.execute('SELECT description FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()

    if not task:
        await query.edit_message_text("Задача уже удалена.")
        return

    cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()

    await query.edit_message_text(f"🗑️ Задача \"{task[0]}\" удалена.")

# Редактирование задачи
async def handle_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    task_id = int(query.data.split('_')[1])
    context.user_data['editing_task_id'] = task_id

    await query.edit_message_text("Введите новое описание задачи:")
    context.user_data['awaiting_edit_id'] = True

# Обработка нового описания
async def handle_edit_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_description = update.message.text
    task_id = context.user_data['editing_task_id']

    conn = sqlite3.connect('tasks.db')
    cursor = conn.cursor()
    cursor.execute('SELECT description FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()

    if not task:
        await update.message.reply_text("Задача не найдена.")
        return

    cursor.execute('UPDATE tasks SET description = ? WHERE id = ?', (new_description, task_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✏️ Задача обновлена: \"{new_description}\"")
    context.user_data['awaiting_edit_id'] = False
    await show_main_menu(update, context)

# Установка ежедневного отчёта
async def set_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    scheduler = context.application.bot_data.get('scheduler')

    if not scheduler:
        await update.message.reply_text("❌ Планировщик не запущен.")
        return

    current_jobs = scheduler.get_jobs()
    for job in current_jobs:
        if job.name == str(chat_id):
            job.remove()

    scheduler.add_job(
        daily_report,
        trigger="cron",
        hour=9, minute=0,
        chat_id=chat_id,
        name=str(chat_id),
        replace_existing=True
    )

    await update.message.reply_text("✅ Ежедневный отчёт установлен на 09:00.")

# Ежедневный отчёт
async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.kwargs.get('chat_id') or context.job.args[0] if context.job.args else None
    if not chat_id:
        logger.error("Не удалось определить chat_id для отчёта")
        return

    conn = sqlite3.connect('tasks.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, description, created_at FROM tasks WHERE is_closed = 0')
    open_tasks = cursor.fetchall()
    conn.close()

    if not open_tasks:
        await context.bot.send_message(chat_id=chat_id, text="📭 Нет открытых задач.")
        return

    now = datetime.now()
    msg = "📅 ЕЖЕДНЕВНЫЙ ОТЧЁТ — ОТКРЫТЫЕ ЗАДАЧИ:\n\n"
    for t in open_tasks:
        created = datetime.strptime(t[2], '%Y-%m-%d %H:%M:%S')
        delta = now - created
        days = delta.days
        hours = delta.seconds // 3600

        if days > 0:
            time_str = f"{days} дн."
        else:
            time_str = f"{hours} ч."

        msg += f"ID: {t[0]} | {t[1]}\nВисит: {time_str}\n\n"

    await context.bot.send_message(chat_id=chat_id, text=msg)

# Запуск планировщика внутри event loop
async def post_init(application: Application):
    scheduler = AsyncIOScheduler()
    scheduler.start()
    application.bot_data['scheduler'] = scheduler
    logger.info("✅ Планировщик запущен!")

# Основная функция
def main():
    init_db()

    # 🔑 ТОКЕН
    application = Application.builder().token("8296163167:AAHPn-gjTODYfao8G7_aWY8nEsczGgSwiJY").build()

    # Обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^(➕ Добавить задачу|✅ Закрыть задачу|📋 Показать все|🗑️ Удалить задачу|🕗 Настроить отчёт)$"), handle_main_menu))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(CallbackQueryHandler(show_tasks_by_filter, pattern="^filter_(open|closed|all)$"))
    application.add_handler(CallbackQueryHandler(handle_close_task_callback, pattern=r"^close_\d+$"))
    application.add_handler(CallbackQueryHandler(handle_delete_callback, pattern=r"^delete_\d+$"))
    application.add_handler(CallbackQueryHandler(handle_edit_callback, pattern=r"^edit_\d+$"))

    # Старые команды — для совместимости
    application.add_handler(CommandHandler("add", add_task))
    application.add_handler(CommandHandler("close", close_task))
    application.add_handler(CommandHandler("list", list_tasks))
    application.add_handler(CommandHandler("setdaily", set_daily))

    # Планировщик
    application.post_init = post_init

    # Запуск
    logger.info("🚀 Бот запускается...")
    application.run_polling()

# Старые функции — оставим для совместимости
async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /add <описание задачи>")
        return
    description = ' '.join(context.args)
    conn = sqlite3.connect('tasks.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tasks (description) VALUES (?)', (description,))
    conn.commit()
    task_id = cursor.lastrowid
    conn.close()
    await update.message.reply_text(f"✅ Задача добавлена!\nID: {task_id}\nОписание: {description}")

async def close_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /close <id> <часы>")
        return
    try:
        task_id = int(context.args[0])
        time_spent = float(context.args[1])
    except ValueError:
        await update.message.reply_text("ID и время должны быть числами!")
        return
    conn = sqlite3.connect('tasks.db')
    cursor = conn.cursor()
    cursor.execute('SELECT description, is_closed FROM tasks WHERE id = ?', (task_id,))
    task = cursor.fetchone()
    if not task:
        await update.message.reply_text(f"Задача с ID {task_id} не найдена.")
        return
    if task[1]:
        await update.message.reply_text("Задача уже закрыта!")
        return
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('UPDATE tasks SET closed_at = ?, time_spent = ?, is_closed = 1 WHERE id = ?', (now, time_spent, task_id))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Задача \"{task[0]}\" закрыта.\nПотрачено времени: {time_spent} ч.")

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_task_filters(update, context)

if __name__ == '__main__':
    main()
