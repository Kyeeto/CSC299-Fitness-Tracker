"""
Unit tests for the Fitness Tracker Flask API.

Each test class gets a fresh, empty SQLite database via setUp so tests are
fully isolated from one another.  The real DB file is never touched.
"""

import atexit
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Path / DB setup — must happen before app is imported
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server'))

import database  # noqa: E402

_db_fd, _db_path = tempfile.mkstemp(suffix='.test.db')


def _cleanup():
    try:
        os.close(_db_fd)
    except OSError:
        pass
    try:
        os.unlink(_db_path)
    except OSError:
        pass


atexit.register(_cleanup)

# Redirect DB to temp file before app.py calls init_db() on import
database.DB_PATH = _db_path

import app as _flask_module  # noqa: E402 — intentionally after DB patch

_app = _flask_module.app
_app.config['TESTING'] = True
_client = _app.test_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _json(response):
    return json.loads(response.data)


def _post(url, body):
    return _client.post(url, json=body, content_type='application/json')


def _delete(url):
    return _client.delete(url)


# ---------------------------------------------------------------------------
# Base class — clears all rows before every test
# ---------------------------------------------------------------------------

class BaseTest(unittest.TestCase):

    def setUp(self):
        conn = database.get_db()
        conn.executescript('''
            DELETE FROM workout_sets;
            DELETE FROM workouts;
            DELETE FROM personal_records;
            DELETE FROM goals;
            DELETE FROM templates;
            DELETE FROM exercises;
        ''')
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# Exercises
# ---------------------------------------------------------------------------

class TestExercises(BaseTest):

    def _add(self, name='Bench Press', muscle_group='Chest'):
        return _post('/api/exercises', {'name': name, 'muscle_group': muscle_group})

    # -- GET ----------------------------------------------------------------

    def test_list_empty(self):
        r = _client.get('/api/exercises')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_json(r), [])

    def test_list_after_create(self):
        self._add()
        self.assertEqual(len(_json(_client.get('/api/exercises'))), 1)

    def test_list_ordered_by_muscle_group_then_name(self):
        _post('/api/exercises', {'name': 'Squat',           'muscle_group': 'Legs'})
        _post('/api/exercises', {'name': 'Bench Press',     'muscle_group': 'Chest'})
        _post('/api/exercises', {'name': 'Overhead Press',  'muscle_group': 'Shoulders'})
        groups = [e['muscle_group'] for e in _json(_client.get('/api/exercises'))]
        self.assertEqual(groups, sorted(groups))

    # -- POST ---------------------------------------------------------------

    def test_create_returns_201(self):
        self.assertEqual(self._add().status_code, 201)

    def test_create_returns_correct_fields(self):
        data = _json(self._add())
        self.assertEqual(data['name'], 'Bench Press')
        self.assertEqual(data['muscle_group'], 'Chest')
        self.assertIn('id', data)

    def test_create_duplicate_returns_400(self):
        self._add()
        self.assertEqual(self._add().status_code, 400)

    def test_create_missing_name_returns_400(self):
        self.assertEqual(_post('/api/exercises', {'muscle_group': 'Chest'}).status_code, 400)

    def test_create_missing_muscle_group_returns_400(self):
        self.assertEqual(_post('/api/exercises', {'name': 'Squat'}).status_code, 400)

    def test_create_strips_whitespace(self):
        data = _json(_post('/api/exercises', {'name': '  Pull Up  ', 'muscle_group': ' Back '}))
        self.assertEqual(data['name'], 'Pull Up')
        self.assertEqual(data['muscle_group'], 'Back')


# ---------------------------------------------------------------------------
# Workouts
# ---------------------------------------------------------------------------

