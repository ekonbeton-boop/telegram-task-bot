from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'super_secret_key_2025'  # 🔐 Обязательно для сессий

# 🔐 Настройка логина и пароля (измени на свои!)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password123"

DATABASE = 'tasks.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# 🔐 Проверка аутентификации
def login_required(f):
    def wrap(*args, **kwargs):
        if 'logged_in' not in session:
            flash('Пожалуйста, войдите в систему.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# 🔐 Страница входа
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['logged_in'] = True
            session['username'] = username
            flash('✅ Вход выполнен!', 'success')
            return redirect(url_for('index'))
        else:
            flash('❌ Неверный логин или пароль', 'danger')
    return render_template('login.html')

# 🔐 Выход
@app.route('/logout')
def logout():
    session.clear()
    flash('🚪 Вы вышли из системы.', 'info')
    return redirect(url_for('login'))

# 🏠 Главная страница — список задач (только для авторизованных)
@app.route('/')
@login_required
def index():
    filter_status = request.args.get('filter', 'all')

    conn = get_db_connection()
    if filter_status == 'open':
        tasks = conn.execute('SELECT * FROM tasks WHERE is_closed = 0 ORDER BY id DESC').fetchall()
    elif filter_status == 'closed':
        tasks = conn.execute('SELECT * FROM tasks WHERE is_closed = 1 ORDER BY id DESC').fetchall()
    else:
        tasks = conn.execute('SELECT * FROM tasks ORDER BY id DESC').fetchall()
    conn.close()

    return render_template('index.html', tasks=tasks, filter=filter_status)

# ➕ Добавление задачи
@app.route('/add', methods=['POST'])
@login_required
def add_task():
    description = request.form['description'].strip()
    if not description:
        flash('Описание не может быть пустым!', 'danger')
        return redirect(url_for('index'))

    conn = get_db_connection()
    conn.execute('INSERT INTO tasks (description) VALUES (?)', (description,))
    conn.commit()
    conn.close()

    flash('✅ Задача добавлена!', 'success')
    return redirect(url_for('index'))

# ✏️ Редактирование задачи
@app.route('/edit/<int:task_id>', methods=['POST'])
@login_required
def edit_task(task_id):
    description = request.form['description'].strip()
    if not description:
        return jsonify({'error': 'Описание не может быть пустым'}), 400

    conn = get_db_connection()
    conn.execute('UPDATE tasks SET description = ? WHERE id = ?', (description, task_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True})

# ✅ Закрытие задачи
@app.route('/close/<int:task_id>', methods=['POST'])
@login_required
def close_task(task_id):
    try:
        time_spent = float(request.form['time_spent'])
    except ValueError:
        return jsonify({'error': 'Время должно быть числом'}), 400

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db_connection()
    conn.execute('''
        UPDATE tasks
        SET closed_at = ?, time_spent = ?, is_closed = 1
        WHERE id = ?
    ''', (now, time_spent, task_id))
    conn.commit()
    conn.close()

    return jsonify({'success': True})

# 🗑️ Удаление задачи
@app.route('/delete/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': True})

# 📊 API для статистики
@app.route('/api/stats')
@login_required
def stats():
    conn = get_db_connection()
    total = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
    open_count = conn.execute('SELECT COUNT(*) FROM tasks WHERE is_closed = 0').fetchone()[0]
    closed_count = conn.execute('SELECT COUNT(*) FROM tasks WHERE is_closed = 1').fetchone()[0]

    avg_time_row = conn.execute('SELECT AVG(time_spent) FROM tasks WHERE is_closed = 1').fetchone()
    avg_time = round(avg_time_row[0], 2) if avg_time_row[0] else 0

    top_long_tasks = conn.execute('''
        SELECT description, time_spent
        FROM tasks
        WHERE is_closed = 1 AND time_spent IS NOT NULL
        ORDER BY time_spent DESC
        LIMIT 5
    ''').fetchall()

    conn.close()

    return jsonify({
        'total': total,
        'open': open_count,
        'closed': closed_count,
        'avg_time': avg_time,
        'top_long_tasks': [dict(row) for row in top_long_tasks]
    })

# 📥 Экспорт в Excel
import pandas as pd
from io import BytesIO
from flask import send_file

@app.route('/export')
@login_required
def export_excel():
    conn = get_db_connection()
    tasks = conn.execute('''
        SELECT
            id,
            description,
            created_at,
            closed_at,
            time_spent,
            CASE WHEN is_closed = 1 THEN 'Закрыта' ELSE 'Открыта' END as status
        FROM tasks
        ORDER BY id DESC
    ''').fetchall()
    conn.close()

    # Преобразуем в DataFrame
    df = pd.DataFrame(tasks, columns=['ID', 'Описание', 'Создана', 'Закрыта', 'Потрачено часов', 'Статус'])

    # Экспорт в Excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Задачи')
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        download_name='tasks_export.xlsx',
        as_attachment=True
    )

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        print("⚠️ База данных не найдена! Запустите сначала Telegram-бота (main.py), чтобы она создалась.")
        exit(1)

    print("🌐 Запускаю веб-интерфейс...")
    print("🔑 Логин: admin | Пароль: password123")
    print("Открой в браузере: http://127.0.0.1:5000")
    app.run(debug=True)
