const API = '/api';

let exercises = [];
let templates = [];
let muscleChart, freqChart, strengthChart;
let allWorkouts = [];
let pendingExerciseSelect = null;

// ── Auth ───────────────────────────────────────────────────────

async function checkAuth() {
  const r = await fetch(`${API}/auth/me`);
  if (r.status === 401) {
    showAuthOverlay(false);
    return false;
  }
  const user = await r.json();
  document.getElementById('usernameDisplay').textContent = user.username;
  document.getElementById('userInfo').classList.remove('hidden');
  document.getElementById('authOverlay').classList.add('hidden');
  return true;
}

function showAuthOverlay(isSignUp = false) {
  document.getElementById('authOverlay').classList.remove('hidden');
  setAuthMode(isSignUp);
}

let authMode = 'login';

function setAuthMode(signUp) {
  authMode = signUp ? 'signup' : 'login';
  document.getElementById('authTitle').textContent    = signUp ? 'Create account' : 'Welcome back';
  document.getElementById('authSubtitle').textContent = signUp ? 'Start tracking your fitness' : 'Sign in to your account';
  document.getElementById('authSubmit').textContent   = signUp ? 'Sign Up' : 'Sign In';
  document.getElementById('authToggle').textContent   = signUp ? 'Sign In' : 'Sign Up';
  document.querySelector('.auth-toggle').firstChild.textContent = signUp
    ? 'Already have an account? '
    : "Don't have an account? ";
  document.getElementById('authError').classList.add('hidden');
  document.getElementById('authPassword').value = '';
}

document.getElementById('authToggle').addEventListener('click', () => {
  setAuthMode(authMode === 'login');
});

document.getElementById('authForm').addEventListener('submit', async e => {
  e.preventDefault();
  const username = document.getElementById('authUsername').value.trim();
  const password = document.getElementById('authPassword').value;
  const errEl    = document.getElementById('authError');
  errEl.classList.add('hidden');

  const endpoint = authMode === 'signup' ? '/api/auth/signup' : '/api/auth/login';
  const r = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const data = await r.json();

  if (!r.ok) {
    errEl.textContent = data.error;
    errEl.classList.remove('hidden');
    return;
  }

  document.getElementById('usernameDisplay').textContent = data.username;
  document.getElementById('userInfo').classList.remove('hidden');
  document.getElementById('authOverlay').classList.add('hidden');
  loadApp();
});

document.getElementById('logoutBtn').addEventListener('click', async () => {
  await fetch('/api/auth/logout', { method: 'POST' });
  document.getElementById('userInfo').classList.add('hidden');
  showAuthOverlay(false);
  // Reset app state
  allWorkouts = [];
  exercises = [];
  templates = [];
});

// ── Boot ───────────────────────────────────────────────────────

async function init() {
  const authed = await checkAuth();
  if (authed) loadApp();
}

async function loadApp() {
  await Promise.all([fetchExercises(), fetchTemplates()]);
  setDefaultDates();
  const container = document.getElementById('setsContainer');
  if (!container.children.length) addSetRow(container);
  setupTabs();
  setupForms();
  loadDashboard();
}

// ── Tabs ───────────────────────────────────────────────────────

function setupTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
      const loaders = {
        dashboard: loadDashboard,
        history:   loadHistory,
        records:   loadRecords,
        goals:     loadGoals,
        templates: loadTemplatesTab,
      };
      loaders[btn.dataset.tab]?.();
    });
  });
}

// ── Data helpers ───────────────────────────────────────────────

async function fetchExercises() {
  const r = await fetch(`${API}/exercises`);
  exercises = await r.json();
  // Populate strength exercise dropdown
  const sel = document.getElementById('strengthExercise');
  sel.innerHTML = '<option value="">Select an exercise...</option>';
  exercises.forEach(e => {
    sel.innerHTML += `<option value="${e.id}">${e.name} (${e.muscle_group})</option>`;
  });
}

async function fetchTemplates() {
  const r = await fetch(`${API}/templates`);
  templates = await r.json();
  const sel = document.getElementById('templateSelect');
  sel.innerHTML = '<option value="">Load from template...</option>';
  templates.forEach(t => {
    sel.innerHTML += `<option value="${t.id}">${t.name}</option>`;
  });
}