class TestWorkouts(BaseTest):

    def setUp(self):
        super().setUp()
        self.ex_id = _json(_post('/api/exercises', {'name': 'Bench Press', 'muscle_group': 'Chest'}))['id']

    def _log(self, sets=None, date_str=None, notes=''):
        return _post('/api/workouts', {
            'date':  date_str or str(date.today()),
            'notes': notes,
            'sets':  sets or [{'exercise_id': self.ex_id, 'sets': 3, 'reps': 8, 'weight': 135}],
        })

    # -- GET ----------------------------------------------------------------

    def test_list_empty(self):
        self.assertEqual(_json(_client.get('/api/workouts')), [])

    def test_list_includes_sets(self):
        self._log()
        w = _json(_client.get('/api/workouts'))[0]
        self.assertEqual(len(w['sets']), 1)

    def test_list_sets_include_exercise_name(self):
        self._log()
        s = _json(_client.get('/api/workouts'))[0]['sets'][0]
        self.assertEqual(s['exercise_name'], 'Bench Press')
        self.assertEqual(s['muscle_group'], 'Chest')

    def test_list_ordered_newest_first(self):
        self._log(date_str='2026-01-01')
        self._log(date_str='2026-06-01')
        dates = [w['date'] for w in _json(_client.get('/api/workouts'))]
        self.assertEqual(dates, sorted(dates, reverse=True))

    # -- POST ---------------------------------------------------------------

    def test_create_returns_201(self):
        self.assertEqual(self._log().status_code, 201)

    def test_create_persists_notes(self):
        data = _json(self._log(notes='Felt strong today'))
        self.assertEqual(data['notes'], 'Felt strong today')

    def test_create_missing_date_returns_400(self):
        r = _post('/api/workouts', {'sets': []})
        self.assertEqual(r.status_code, 400)

    def test_create_multiple_sets(self):
        ex2 = _json(_post('/api/exercises', {'name': 'Squat', 'muscle_group': 'Legs'}))['id']
        self._log(sets=[
            {'exercise_id': self.ex_id, 'sets': 3, 'reps': 8,  'weight': 135},
            {'exercise_id': ex2,        'sets': 4, 'reps': 5,  'weight': 225},
        ])
        w = _json(_client.get('/api/workouts'))[0]
        self.assertEqual(len(w['sets']), 2)

    # -- DELETE -------------------------------------------------------------

    def test_delete_removes_workout(self):
        w_id = _json(self._log())['id']
        _delete(f'/api/workouts/{w_id}')
        self.assertEqual(_json(_client.get('/api/workouts')), [])

    def test_delete_cascades_to_sets(self):
        w_id = _json(self._log())['id']
        _delete(f'/api/workouts/{w_id}')
        conn = database.get_db()
        count = conn.execute('SELECT COUNT(*) FROM workout_sets').fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_delete_returns_deleted_id(self):
        w_id = _json(self._log())['id']
        data = _json(_delete(f'/api/workouts/{w_id}'))
        self.assertEqual(data['deleted'], w_id)


# ---------------------------------------------------------------------------
# Personal Records
# ---------------------------------------------------------------------------

class TestPersonalRecords(BaseTest):

    def setUp(self):
        super().setUp()
        self.ex_id = _json(_post('/api/exercises', {'name': 'Deadlift', 'muscle_group': 'Back'}))['id']

    def _log(self, weight, date_str='2026-01-01'):
        return _post('/api/workouts', {
            'date':  date_str,
            'notes': '',
            'sets':  [{'exercise_id': self.ex_id, 'sets': 1, 'reps': 1, 'weight': weight}],
        })

    # -- List ---------------------------------------------------------------

    def test_list_empty(self):
        self.assertEqual(_json(_client.get('/api/records')), [])

    def test_list_includes_exercise_metadata(self):
        self._log(200)
        rec = _json(_client.get('/api/records'))[0]
        self.assertEqual(rec['exercise_name'], 'Deadlift')
        self.assertEqual(rec['muscle_group'], 'Back')

    # -- PR detection -------------------------------------------------------

    def test_first_workout_creates_pr(self):
        data = _json(self._log(200))
        self.assertEqual(len(data['new_prs']), 1)
        self.assertEqual(data['new_prs'][0]['weight'], 200)
        self.assertEqual(data['new_prs'][0]['exercise'], 'Deadlift')

    def test_heavier_weight_triggers_new_pr(self):
        self._log(200)
        data = _json(self._log(225, date_str='2026-02-01'))
        self.assertEqual(len(data['new_prs']), 1)
        self.assertEqual(data['new_prs'][0]['weight'], 225)

    def test_lighter_weight_no_pr(self):
        self._log(225)
        self.assertEqual(_json(self._log(200, date_str='2026-02-01'))['new_prs'], [])

    def test_equal_weight_no_pr(self):
        self._log(225)
        self.assertEqual(_json(self._log(225, date_str='2026-02-01'))['new_prs'], [])

    def test_pr_record_stores_highest_weight(self):
        self._log(200)
        self._log(250, date_str='2026-02-01')
        self._log(220, date_str='2026-03-01')
        records = _json(_client.get('/api/records'))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['weight'], 250)

    def test_pr_record_stores_date_achieved(self):
        self._log(200, date_str='2026-01-01')
        self._log(250, date_str='2026-02-01')
        rec = _json(_client.get('/api/records'))[0]
        self.assertEqual(rec['date_achieved'], '2026-02-01')

    def test_separate_prs_per_exercise(self):
        ex2 = _json(_post('/api/exercises', {'name': 'Squat', 'muscle_group': 'Legs'}))['id']
        self._log(300)
        _post('/api/workouts', {
            'date': '2026-01-01', 'notes': '',
            'sets': [{'exercise_id': ex2, 'sets': 1, 'reps': 1, 'weight': 225}],
        })
        self.assertEqual(len(_json(_client.get('/api/records'))), 2)


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------

