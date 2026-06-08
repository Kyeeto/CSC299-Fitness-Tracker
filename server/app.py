import csv
import io
import json
import os
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, request, send_file, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db, init_db

app = Flask(__name__, static_folder='static', static_url_path='')
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
init_db()


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# ── Auth ──────────────────────────────────────────────────────

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    db = get_db()
    try:
        cur = db.execute(
            'INSERT INTO users (username, password_hash) VALUES (?, ?)',
            (username, generate_password_hash(password))
        )
        db.commit()
        user_id = cur.lastrowid
        session['user_id'] = user_id
        session['username'] = username
        db.close()
        return jsonify({'id': user_id, 'username': username}), 201
    except Exception:
        db.close()
        return jsonify({'error': 'Username already taken'}), 409


@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    db.close()
    if user is None or not check_password_hash(user['password_hash'], password):
        return jsonify({'error': 'Invalid username or password'}), 401
    session['user_id'] = user['id']
    session['username'] = user['username']
    return jsonify({'id': user['id'], 'username': user['username']})


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})


@app.route('/api/auth/me', methods=['GET'])
def me():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    return jsonify({'id': session['user_id'], 'username': session['username']})


# ── Exercises ─────────────────────────────────────────────────

@app.route('/api/exercises', methods=['GET'])
@require_auth
def list_exercises():
    db = get_db()
    rows = db.execute('SELECT * FROM exercises ORDER BY muscle_group, name').fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/exercises', methods=['POST'])
@require_auth
def create_exercise():
    data = request.json or {}
    if not data.get('name') or not data.get('muscle_group'):
        return jsonify({'error': 'name and muscle_group required'}), 400
    db = get_db()
    try:
        cur = db.execute(
            'INSERT INTO exercises (name, muscle_group) VALUES (?, ?)',
            (data['name'].strip(), data['muscle_group'].strip())
        )
        db.commit()
        row = db.execute('SELECT * FROM exercises WHERE id = ?', (cur.lastrowid,)).fetchone()
        db.close()
        return jsonify(dict(row)), 201
    except Exception as e:
        db.close()
        return jsonify({'error': str(e)}), 400


# ── Workouts ──────────────────────────────────────────────────

@app.route('/api/workouts', methods=['GET'])
@require_auth
def list_workouts():
    user_id = session['user_id']
    db = get_db()
    workouts = db.execute(
        'SELECT * FROM workouts WHERE user_id = ? ORDER BY date DESC', (user_id,)
    ).fetchall()
    result = []
    for w in workouts:
        sets = db.execute('''
            SELECT ws.*, e.name AS exercise_name, e.muscle_group
            FROM workout_sets ws
            JOIN exercises e ON ws.exercise_id = e.id
            WHERE ws.workout_id = ?
        ''', (w['id'],)).fetchall()
        result.append({**dict(w), 'sets': [dict(s) for s in sets]})
    db.close()
    return jsonify(result)


@app.route('/api/workouts', methods=['POST'])
@require_auth
def create_workout():
    user_id = session['user_id']
    data = request.json or {}
    if not data.get('date'):
        return jsonify({'error': 'date required'}), 400

    db = get_db()
    cur = db.execute(
        'INSERT INTO workouts (user_id, date, notes) VALUES (?, ?, ?)',
        (user_id, data['date'], data.get('notes', ''))
    )
    workout_id = cur.lastrowid
    new_prs = []

    for s in data.get('sets', []):
        db.execute(
            'INSERT INTO workout_sets (workout_id, exercise_id, sets, reps, weight) VALUES (?, ?, ?, ?, ?)',
            (workout_id, s['exercise_id'], s['sets'], s['reps'], s['weight'])
        )
        pr = db.execute(
            'SELECT * FROM personal_records WHERE exercise_id = ? AND user_id = ?',
            (s['exercise_id'], user_id)
        ).fetchone()
        ex = db.execute('SELECT name FROM exercises WHERE id = ?', (s['exercise_id'],)).fetchone()
        if pr is None:
            db.execute(
                'INSERT INTO personal_records (exercise_id, weight, date_achieved, user_id) VALUES (?, ?, ?, ?)',
                (s['exercise_id'], s['weight'], data['date'], user_id)
            )
            new_prs.append({'exercise': ex['name'], 'weight': s['weight']})
        elif s['weight'] > pr['weight']:
            db.execute(
                'UPDATE personal_records SET weight = ?, date_achieved = ? WHERE id = ?',
                (s['weight'], data['date'], pr['id'])
            )
            new_prs.append({'exercise': ex['name'], 'weight': s['weight']})

    db.commit()
    workout = db.execute('SELECT * FROM workouts WHERE id = ?', (workout_id,)).fetchone()
    db.close()
    return jsonify({**dict(workout), 'new_prs': new_prs}), 201