function setDefaultDates() {
  const today = new Date().toISOString().split('T')[0];
  document.getElementById('workoutDate').value = today;
  document.getElementById('goalStart').value   = today;
  const later = new Date();
  later.setMonth(later.getMonth() + 1);
  document.getElementById('goalEnd').value = later.toISOString().split('T')[0];
}

// ── Exercise select builder ─────────────────────────────────────

function buildExerciseSelect(sel, selectedId = null) {
  sel.innerHTML = '<option value="">-- Select exercise --</option>';
  exercises.forEach(e => {
    sel.innerHTML += `<option value="${e.id}" ${e.id == selectedId ? 'selected' : ''}>${e.name}</option>`;
  });
  sel.innerHTML += '<option value="new">+ Add new exercise...</option>';
  sel.addEventListener('change', () => {
    if (sel.value === 'new') { sel.value = ''; openExerciseModal(sel); }
  });
}

// ── Set row factory ─────────────────────────────────────────────

function addSetRow(container, preset = null) {
  const row = document.createElement('div');
  row.className = 'set-row';
  row.innerHTML = `
    <label>Exercise<select class="exercise-select" required></select></label>
    <label>Sets<input type="number" class="sets-input"   value="${preset?.sets   ?? 3}"  min="1" required /></label>
    <label>Reps<input type="number" class="reps-input"   value="${preset?.reps   ?? 10}" min="1" required /></label>
    <label>Weight (lbs)<input type="number" class="weight-input" step="0.5"
      value="${preset?.weight ?? ''}" min="0" required /></label>
    <button type="button" class="btn-danger remove-set" style="align-self:flex-end">✕</button>
  `;
  container.appendChild(row);
  buildExerciseSelect(row.querySelector('.exercise-select'), preset?.exercise_id);
  row.querySelector('.remove-set').addEventListener('click', () => row.remove());
}

// ── Dashboard ──────────────────────────────────────────────────

async function loadDashboard() {
  await Promise.all([loadAlerts(), loadSummaryStats(), loadMuscleChart(), loadFreqChart()]);
  const sel = document.getElementById('strengthExercise');
  if (sel.value) loadStrengthChart(sel.value);
}

async function loadSummaryStats() {
  const r    = await fetch(`${API}/stats/summary`);
  const data = await r.json();
  document.getElementById('stat-total-workouts').textContent = data.total_workouts;
  document.getElementById('stat-this-week').textContent      = data.this_week;
  document.getElementById('stat-records').textContent        = data.total_records;
  document.getElementById('stat-last-workout').textContent   = data.last_workout ?? 'None yet';
}

async function loadAlerts() {
  const r = await fetch(`${API}/alerts`);
  const alerts = await r.json();
  const el = document.getElementById('alerts-container');
  el.innerHTML = alerts.map(a => `<div class="alert">⚠️ ${a.message}</div>`).join('');
}

async function loadMuscleChart() {
  const r    = await fetch(`${API}/stats/muscle_groups`);
  const data = await r.json();
  const ctx  = document.getElementById('muscleChart').getContext('2d');
  if (muscleChart) muscleChart.destroy();
  muscleChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: data.map(d => d.muscle_group),
      datasets: [{
        data: data.map(d => d.total_sets),
        backgroundColor: ['#3b82f6','#22c55e','#f59e0b','#ef4444','#8b5cf6',
                          '#06b6d4','#ec4899','#84cc16','#f97316'],
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#f1f5f9' } } },
    },
  });
}

async function loadFreqChart() {
  const r    = await fetch(`${API}/stats/weekly_frequency`);
  const data = await r.json();
  const ctx  = document.getElementById('frequencyChart').getContext('2d');
  if (freqChart) freqChart.destroy();
  freqChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.map(d => d.week),
      datasets: [{
        label: 'Workouts',
        data: data.map(d => d.count),
        backgroundColor: '#3b82f6',
        borderRadius: 4,
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#f1f5f9' } } },
      scales: {
        x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
        y: { ticks: { color: '#94a3b8', stepSize: 1 }, grid: { color: '#334155' }, beginAtZero: true },
      },
    },
  });
}

