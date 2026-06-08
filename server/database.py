import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fitness.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    TEXT DEFAULT (date('now'))
        );

        CREATE TABLE IF NOT EXISTS exercises (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL UNIQUE,
            muscle_group TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS workouts (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            date    TEXT NOT NULL,
            notes   TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS workout_sets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            workout_id  INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
            exercise_id INTEGER NOT NULL REFERENCES exercises(id),
            sets        INTEGER NOT NULL,
            reps        INTEGER NOT NULL,
            weight      REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS personal_records (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER REFERENCES users(id),
            exercise_id   INTEGER NOT NULL REFERENCES exercises(id),
            weight        REAL    NOT NULL,
            date_achieved TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS goals (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER REFERENCES users(id),
            type       TEXT    NOT NULL,
            target     INTEGER NOT NULL,
            start_date TEXT    NOT NULL,
            end_date   TEXT    NOT NULL,
            active     INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER REFERENCES users(id),
            name        TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            exercises   TEXT NOT NULL
        );
    ''')
    conn.commit()
    _migrate(conn)
    _seed_exercises(conn)
    conn.close()


def _migrate(conn):
    """Add user_id to tables created before auth was added."""
    for table in ('workouts', 'goals', 'templates', 'personal_records'):
        try:
            conn.execute(
                f'ALTER TABLE {table} ADD COLUMN user_id INTEGER REFERENCES users(id)'
            )
        except Exception:
            pass
    conn.commit()


_DEFAULT_EXERCISES = [
    # Chest
    ('Bench Press',          'Chest'),
    ('Incline Bench Press',  'Chest'),
    ('Decline Bench Press',  'Chest'),
    ('Dumbbell Fly',         'Chest'),
    ('Cable Fly',            'Chest'),
    ('Push Up',              'Chest'),
    # Back
    ('Deadlift',             'Back'),
    ('Pull Up',              'Back'),
    ('Chin Up',              'Back'),
    ('Barbell Row',          'Back'),
    ('Dumbbell Row',         'Back'),
    ('Lat Pulldown',         'Back'),
    ('Seated Cable Row',     'Back'),
    ('T-Bar Row',            'Back'),
    # Shoulders
    ('Overhead Press',       'Shoulders'),
    ('Dumbbell Shoulder Press', 'Shoulders'),
    ('Lateral Raise',        'Shoulders'),
    ('Front Raise',          'Shoulders'),
    ('Arnold Press',         'Shoulders'),
    ('Face Pull',            'Shoulders'),
    ('Upright Row',          'Shoulders'),
    # Biceps
    ('Barbell Curl',         'Biceps'),
    ('Dumbbell Curl',        'Biceps'),
    ('Hammer Curl',          'Biceps'),
    ('Preacher Curl',        'Biceps'),
    ('Cable Curl',           'Biceps'),
    # Triceps
    ('Tricep Pushdown',      'Triceps'),
    ('Skull Crusher',        'Triceps'),
    ('Overhead Tricep Extension', 'Triceps'),
    ('Dips',                 'Triceps'),
    ('Close Grip Bench Press', 'Triceps'),
    # Legs
    ('Squat',                'Legs'),
    ('Front Squat',          'Legs'),
    ('Leg Press',            'Legs'),
    ('Romanian Deadlift',    'Legs'),
    ('Leg Curl',             'Legs'),
    ('Leg Extension',        'Legs'),
    ('Calf Raise',           'Legs'),
    ('Lunges',               'Legs'),
    ('Hip Thrust',           'Legs'),
    ('Sumo Deadlift',        'Legs'),
    # Core
    ('Plank',                'Core'),
    ('Crunches',             'Core'),
    ('Russian Twist',        'Core'),
    ('Leg Raise',            'Core'),
    ('Cable Crunch',         'Core'),
    ('Ab Wheel Rollout',     'Core'),
    # Cardio
    ('Running',              'Cardio'),
    ('Cycling',              'Cardio'),
    ('Jump Rope',            'Cardio'),
    ('Rowing Machine',       'Cardio'),
    ('Stair Climber',        'Cardio'),
    # Full Body
    ('Burpees',              'Full Body'),
    ('Kettlebell Swing',     'Full Body'),
    ('Clean and Jerk',       'Full Body'),
    ('Snatch',               'Full Body'),
    ('Thruster',             'Full Body'),
]


def _seed_exercises(conn):
    conn.executemany(
        'INSERT OR IGNORE INTO exercises (name, muscle_group) VALUES (?, ?)',
        _DEFAULT_EXERCISES,
    )
    conn.commit()