class TestGoals(BaseTest):

    def _goal(self, target=4, start='2026-01-01', end='2026-12-31'):
        return _post('/api/goals', {
            'type': 'frequency', 'target': target,
            'start_date': start, 'end_date': end,
        })

    # -- GET ----------------------------------------------------------------

    def test_list_empty(self):
        self.assertEqual(_json(_client.get('/api/goals')), [])

    def test_list_after_create(self):
        self._goal()
        self.assertEqual(len(_json(_client.get('/api/goals'))), 1)

    def test_list_multiple_goals(self):
        self._goal(target=3)
        self._goal(target=5, start='2026-06-01')
        self.assertEqual(len(_json(_client.get('/api/goals'))), 2)

    # -- POST ---------------------------------------------------------------

    def test_create_returns_201(self):
        self.assertEqual(self._goal().status_code, 201)

    def test_create_fields(self):
        data = _json(self._goal(target=5))
        self.assertEqual(data['type'],   'frequency')
        self.assertEqual(data['target'], 5)
        self.assertEqual(data['active'], 1)

    def test_create_missing_fields_returns_400(self):
        self.assertEqual(_post('/api/goals', {'type': 'frequency'}).status_code, 400)

    # -- DELETE -------------------------------------------------------------

    def test_delete_deactivates_goal(self):
        g_id = _json(self._goal())['id']
        _delete(f'/api/goals/{g_id}')
        self.assertEqual(_json(_client.get('/api/goals')), [])

    def test_delete_does_not_remove_row(self):
        g_id = _json(self._goal())['id']
        _delete(f'/api/goals/{g_id}')
        conn = database.get_db()
        row = conn.execute('SELECT active FROM goals WHERE id = ?', (g_id,)).fetchone()
        conn.close()
        self.assertEqual(row['active'], 0)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class TestAlerts(BaseTest):

    def setUp(self):
        super().setUp()
        self.ex_id = _json(_post('/api/exercises', {'name': 'Run', 'muscle_group': 'Cardio'}))['id']

    def _goal(self, target, start, end):
        _post('/api/goals', {
            'type': 'frequency', 'target': target,
            'start_date': start, 'end_date': end,
        })

    def _workout(self, date_str):
        _post('/api/workouts', {
            'date':  date_str,
            'notes': '',
            'sets':  [{'exercise_id': self.ex_id, 'sets': 1, 'reps': 1, 'weight': 0}],
        })

    def test_no_goals_no_alerts(self):
        self.assertEqual(_json(_client.get('/api/alerts')), [])

    def test_expired_goal_not_alerted(self):
        self._goal(target=7, start='2020-01-01', end='2020-01-31')
        self.assertEqual(_json(_client.get('/api/alerts')), [])

    def test_alert_when_zero_workouts_and_high_target(self):
        today = date.today()
        start = str(today - timedelta(days=6))
        end   = str(today + timedelta(days=30))
        # 7 workouts/week goal, 7 days elapsed, 0 done → behind
        self._goal(target=7, start=start, end=end)
        alerts = _json(_client.get('/api/alerts'))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['type'], 'frequency_warning')
        self.assertIn('goal_id', alerts[0])
        self.assertIn('message', alerts[0])

    def test_no_alert_when_ahead_of_pace(self):
        today = date.today()
        # Goal starts today: only 1 day elapsed, target=1/week → expected ≈ 0.14
        # Log 1 workout → definitely not behind
        self._goal(target=1, start=str(today), end=str(today + timedelta(days=30)))
        self._workout(str(today))
        self.assertEqual(_json(_client.get('/api/alerts')), [])

    def test_alert_message_contains_useful_info(self):
        today = date.today()
        start = str(today - timedelta(days=6))
        self._goal(target=7, start=start, end=str(today + timedelta(days=30)))
        msg = _json(_client.get('/api/alerts'))[0]['message']
        # Should mention the target and count
        self.assertIn('7', msg)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats(BaseTest):

    def setUp(self):
        super().setUp()
        self.chest_id = _json(_post('/api/exercises', {'name': 'Bench Press', 'muscle_group': 'Chest'}))['id']
        self.legs_id  = _json(_post('/api/exercises', {'name': 'Squat',       'muscle_group': 'Legs'}))['id']

    def _log(self, date_str, sets):
        _post('/api/workouts', {'date': date_str, 'notes': '', 'sets': sets})

    # -- Muscle groups ------------------------------------------------------

    def test_muscle_groups_empty(self):
        self.assertEqual(_json(_client.get('/api/stats/muscle_groups')), [])

    def test_muscle_groups_counts_sets(self):
        self._log('2026-01-01', [
            {'exercise_id': self.chest_id, 'sets': 3, 'reps': 8, 'weight': 135},
            {'exercise_id': self.legs_id,  'sets': 4, 'reps': 5, 'weight': 225},
        ])
        data   = _json(_client.get('/api/stats/muscle_groups'))
        groups = {d['muscle_group']: d['total_sets'] for d in data}
        # Each exercise appears once as a row in workout_sets
        self.assertEqual(groups['Chest'], 1)
        self.assertEqual(groups['Legs'],  1)

    def test_muscle_groups_accumulates_across_workouts(self):
        for d in ['2026-01-01', '2026-01-08']:
            self._log(d, [{'exercise_id': self.chest_id, 'sets': 3, 'reps': 8, 'weight': 135}])
        data   = _json(_client.get('/api/stats/muscle_groups'))
        groups = {d['muscle_group']: d['total_sets'] for d in data}
        self.assertEqual(groups['Chest'], 2)

    # -- Weekly frequency ---------------------------------------------------

    def test_weekly_frequency_returns_8_entries(self):
        self.assertEqual(len(_json(_client.get('/api/stats/weekly_frequency'))), 8)

    def test_weekly_frequency_counts_this_week(self):
        today = str(date.today())
        self._log(today, [{'exercise_id': self.chest_id, 'sets': 1, 'reps': 1, 'weight': 100}])
        data = _json(_client.get('/api/stats/weekly_frequency'))
        # Last entry is the current week
        self.assertGreaterEqual(data[-1]['count'], 1)

    def test_weekly_frequency_has_week_field(self):
        data = _json(_client.get('/api/stats/weekly_frequency'))
        for entry in data:
            self.assertIn('week',  entry)
            self.assertIn('count', entry)

    # -- Strength trend -----------------------------------------------------

    def test_strength_empty(self):
        self.assertEqual(_json(_client.get(f'/api/stats/strength/{self.chest_id}')), [])

    def test_strength_returns_max_per_session(self):
        self._log('2026-01-01', [
            {'exercise_id': self.chest_id, 'sets': 1, 'reps': 1, 'weight': 135},
            {'exercise_id': self.chest_id, 'sets': 1, 'reps': 1, 'weight': 145},
        ])
        data = _json(_client.get(f'/api/stats/strength/{self.chest_id}'))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['max_weight'], 145)

    def test_strength_ordered_by_date(self):
        for d, w in [('2026-01-01', 135), ('2026-02-01', 145), ('2026-03-01', 155)]:
            self._log(d, [{'exercise_id': self.chest_id, 'sets': 1, 'reps': 1, 'weight': w}])
        data    = _json(_client.get(f'/api/stats/strength/{self.chest_id}'))
        weights = [e['max_weight'] for e in data]
        self.assertEqual(weights, [135, 145, 155])

    def test_strength_only_returns_requested_exercise(self):
        self._log('2026-01-01', [
            {'exercise_id': self.chest_id, 'sets': 1, 'reps': 1, 'weight': 135},
            {'exercise_id': self.legs_id,  'sets': 1, 'reps': 1, 'weight': 225},
        ])
        data = _json(_client.get(f'/api/stats/strength/{self.chest_id}'))
        self.assertEqual(len(data), 1)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class TestTemplates(BaseTest):

    def setUp(self):
        super().setUp()
        self.ex_id = _json(_post('/api/exercises', {'name': 'Push Up', 'muscle_group': 'Chest'}))['id']

    def _tmpl(self, name='Push Day', description=''):
        return _post('/api/templates', {
            'name':        name,
            'description': description,
            'exercises':   [{'exercise_id': self.ex_id, 'sets': 3, 'reps': 15, 'weight': 0}],
        })

    # -- GET ----------------------------------------------------------------

    def test_list_empty(self):
        self.assertEqual(_json(_client.get('/api/templates')), [])

    def test_list_after_create(self):
        self._tmpl()
        self.assertEqual(len(_json(_client.get('/api/templates'))), 1)

    # -- POST ---------------------------------------------------------------

    def test_create_returns_201(self):
        self.assertEqual(self._tmpl().status_code, 201)

    def test_create_fields(self):
        data = _json(self._tmpl(description='Classic'))
        self.assertEqual(data['name'], 'Push Day')
        self.assertEqual(data['description'], 'Classic')
        self.assertIsInstance(data['exercises'], list)

    def test_create_exercises_deserialized(self):
        data = _json(self._tmpl())
        ex = data['exercises'][0]
        self.assertEqual(ex['exercise_id'], self.ex_id)
        self.assertEqual(ex['sets'],  3)
        self.assertEqual(ex['reps'],  15)
        self.assertEqual(ex['weight'], 0)

    def test_create_duplicate_name_returns_400(self):
        self._tmpl()
        self.assertEqual(self._tmpl().status_code, 400)

    def test_create_missing_name_returns_400(self):
        r = _post('/api/templates', {'exercises': []})
        self.assertEqual(r.status_code, 400)

    def test_create_missing_exercises_returns_400(self):
        r = _post('/api/templates', {'name': 'Test'})
        self.assertEqual(r.status_code, 400)

    # -- DELETE -------------------------------------------------------------

    def test_delete_removes_template(self):
        t_id = _json(self._tmpl())['id']
        _delete(f'/api/templates/{t_id}')
        self.assertEqual(_json(_client.get('/api/templates')), [])

    def test_delete_returns_deleted_id(self):
        t_id = _json(self._tmpl())['id']
        data = _json(_delete(f'/api/templates/{t_id}'))
        self.assertEqual(data['deleted'], t_id)


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

