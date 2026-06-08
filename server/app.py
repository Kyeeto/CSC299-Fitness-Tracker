import csv
import io
import json
import os
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_file, send_from_directory

from database import get_db, init_db

app = Flask(__name__, static_folder='static', static_url_path='')
init_db()


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


# ── Exercises ─────────────────────────────────────────────────

@app.route('/api/exercises', methods=['GET'])
def list_exercises():
    db = get_db()
    rows = db.execute('SELECT * FROM exercises ORDER BY muscle_group, name').fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/exercises', methods=['POST'])
def create_exercise():
    data = request.json
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
def list_workouts():
    db = get_db()
    workouts = db.execute('SELECT * FROM workouts ORDER BY date DESC').fetchall()
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
def create_workout():
    data = request.json
    if not data.get('date'):
        return jsonify({'error': 'date required'}), 400

    db = get_db()
    cur = db.execute(
        'INSERT INTO workouts (date, notes) VALUES (?, ?)',
        (data['date'], data.get('notes', ''))
    )
    workout_id = cur.lastrowid
    new_prs = []

    for s in data.get('sets', []):
        db.execute(
            'INSERT INTO workout_sets (workout_id, exercise_id, sets, reps, weight) VALUES (?, ?, ?, ?, ?)',
            (workout_id, s['exercise_id'], s['sets'], s['reps'], s['weight'])
        )
        pr = db.execute(
            'SELECT * FROM personal_records WHERE exercise_id = ?', (s['exercise_id'],)
        ).fetchone()
        if pr is None or s['weight'] > pr['weight']:
            db.execute('''
                INSERT INTO personal_records (exercise_id, weight, date_achieved)
                VALUES (?, ?, ?)
                ON CONFLICT(exercise_id) DO UPDATE
                    SET weight = excluded.weight, date_achieved = excluded.date_achieved
            ''', (s['exercise_id'], s['weight'], data['date']))
            ex = db.execute('SELECT name FROM exercises WHERE id = ?', (s['exercise_id'],)).fetchone()
            new_prs.append({'exercise': ex['name'], 'weight': s['weight']})

    db.commit()
    workout = db.execute('SELECT * FROM workouts WHERE id = ?', (workout_id,)).fetchone()
    db.close()
    return jsonify({**dict(workout), 'new_prs': new_prs}), 201


@app.route('/api/workouts/<int:workout_id>', methods=['DELETE'])
def delete_workout(workout_id):
    db = get_db()
    db.execute('DELETE FROM workouts WHERE id = ?', (workout_id,))
    db.commit()
    db.close()
    return jsonify({'deleted': workout_id})


# ── Personal Records ──────────────────────────────────────────

@app.route('/api/records', methods=['GET'])
def list_records():
    db = get_db()
    rows = db.execute('''
        SELECT pr.*, e.name AS exercise_name, e.muscle_group
        FROM personal_records pr
        JOIN exercises e ON pr.exercise_id = e.id
        ORDER BY e.muscle_group, e.name
    ''').fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ── Goals ─────────────────────────────────────────────────────