@app.route('/api/workouts/<int:workout_id>', methods=['DELETE'])
@require_auth
def delete_workout(workout_id):
    user_id = session['user_id']
    db = get_db()
    db.execute('DELETE FROM workouts WHERE id = ? AND user_id = ?', (workout_id, user_id))
    db.commit()
    db.close()
    return jsonify({'deleted': workout_id})


# ── Personal Records ──────────────────────────────────────────

@app.route('/api/records', methods=['GET'])
@require_auth
def list_records():
    user_id = session['user_id']
    db = get_db()
    rows = db.execute('''
        SELECT pr.*, e.name AS exercise_name, e.muscle_group
        FROM personal_records pr
        JOIN exercises e ON pr.exercise_id = e.id
        WHERE pr.user_id = ?
        ORDER BY e.muscle_group, e.name
    ''', (user_id,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ── Goals ─────────────────────────────────────────────────────

@app.route('/api/goals', methods=['GET'])
@require_auth
def list_goals():
    user_id = session['user_id']
    db = get_db()
    rows = db.execute(
        'SELECT * FROM goals WHERE user_id = ? AND active = 1 ORDER BY start_date DESC',
        (user_id,)
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/goals', methods=['POST'])
@require_auth
def create_goal():
    user_id = session['user_id']
    data = request.json or {}
    required = ('type', 'target', 'start_date', 'end_date')
    if not all(k in data for k in required):
        return jsonify({'error': 'type, target, start_date, end_date required'}), 400
    db = get_db()
    cur = db.execute(
        'INSERT INTO goals (user_id, type, target, start_date, end_date) VALUES (?, ?, ?, ?, ?)',
        (user_id, data['type'], data['target'], data['start_date'], data['end_date'])
    )
    db.commit()
    row = db.execute('SELECT * FROM goals WHERE id = ?', (cur.lastrowid,)).fetchone()
    db.close()
    return jsonify(dict(row)), 201


@app.route('/api/goals/<int:goal_id>', methods=['DELETE'])
@require_auth
def delete_goal(goal_id):
    user_id = session['user_id']
    db = get_db()
    db.execute('UPDATE goals SET active = 0 WHERE id = ? AND user_id = ?', (goal_id, user_id))
    db.commit()
    db.close()
    return jsonify({'deleted': goal_id})


# ── Summary stats ────────────────────────────────────────────

@app.route('/api/stats/summary', methods=['GET'])
@require_auth
def stats_summary():
    user_id = session['user_id']
    db = get_db()
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())

    total_workouts  = db.execute(
        'SELECT COUNT(*) FROM workouts WHERE user_id = ?', (user_id,)
    ).fetchone()[0]
    total_records   = db.execute(
        'SELECT COUNT(*) FROM personal_records WHERE user_id = ?', (user_id,)
    ).fetchone()[0]
    total_exercises = db.execute('SELECT COUNT(*) FROM exercises').fetchone()[0]
    this_week       = db.execute(
        'SELECT COUNT(*) FROM workouts WHERE user_id = ? AND date >= ?',
        (user_id, str(week_start))
    ).fetchone()[0]
    last_workout    = db.execute(
        'SELECT date FROM workouts WHERE user_id = ? ORDER BY date DESC LIMIT 1', (user_id,)
    ).fetchone()

    db.close()
    return jsonify({
        'total_workouts':  total_workouts,
        'total_records':   total_records,
        'total_exercises': total_exercises,
        'this_week':       this_week,
        'last_workout':    last_workout['date'] if last_workout else None,
    })


# ── Alerts ────────────────────────────────────────────────────

@app.route('/api/alerts', methods=['GET'])
@require_auth
def get_alerts():
    user_id = session['user_id']
    db = get_db()
    today = datetime.now().date()
    goals = db.execute(
        'SELECT * FROM goals WHERE user_id = ? AND active = 1 AND end_date >= ?',
        (user_id, str(today))
    ).fetchall()
    alerts = []

    for goal in goals:
        if goal['type'] == 'frequency':
            start = datetime.strptime(goal['start_date'], '%Y-%m-%d').date()
            end   = datetime.strptime(goal['end_date'],   '%Y-%m-%d').date()
            days_elapsed = (today - start).days + 1
            count = db.execute(
                'SELECT COUNT(*) AS cnt FROM workouts WHERE user_id = ? AND date >= ? AND date <= ?',
                (user_id, goal['start_date'], str(today))
            ).fetchone()['cnt']

            expected = goal['target'] * (days_elapsed / 7)
            if count < expected - 0.5:
                days_left = (end - today).days
                needed = goal['target'] - count
                alerts.append({
                    'type': 'frequency_warning',
                    'goal_id': goal['id'],
                    'message': (
                        f"Behind on your goal of {goal['target']} workouts/week. "
                        f"Done this period: {count}. "
                        f"Need {max(0, needed)} more with {days_left} day(s) left."
                    )
                })

    db.close()
    return jsonify(alerts)


# ── Stats ─────────────────────────────────────────────────────

@app.route('/api/stats/muscle_groups', methods=['GET'])
@require_auth
def stats_muscle_groups():
    user_id = session['user_id']
    db = get_db()
    rows = db.execute('''
        SELECT e.muscle_group, COUNT(ws.id) AS total_sets
        FROM workout_sets ws
        JOIN exercises e ON ws.exercise_id = e.id
        JOIN workouts w ON ws.workout_id = w.id
        WHERE w.user_id = ?
        GROUP BY e.muscle_group
    ''', (user_id,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/stats/weekly_frequency', methods=['GET'])
@require_auth
def stats_weekly_frequency():
    user_id = session['user_id']
    db = get_db()
    today = datetime.now().date()
    weeks = []
    for i in range(7, -1, -1):
        week_start = today - timedelta(weeks=i, days=today.weekday())
        week_end   = week_start + timedelta(days=6)
        count = db.execute(
            'SELECT COUNT(*) AS cnt FROM workouts WHERE user_id = ? AND date >= ? AND date <= ?',
            (user_id, str(week_start), str(week_end))
        ).fetchone()['cnt']
        weeks.append({'week': str(week_start), 'count': count})
    db.close()
    return jsonify(weeks)


@app.route('/api/stats/strength/<int:exercise_id>', methods=['GET'])
@require_auth
def stats_strength(exercise_id):
    user_id = session['user_id']
    db = get_db()
    rows = db.execute('''
        SELECT w.date, MAX(ws.weight) AS max_weight
        FROM workout_sets ws
        JOIN workouts w ON ws.workout_id = w.id
        WHERE ws.exercise_id = ? AND w.user_id = ?
        GROUP BY w.date
        ORDER BY w.date
    ''', (exercise_id, user_id)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ── Templates ─────────────────────────────────────────────────

@app.route('/api/templates', methods=['GET'])
@require_auth
def list_templates():
    user_id = session['user_id']
    db = get_db()
    rows = db.execute(
        'SELECT * FROM templates WHERE user_id = ? ORDER BY name', (user_id,)
    ).fetchall()
    db.close()
    return jsonify([{**dict(r), 'exercises': json.loads(r['exercises'])} for r in rows])


@app.route('/api/templates', methods=['POST'])
@require_auth
def create_template():
    user_id = session['user_id']
    data = request.json or {}
    if not data.get('name') or not data.get('exercises'):
        return jsonify({'error': 'name and exercises required'}), 400
    db = get_db()
    try:
        cur = db.execute(
            'INSERT INTO templates (user_id, name, description, exercises) VALUES (?, ?, ?, ?)',
            (user_id, data['name'], data.get('description', ''), json.dumps(data['exercises']))
        )
        db.commit()
        row = db.execute('SELECT * FROM templates WHERE id = ?', (cur.lastrowid,)).fetchone()
        db.close()
        return jsonify({**dict(row), 'exercises': json.loads(row['exercises'])}), 201
    except Exception as e:
        db.close()
        return jsonify({'error': str(e)}), 400


@app.route('/api/templates/<int:template_id>', methods=['DELETE'])
@require_auth
def delete_template(template_id):
    user_id = session['user_id']
    db = get_db()
    db.execute('DELETE FROM templates WHERE id = ? AND user_id = ?', (template_id, user_id))
    db.commit()
    db.close()
    return jsonify({'deleted': template_id})


# ── CSV Export ────────────────────────────────────────────────

@app.route('/api/export/csv', methods=['GET'])
@require_auth
def export_csv():
    user_id = session['user_id']
    db = get_db()
    rows = db.execute('''
        SELECT w.date, w.notes, e.name AS exercise, e.muscle_group,
               ws.sets, ws.reps, ws.weight
        FROM workout_sets ws
        JOIN workouts w ON ws.workout_id = w.id
        JOIN exercises e ON ws.exercise_id = e.id
        WHERE w.user_id = ?
        ORDER BY w.date, e.name
    ''', (user_id,)).fetchall()
    db.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Date', 'Notes', 'Exercise', 'Muscle Group', 'Sets', 'Reps', 'Weight (lbs)'])
    for r in rows:
        writer.writerow([r['date'], r['notes'], r['exercise'],
                         r['muscle_group'], r['sets'], r['reps'], r['weight']])

    return send_file(
        io.BytesIO(buf.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='workout_history.csv'
    )


if __name__ == '__main__':
    app.run(debug=True, port=5000)