class TestCSVExport(BaseTest):

    def test_export_returns_200(self):
        self.assertEqual(_client.get('/api/export/csv').status_code, 200)

    def test_export_content_type_is_csv(self):
        r = _client.get('/api/export/csv')
        self.assertIn('text/csv', r.content_type)

    def test_export_empty_has_header_only(self):
        r = _client.get('/api/export/csv')
        lines = r.data.decode().strip().splitlines()
        self.assertEqual(len(lines), 1)

    def test_export_header_columns(self):
        r = _client.get('/api/export/csv')
        header = r.data.decode().strip().splitlines()[0]
        for col in ('Date', 'Notes', 'Exercise', 'Muscle Group', 'Sets', 'Reps', 'Weight'):
            self.assertIn(col, header)

    def test_export_includes_workout_data(self):
        ex_id = _json(_post('/api/exercises', {'name': 'Deadlift', 'muscle_group': 'Back'}))['id']
        _post('/api/workouts', {
            'date': '2026-01-01', 'notes': 'Test session',
            'sets': [{'exercise_id': ex_id, 'sets': 3, 'reps': 5, 'weight': 315}],
        })
        lines = _client.get('/api/export/csv').data.decode().strip().splitlines()
        self.assertEqual(len(lines), 2)
        row = lines[1]
        self.assertIn('Deadlift', row)
        self.assertIn('315', row)
        self.assertIn('2026-01-01', row)

    def test_export_multiple_rows(self):
        ex_id = _json(_post('/api/exercises', {'name': 'Squat', 'muscle_group': 'Legs'}))['id']
        for d in ('2026-01-01', '2026-01-08'):
            _post('/api/workouts', {
                'date': d, 'notes': '',
                'sets': [{'exercise_id': ex_id, 'sets': 1, 'reps': 1, 'weight': 200}],
            })
        lines = _client.get('/api/export/csv').data.decode().strip().splitlines()
        self.assertEqual(len(lines), 3)  # header + 2 rows


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