@app.route('/api/goals', methods=['GET'])
def list_goals():
    db = get_db()
    rows = db.execute(
        'SELECT * FROM goals WHERE active = 1 ORDER BY start_date DESC'
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/goals', methods=['POST'])
def create_goal():
    data = request.json
    required = ('type', 'target', 'start_date', 'end_date')
    if not all(k in data for k in required):
        return jsonify({'error': 'type, target, start_date, end_date required'}), 400
    db = get_db()
    cur = db.execute(
        'INSERT INTO goals (type, target, start_date, end_date) VALUES (?, ?, ?, ?)',
        (data['type'], data['target'], data['start_date'], data['end_date'])
    )
    db.commit()
    row = db.execute('SELECT * FROM goals WHERE id = ?', (cur.lastrowid,)).fetchone()
    db.close()
    return jsonify(dict(row)), 201


@app.route('/api/goals/<int:goal_id>', methods=['DELETE'])
def delete_goal(goal_id):
    db = get_db()
    db.execute('UPDATE goals SET active = 0 WHERE id = ?', (goal_id,))
    db.commit()
    db.close()
    return jsonify({'deleted': goal_id})


# ── Summary stats ────────────────────────────────────────────

@app.route('/api/stats/summary', methods=['GET'])
def stats_summary():
    db = get_db()
    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())

    total_workouts  = db.execute('SELECT COUNT(*) FROM workouts').fetchone()[0]
    total_records   = db.execute('SELECT COUNT(*) FROM personal_records').fetchone()[0]
    total_exercises = db.execute('SELECT COUNT(*) FROM exercises').fetchone()[0]
    this_week       = db.execute(
        'SELECT COUNT(*) FROM workouts WHERE date >= ?', (str(week_start),)
    ).fetchone()[0]
    last_workout    = db.execute(
        'SELECT date FROM workouts ORDER BY date DESC LIMIT 1'
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
def get_alerts():
    db = get_db()
    today = datetime.now().date()
    goals = db.execute(
        "SELECT * FROM goals WHERE active = 1 AND end_date >= ?", (str(today),)
    ).fetchall()
    alerts = []

    for goal in goals:
        if goal['type'] == 'frequency':
            start = datetime.strptime(goal['start_date'], '%Y-%m-%d').date()
            end   = datetime.strptime(goal['end_date'],   '%Y-%m-%d').date()
            days_elapsed = (today - start).days + 1
            count = db.execute(
                "SELECT COUNT(*) AS cnt FROM workouts WHERE date >= ? AND date <= ?",
                (goal['start_date'], str(today))
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
def stats_muscle_groups():
    db = get_db()
    rows = db.execute('''
        SELECT e.muscle_group, COUNT(ws.id) AS total_sets
        FROM workout_sets ws
        JOIN exercises e ON ws.exercise_id = e.id
        GROUP BY e.muscle_group
    ''').fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/stats/weekly_frequency', methods=['GET'])
def stats_weekly_frequency():
    db = get_db()
    today = datetime.now().date()
    weeks = []
    for i in range(7, -1, -1):
        week_start = today - timedelta(weeks=i, days=today.weekday())
        week_end   = week_start + timedelta(days=6)
        count = db.execute(
            "SELECT COUNT(*) AS cnt FROM workouts WHERE date >= ? AND date <= ?",
            (str(week_start), str(week_end))
        ).fetchone()['cnt']
        weeks.append({'week': str(week_start), 'count': count})
    db.close()
    return jsonify(weeks)


@app.route('/api/stats/strength/<int:exercise_id>', methods=['GET'])
def stats_strength(exercise_id):
    db = get_db()
    rows = db.execute('''
        SELECT w.date, MAX(ws.weight) AS max_weight
        FROM workout_sets ws
        JOIN workouts w ON ws.workout_id = w.id
        WHERE ws.exercise_id = ?
        GROUP BY w.date
        ORDER BY w.date
    ''', (exercise_id,)).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ── Templates ─────────────────────────────────────────────────

@app.route('/api/templates', methods=['GET'])
def list_templates():
    db = get_db()
    rows = db.execute('SELECT * FROM templates ORDER BY name').fetchall()
    db.close()
    return jsonify([{**dict(r), 'exercises': json.loads(r['exercises'])} for r in rows])


@app.route('/api/templates', methods=['POST'])
def create_template():
    data = request.json
    if not data.get('name') or not data.get('exercises'):
        return jsonify({'error': 'name and exercises required'}), 400
    db = get_db()
    try:
        cur = db.execute(
            'INSERT INTO templates (name, description, exercises) VALUES (?, ?, ?)',
            (data['name'], data.get('description', ''), json.dumps(data['exercises']))
        )
        db.commit()
        row = db.execute('SELECT * FROM templates WHERE id = ?', (cur.lastrowid,)).fetchone()
        db.close()
        return jsonify({**dict(row), 'exercises': json.loads(row['exercises'])}), 201
    except Exception as e:
        db.close()
        return jsonify({'error': str(e)}), 400


@app.route('/api/templates/<int:template_id>', methods=['DELETE'])
def delete_template(template_id):
    db = get_db()
    db.execute('DELETE FROM templates WHERE id = ?', (template_id,))
    db.commit()
    db.close()
    return jsonify({'deleted': template_id})


# ── CSV Export ────────────────────────────────────────────────

@app.route('/api/export/csv', methods=['GET'])
def export_csv():
    db = get_db()
    rows = db.execute('''
        SELECT w.date, w.notes, e.name AS exercise, e.muscle_group,
               ws.sets, ws.reps, ws.weight
        FROM workout_sets ws
        JOIN workouts w ON ws.workout_id = w.id
        JOIN exercises e ON ws.exercise_id = e.id
        ORDER BY w.date, e.name
    ''').fetchall()
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