async function loadStrengthChart(exerciseId) {
  const r    = await fetch(`${API}/stats/strength/${exerciseId}`);
  const data = await r.json();
  const name = exercises.find(e => e.id == exerciseId)?.name ?? '';
  const emptyMsg = document.getElementById('strengthEmpty');

  if (!data.length) {
    if (strengthChart) { strengthChart.destroy(); strengthChart = null; }
    emptyMsg.classList.remove('hidden');
    return;
  }
  emptyMsg.classList.add('hidden');

  const ctx  = document.getElementById('strengthChart').getContext('2d');
  if (strengthChart) strengthChart.destroy();
  strengthChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.map(d => d.date),
      datasets: [{
        label: `${name} — max weight (lbs)`,
        data: data.map(d => d.max_weight),
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59,130,246,.15)',
        tension: 0.3,
        fill: true,
        pointRadius: 5,
        pointBackgroundColor: '#3b82f6',
      }],
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#f1f5f9' } } },
      scales: {
        x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
        y: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
      },
    },
  });
}

document.getElementById('strengthExercise')
  .addEventListener('change', e => { if (e.target.value) loadStrengthChart(e.target.value); });

// ── Log Workout ─────────────────────────────────────────────────

function setupForms() {
  document.getElementById('addSetBtn').addEventListener('click', () =>
    addSetRow(document.getElementById('setsContainer'))
  );

  document.getElementById('loadTemplateBtn').addEventListener('click', () => {
    const id = document.getElementById('templateSelect').value;
    if (!id) return;
    const tmpl = templates.find(t => t.id == id);
    if (!tmpl) return;
    const c = document.getElementById('setsContainer');
    c.innerHTML = '';
    tmpl.exercises.forEach(ex => addSetRow(c, ex));
  });

  document.getElementById('workoutForm').addEventListener('submit', submitWorkout);
  document.getElementById('goalForm').addEventListener('submit', submitGoal);
  document.getElementById('templateForm').addEventListener('submit', submitTemplate);
  document.getElementById('exerciseForm').addEventListener('submit', submitExercise);

  document.getElementById('addTemplateSetBtn').addEventListener('click', () => {
    const container = document.getElementById('templateSetsContainer');
    const row = document.createElement('div');
    row.className = 'set-row';
    row.innerHTML = `
      <label>Exercise<select class="tmpl-exercise-select" required></select></label>
      <label>Sets<input type="number" class="sets-input"   value="3"  min="1" required /></label>
      <label>Reps<input type="number" class="reps-input"   value="10" min="1" required /></label>
      <label>Default Weight<input type="number" class="weight-input" step="0.5" value="0" min="0" /></label>
      <button type="button" class="btn-danger" onclick="this.closest('.set-row').remove()"
              style="align-self:flex-end">✕</button>
    `;
    container.appendChild(row);
    buildExerciseSelect(row.querySelector('.tmpl-exercise-select'));
  });

  document.getElementById('closeModal').addEventListener('click', () =>
    document.getElementById('exerciseModal').classList.add('hidden')
  );

  document.getElementById('historyFilter').addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    const filtered = allWorkouts.filter(w =>
      w.date.includes(q) ||
      (w.notes && w.notes.toLowerCase().includes(q)) ||
      w.sets.some(s => s.exercise_name.toLowerCase().includes(q))
    );
    renderHistory(filtered);
  });
}