class TestSummaryStats(BaseTest):

    def _add_exercise(self):
        return _json(_post('/api/exercises', {'name': 'Squat', 'muscle_group': 'Legs'}))['id']

    def _log(self, ex_id, date_str=None, weight=100):
        _post('/api/workouts', {
            'date': date_str or str(date.today()), 'notes': '',
            'sets': [{'exercise_id': ex_id, 'sets': 1, 'reps': 1, 'weight': weight}],
        })

    def test_summary_returns_200(self):
        self.assertEqual(_client.get('/api/stats/summary').status_code, 200)

    def test_summary_has_all_fields(self):
        data = _json(_client.get('/api/stats/summary'))
        for field in ('total_workouts', 'total_records', 'total_exercises', 'this_week', 'last_workout'):
            self.assertIn(field, data)

    def test_summary_empty_db(self):
        data = _json(_client.get('/api/stats/summary'))
        self.assertEqual(data['total_workouts'],  0)
        self.assertEqual(data['total_records'],   0)
        self.assertEqual(data['total_exercises'], 0)
        self.assertEqual(data['this_week'],       0)
        self.assertIsNone(data['last_workout'])

    def test_summary_counts_workout(self):
        ex_id = self._add_exercise()
        self._log(ex_id)
        data = _json(_client.get('/api/stats/summary'))
        self.assertEqual(data['total_workouts'], 1)
        self.assertEqual(data['this_week'],      1)

    def test_summary_counts_records(self):
        ex_id = self._add_exercise()
        self._log(ex_id, weight=200)
        self.assertEqual(_json(_client.get('/api/stats/summary'))['total_records'], 1)

    def test_summary_counts_exercises(self):
        self._add_exercise()
        _post('/api/exercises', {'name': 'Push Up', 'muscle_group': 'Chest'})
        self.assertEqual(_json(_client.get('/api/stats/summary'))['total_exercises'], 2)

    def test_summary_last_workout_date(self):
        ex_id = self._add_exercise()
        self._log(ex_id, date_str='2026-05-01')
        self._log(ex_id, date_str='2026-06-01')
        self.assertEqual(_json(_client.get('/api/stats/summary'))['last_workout'], '2026-06-01')

    def test_this_week_excludes_old_workouts(self):
        ex_id = self._add_exercise()
        self._log(ex_id, date_str='2020-01-01')
        data = _json(_client.get('/api/stats/summary'))
        self.assertEqual(data['total_workouts'], 1)
        self.assertEqual(data['this_week'],      0)


# ---------------------------------------------------------------------------
# Index route
# ---------------------------------------------------------------------------

class TestIndexRoute(BaseTest):

    def test_root_returns_html(self):
        r = _client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Fitness Tracker', r.data)


# ---------------------------------------------------------------------------

if __name__ == '__main__':
    unittest.main(verbosity=2)
