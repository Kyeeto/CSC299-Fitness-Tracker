#!/usr/bin/env python3
"""Fitness Tracker CLI — talks to the Flask REST API on localhost:5000"""
import argparse
import sys
from datetime import date

try:
    import requests
except ImportError:
    print("Run: pip install requests")
    sys.exit(1)

BASE = 'http://localhost:5000/api'


def _get(path):
    try:
        return requests.get(f'{BASE}{path}').json()
    except requests.ConnectionError:
        print("Cannot connect to server. Is it running? (python server/app.py)")
        sys.exit(1)


def _post(path, body):
    try:
        r = requests.post(f'{BASE}{path}', json=body)
        return r.status_code, r.json()
    except requests.ConnectionError:
        print("Cannot connect to server. Is it running? (python server/app.py)")
        sys.exit(1)


def _delete(path):
    try:
        return requests.delete(f'{BASE}{path}').json()
    except requests.ConnectionError:
        print("Cannot connect to server. Is it running? (python server/app.py)")
        sys.exit(1)


# ── exercise ───────────────────────────────────────────────────

def cmd_exercise_list(_args):
    exercises = _get('/exercises')
    if not exercises:
        print("No exercises yet. Add one with: client.py exercise add <name> <muscle_group>")
        return
    by_group = {}
    for e in exercises:
        by_group.setdefault(e['muscle_group'], []).append(e)
    for group in sorted(by_group):
        print(f"\n{group}:")
        for e in by_group[group]:
            print(f"  [{e['id']:>3}] {e['name']}")


def cmd_exercise_add(args):
    code, data = _post('/exercises', {'name': args.name, 'muscle_group': args.muscle_group})
    if code == 201:
        print(f"Added: [{data['id']}] {data['name']} ({data['muscle_group']})")
    else:
        print(f"Error: {data.get('error')}")


# ── log ────────────────────────────────────────────────────────

def cmd_log(args):
    today = str(date.today())
    sets  = []

    if args.from_template:
        tmpls = _get('/templates')
        tmpl  = next((t for t in tmpls if t['name'].lower() == args.from_template.lower()), None)
        if not tmpl:
            names = [t['name'] for t in tmpls]
            print(f"Template '{args.from_template}' not found. Available: {names or 'none'}")
            return
        sets = tmpl['exercises']
        print(f"Loaded template: {tmpl['name']}")
    else:
        if args.exercise is None:
            print("Provide --exercise (name or ID) or --from-template")
            return
        if args.weight is None:
            print("--weight is required when not using --from-template")
            return
        exs = _get('/exercises')
        ex  = None
        try:
            eid = int(args.exercise)
            ex  = next((e for e in exs if e['id'] == eid), None)
        except ValueError:
            ex  = next((e for e in exs if e['name'].lower() == args.exercise.lower()), None)
        if not ex:
            print(f"Exercise '{args.exercise}' not found. Run 'client.py exercise list' to see options.")
            return
        sets = [{'exercise_id': ex['id'], 'sets': args.sets, 'reps': args.reps, 'weight': args.weight}]

    code, data = _post('/workouts', {
        'date':  args.date or today,
        'notes': args.notes or '',
        'sets':  sets,
    })

    if code == 201:
        print(f"Workout logged for {data['date']}")
        for pr in data.get('new_prs', []):
            print(f"  🏆 New PR! {pr['exercise']}: {pr['weight']} lbs")
    else:
        print(f"Error: {data}")


# ── history ────────────────────────────────────────────────────

def cmd_history(args):
    workouts = _get('/workouts')
    if not workouts:
        print("No workouts logged yet.")
        return
    for w in workouts[:args.limit]:
        header = w['date']
        if w.get('notes'):
            header += f" — {w['notes']}"
        print(f"\n{header}")
        for s in w['sets']:
            print(f"  {s['exercise_name']:<28} {s['sets']}x{s['reps']} @ {s['weight']} lbs")


# ── records ────────────────────────────────────────────────────

def cmd_records(_args):
    records = _get('/records')
    if not records:
        print("No personal records yet.")
        return
    print("\nPersonal Records:")
    print(f"  {'Exercise':<28} {'Weight':>10}  Date")
    print(f"  {'-'*28} {'-'*10}  {'-'*10}")
    for r in records:
        print(f"  {r['exercise_name']:<28} {r['weight']:>9} lbs  {r['date_achieved']}")


# ── alerts ─────────────────────────────────────────────────────

def cmd_alerts(_args):
    alerts = _get('/alerts')
    if not alerts:
        print("No alerts — you're on track!")
    for a in alerts:
        print(f"⚠️  {a['message']}")


# ── goal ───────────────────────────────────────────────────────

def cmd_goal(args):
    code, data = _post('/goals', {
        'type':       'frequency',
        'target':     args.target,
        'start_date': args.start,
        'end_date':   args.end,
    })
    if code == 201:
        print(f"Goal set: {args.target} workouts/week from {args.start} to {args.end}")
    else:
        print(f"Error: {data.get('error')}")


# ── CLI wiring ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog='client.py',
        description='Fitness Tracker CLI',
    )
    sub = parser.add_subparsers(dest='command', metavar='<command>')

    # exercise
    p_ex  = sub.add_parser('exercise', help='Manage exercises')
    ex_sub = p_ex.add_subparsers(dest='action', metavar='<action>')
    ex_sub.add_parser('list', help='List all exercises')
    p_add = ex_sub.add_parser('add', help='Add a new exercise')
    p_add.add_argument('name')
    p_add.add_argument('muscle_group', metavar='muscle-group',
                       help='e.g. Chest, Back, Legs, Shoulders, Biceps, Triceps, Core, Cardio')

    # log
    p_log = sub.add_parser('log', help='Log a workout')
    p_log.add_argument('-e', '--exercise',      help='Exercise name or ID')
    p_log.add_argument('-s', '--sets',   type=int,   default=3)
    p_log.add_argument('-r', '--reps',   type=int,   default=10)
    p_log.add_argument('-w', '--weight', type=float, default=None, help='Weight in lbs')
    p_log.add_argument('-d', '--date',   default=None, help='YYYY-MM-DD (default: today)')
    p_log.add_argument('-n', '--notes',  default='')
    p_log.add_argument('-t', '--from-template', dest='from_template',
                       help='Load exercises from a saved template by name')

    # history
    p_hist = sub.add_parser('history', help='View recent workouts')
    p_hist.add_argument('-n', '--limit', type=int, default=5, help='How many to show (default 5)')

    # records
    sub.add_parser('records', help='Show personal records')

    # alerts
    sub.add_parser('alerts', help='Check goal alerts')

    # goal
    p_goal = sub.add_parser('goal', help='Set a weekly frequency goal')
    p_goal.add_argument('target', type=int, help='Workouts per week')
    p_goal.add_argument('start',  help='Start date YYYY-MM-DD')
    p_goal.add_argument('end',    help='End date YYYY-MM-DD')

    args = parser.parse_args()

    dispatch = {
        ('exercise', 'list'): cmd_exercise_list,
        ('exercise', 'add'):  cmd_exercise_add,
        ('log',      None):   cmd_log,
        ('history',  None):   cmd_history,
        ('records',  None):   cmd_records,
        ('alerts',   None):   cmd_alerts,
        ('goal',     None):   cmd_goal,
    }

    key = (args.command, getattr(args, 'action', None))
    fn  = dispatch.get(key)
    if fn:
        fn(args)
    elif args.command == 'exercise':
        p_ex.print_help()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