async function submitWorkout(e) {
  e.preventDefault();
  const rows = document.querySelectorAll('#setsContainer .set-row');
  if (!rows.length) { alert('Add at least one exercise.'); return; }

  const sets = [];
  for (const row of rows) {
    const exercise_id = row.querySelector('.exercise-select').value;
    if (!exercise_id) { alert('Select an exercise for every row.'); return; }
    sets.push({
      exercise_id: +exercise_id,
      sets:   +row.querySelector('.sets-input').value,
      reps:   +row.querySelector('.reps-input').value,
      weight: +row.querySelector('.weight-input').value,
    });
  }

  const res  = await fetch(`${API}/workouts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      date:  document.getElementById('workoutDate').value,
      notes: document.getElementById('workoutNotes').value,
      sets,
    }),
  });
  const data = await res.json();

  if (data.new_prs?.length) {
    const el = document.getElementById('prAlert');
    el.innerHTML = '🏆 New PR' + (data.new_prs.length > 1 ? 's' : '') + '! ' +
      data.new_prs.map(p => `${p.exercise}: ${p.weight} lbs`).join(' · ');
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 7000);
  }

  document.getElementById('setsContainer').innerHTML = '';
  document.getElementById('workoutNotes').value = '';
  addSetRow(document.getElementById('setsContainer'));
  alert('Workout saved!');
}

// ── History ─────────────────────────────────────────────────────

async function loadHistory() {
  const r = await fetch(`${API}/workouts`);
  allWorkouts = await r.json();
  document.getElementById('historyFilter').value = '';
  renderHistory(allWorkouts);
}

function renderHistory(workouts) {
  const el = document.getElementById('historyList');
  if (!workouts.length) {
    el.innerHTML = '<p class="empty-msg">No workouts yet.</p>';
    return;
  }
  el.innerHTML = workouts.map(w => {
    const volume = w.sets.reduce((sum, s) => sum + s.sets * s.reps * s.weight, 0);
    const volStr = volume > 0 ? `Total volume: ${volume.toLocaleString()} lbs` : '';
    return `
      <div class="workout-card">
        <div class="workout-card-header">
          <div>
            <div class="workout-date">${w.date}</div>
            ${w.notes ? `<div class="workout-notes">${w.notes}</div>` : ''}
          </div>
          <button class="btn-danger" onclick="deleteWorkout(${w.id})">Delete</button>
        </div>
        <table class="sets-table">
          <thead><tr><th>Exercise</th><th>Muscle</th><th>Sets</th><th>Reps</th><th>Weight</th><th>Volume</th></tr></thead>
          <tbody>
            ${w.sets.map(s => `
              <tr>
                <td>${s.exercise_name}</td>
                <td>${s.muscle_group}</td>
                <td>${s.sets}</td>
                <td>${s.reps}</td>
                <td>${s.weight} lbs</td>
                <td style="color:var(--muted)">${(s.sets * s.reps * s.weight).toLocaleString()} lbs</td>
              </tr>`).join('')}
          </tbody>
        </table>
        ${volStr ? `<div class="workout-volume">${volStr}</div>` : ''}
      </div>
    `;
  }).join('');
}

async function deleteWorkout(id) {
  if (!confirm('Delete this workout?')) return;
  await fetch(`${API}/workouts/${id}`, { method: 'DELETE' });
  loadHistory();
}

// ── Records ─────────────────────────────────────────────────────

async function loadRecords() {
  const r       = await fetch(`${API}/records`);
  const records = await r.json();
  const el      = document.getElementById('recordsList');
  if (!records.length) {
    el.innerHTML = '<p class="empty-msg">No records yet — log a workout to get started!</p>';
    return;
  }
  el.innerHTML = `<div class="records-grid">${records.map(rec => `
    <div class="record-card">
      <div class="record-muscle">${rec.muscle_group}</div>
      <div class="record-exercise">${rec.exercise_name}</div>
      <div class="record-weight">${rec.weight}<span class="record-unit"> lbs</span></div>
      <div class="record-date">${rec.date_achieved}</div>
      <span class="pr-badge">PR</span>
    </div>
  `).join('')}</div>`;
}

// ── Goals ────────────────────────────────────────────────────────

async function loadGoals() {
  const r     = await fetch(`${API}/goals`);
  const goals = await r.json();
  const el    = document.getElementById('goalsList');
  if (!goals.length) {
    el.innerHTML = '<p class="empty-msg">No active goals.</p>';
    return;
  }
  el.innerHTML = goals.map(g => `
    <div class="goal-card">
      <div>
        <div class="goal-desc">${g.target} workouts / week</div>
        <div class="goal-dates">${g.start_date} → ${g.end_date}</div>
      </div>
      <button class="btn-danger" onclick="deleteGoal(${g.id})">Remove</button>
    </div>
  `).join('');
}

async function submitGoal(e) {
  e.preventDefault();
  await fetch(`${API}/goals`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      type:       document.getElementById('goalType').value,
      target:     +document.getElementById('goalTarget').value,
      start_date: document.getElementById('goalStart').value,
      end_date:   document.getElementById('goalEnd').value,
    }),
  });
  document.getElementById('goalTarget').value = '';
  loadGoals();
}

async function deleteGoal(id) {
  await fetch(`${API}/goals/${id}`, { method: 'DELETE' });
  loadGoals();
}

// ── Templates ────────────────────────────────────────────────────

async function loadTemplatesTab() {
  await fetchTemplates();
  const el = document.getElementById('templatesList');
  if (!templates.length) {
    el.innerHTML = '<p class="empty-msg">No templates saved yet.</p>';
    return;
  }
  el.innerHTML = templates.map(t => {
    const names = t.exercises.map(ex => exercises.find(e => e.id == ex.exercise_id)?.name ?? '?').join(', ');
    return `
      <div class="template-card">
        <div>
          <div class="template-name">${t.name}</div>
          ${t.description ? `<div class="template-desc">${t.description}</div>` : ''}
          <div class="template-exs">${names}</div>
        </div>
        <button class="btn-danger" onclick="deleteTemplate(${t.id})">Delete</button>
      </div>
    `;
  }).join('');
}

async function submitTemplate(e) {
  e.preventDefault();
  const rows = document.querySelectorAll('#templateSetsContainer .set-row');
  if (!rows.length) { alert('Add at least one exercise.'); return; }

  const exs = [];
  for (const row of rows) {
    const exercise_id = row.querySelector('.tmpl-exercise-select').value;
    if (!exercise_id) { alert('Select an exercise for every row.'); return; }
    exs.push({
      exercise_id: +exercise_id,
      sets:   +row.querySelector('.sets-input').value,
      reps:   +row.querySelector('.reps-input').value,
      weight: +row.querySelector('.weight-input').value,
    });
  }

  const res = await fetch(`${API}/templates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name:        document.getElementById('templateName').value,
      description: document.getElementById('templateDesc').value,
      exercises:   exs,
    }),
  });
  if (res.ok) {
    document.getElementById('templateName').value = '';
    document.getElementById('templateDesc').value = '';
    document.getElementById('templateSetsContainer').innerHTML = '';
    loadTemplatesTab();
  }
}

async function deleteTemplate(id) {
  await fetch(`${API}/templates/${id}`, { method: 'DELETE' });
  loadTemplatesTab();
  fetchTemplates();
}

// ── Exercise Modal ────────────────────────────────────────────────

function openExerciseModal(selectEl) {
  pendingExerciseSelect = selectEl;
  document.getElementById('exerciseName').value = '';
  document.getElementById('exerciseModal').classList.remove('hidden');
  document.getElementById('exerciseName').focus();
}

async function submitExercise(e) {
  e.preventDefault();
  const res = await fetch(`${API}/exercises`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name:         document.getElementById('exerciseName').value.trim(),
      muscle_group: document.getElementById('exerciseMuscleGroup').value,
    }),
  });
  if (!res.ok) { alert('Could not add exercise (it may already exist).'); return; }
  const ex = await res.json();
  exercises.push(ex);

  // Wire new option into waiting select
  if (pendingExerciseSelect) {
    const opt = new Option(ex.name, ex.id, true, true);
    pendingExerciseSelect.insertBefore(opt, pendingExerciseSelect.lastElementChild);
    pendingExerciseSelect.value = ex.id;
    pendingExerciseSelect = null;
  }

  // Keep strength dropdown current
  const sSel = document.getElementById('strengthExercise');
  sSel.innerHTML += `<option value="${ex.id}">${ex.name} (${ex.muscle_group})</option>`;

  document.getElementById('exerciseModal').classList.add('hidden');
}

init();
