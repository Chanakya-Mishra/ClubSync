// Interactive Cursor Spotlight Tracking for Dynamic Aurora & Glass Cards
window.addEventListener('mousemove', (e) => {
  const x = ((e.clientX / window.innerWidth) * 100).toFixed(1) + '%';
  const y = ((e.clientY / window.innerHeight) * 100).toFixed(1) + '%';
  document.documentElement.style.setProperty('--mouse-x', x);
  document.documentElement.style.setProperty('--mouse-y', y);
});

let authToken = localStorage.getItem('clubsync_token') || '';
let currentUser = null;
let campusesList = [];
let allUsersList = [];
let clubsList = [];
let eventsList = [];
let activeSessionIdForDetail = null;
let qrIntervalTimer = null;
let currentLiveQrPayload = null;

// ============================================================================
// API Helper & Toast Notification
// ============================================================================

function showToast(msg, isError = false) {
  const box = document.getElementById('toast-box');
  if (!box) return;
  box.textContent = msg;
  box.className = `fixed bottom-5 right-5 z-50 max-w-sm px-4 py-3 rounded-xl shadow-lg text-xs font-medium ${
    isError ? 'bg-rose-600 text-white' : 'bg-slate-900 text-white'
  }`;
  box.classList.remove('hidden');
  setTimeout(() => box.classList.add('hidden'), 3500);
}

async function apiFetch(path, options = {}) {
  const headers = options.headers ? { ...options.headers } : {};
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }
  if (!(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    let errText = 'Request failed';
    if (typeof data.detail === 'string') errText = data.detail;
    else if (data.detail && data.detail.message) errText = data.detail.message;
    throw new Error(errText);
  }
  return data;
}

function openModal(id) {
  document.getElementById(id)?.classList.remove('hidden');
}

function closeModal(id) {
  document.getElementById(id)?.classList.add('hidden');
}

// ============================================================================
// Hero Page, Auth Screen & Workspace Navigation
// ============================================================================

function showHeroScreen() {
  document.getElementById('hero-screen').classList.remove('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app-screen').classList.add('hidden');

  const backBtn = document.getElementById('hero-back-to-app-btn');
  const signInBtn = document.getElementById('hero-signin-btn');
  const signUpBtn = document.getElementById('hero-signup-btn');
  if (currentUser) {
    backBtn?.classList.remove('hidden');
    signInBtn?.classList.add('hidden');
    signUpBtn?.classList.add('hidden');
  } else {
    backBtn?.classList.add('hidden');
    signInBtn?.classList.remove('hidden');
    signUpBtn?.classList.remove('hidden');
  }
}

function openAuthScreen(mode = 'login') {
  document.getElementById('hero-screen').classList.add('hidden');
  document.getElementById('app-screen').classList.add('hidden');
  document.getElementById('auth-screen').classList.remove('hidden');
  switchAuthMode(mode);
}

function enterWorkspace() {
  if (!currentUser) {
    openAuthScreen('login');
    return;
  }
  document.getElementById('hero-screen').classList.add('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app-screen').classList.remove('hidden');
}

async function verifyFromHero() {
  const serial = document.getElementById('hero-verify-serial-input').value.trim();
  if (!serial) return;
  const box = document.getElementById('hero-verify-result');
  try {
    const res = await apiFetch(`/api/verify/${encodeURIComponent(serial)}`);
    if (res.verified) {
      box.innerHTML = `
        <div class="p-3.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-900 text-xs space-y-1">
          <div class="font-bold">✓ Authentic ClubSync Record (${res.serial_number})</div>
          <div>Recipient: <strong>${res.recipient.full_name}</strong> (${res.recipient.roll_number || 'Verified Student'}) — ${res.recipient.campus}</div>
          <div>Title: <strong>${res.title}</strong> (${res.cert_type})</div>
          <div class="text-[11px] text-emerald-700 font-mono">SHA-256: ${res.cryptographic_proof?.pdf_sha256_hash || ''}</div>
        </div>
      `;
    } else {
      box.innerHTML = `
        <div class="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-semibold">
          ✗ ${res.message}
        </div>
      `;
    }
  } catch (err) {
    box.innerHTML = `<div class="text-rose-600 text-xs">${err.message}</div>`;
  }
}

function switchAuthMode(mode) {
  const loginForm = document.getElementById('login-form');
  const regForm = document.getElementById('register-form');
  const tabLogin = document.getElementById('auth-tab-login');
  const tabReg = document.getElementById('auth-tab-register');
  document.getElementById('auth-error').classList.add('hidden');
  document.getElementById('auth-success').classList.add('hidden');

  if (mode === 'login') {
    loginForm.classList.remove('hidden');
    regForm.classList.add('hidden');
    tabLogin.className = 'py-2 rounded-md bg-white text-slate-900 shadow-sm';
    tabReg.className = 'py-2 rounded-md text-slate-600 hover:text-slate-900';
  } else {
    loginForm.classList.add('hidden');
    regForm.classList.remove('hidden');
    tabReg.className = 'py-2 rounded-md bg-white text-slate-900 shadow-sm';
    tabLogin.className = 'py-2 rounded-md text-slate-600 hover:text-slate-900';
    updateRegRoleNotice();
  }
}

function updateRegRoleNotice() {
  const role = document.getElementById('reg-role')?.value || 'STUDENT';
  const notice = document.getElementById('reg-approval-notice');
  const btn = document.getElementById('reg-submit-btn');
  if (!notice || !btn) return;
  if (role === 'STUDENT' || role === 'PRESIDENT') {
    notice.classList.remove('hidden');
    notice.innerHTML = `<strong>Note for ${role === 'PRESIDENT' ? 'Club Presidents' : 'Students'}:</strong> Submitting this form sends an account request to your Campus Manager or Admin. You can sign in once permitted.`;
    btn.textContent = role === 'PRESIDENT' ? 'Submit Club President Request' : 'Submit Student Account Request';
  } else {
    notice.classList.add('hidden');
    btn.textContent = 'Create Account & Sign In';
  }
}

function showAuthError(msg) {
  const el = document.getElementById('auth-error');
  document.getElementById('auth-success')?.classList.add('hidden');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function showAuthSuccess(msg) {
  const el = document.getElementById('auth-success');
  document.getElementById('auth-error')?.classList.add('hidden');
  el.textContent = msg;
  el.classList.remove('hidden');
}

async function loadCampuses() {
  campusesList = await apiFetch('/api/campuses');
  const selects = ['reg-campus', 'club-campus', 'adm-user-campus'];
  selects.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.innerHTML = campusesList
        .map((c) => `<option value="${c.id}">${c.code} (${c.city})</option>`)
        .join('');
    }
  });
  const filterSelects = ['dash-campus-filter', 'clubs-campus-filter'];
  filterSelects.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.innerHTML =
        `<option value="">All Campuses</option>` +
        campusesList.map((c) => `<option value="${c.id}">${c.code}</option>`).join('');
    }
  });
}

async function handleLogin(e) {
  e.preventDefault();
  try {
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    const data = await apiFetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    authToken = data.token;
    localStorage.setItem('clubsync_token', authToken);
    currentUser = data.user;
    await enterApp();
  } catch (err) {
    showAuthError(err.message);
  }
}

async function handleRegister(e) {
  e.preventDefault();
  try {
    const emailVal = document.getElementById('reg-email').value.trim();
    const payload = {
      full_name: document.getElementById('reg-name').value.trim(),
      email: emailVal,
      password: document.getElementById('reg-password').value,
      role: document.getElementById('reg-role').value,
      campus_id: document.getElementById('reg-campus').value,
      roll_number: document.getElementById('reg-roll').value.trim() || null,
      track: document.getElementById('reg-track').value,
    };
    const data = await apiFetch('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    if (data.pending_approval) {
      switchAuthMode('login');
      document.getElementById('login-email').value = emailVal;
      showAuthSuccess(data.message);
      return;
    }

    authToken = data.token;
    localStorage.setItem('clubsync_token', authToken);
    currentUser = data.user;
    await enterApp();
  } catch (err) {
    showAuthError(err.message);
  }
}

function handleLogout() {
  authToken = '';
  currentUser = null;
  localStorage.removeItem('clubsync_token');
  showHeroScreen();
}

// ============================================================================
// Role-Scoped UI Visibility (Student vs Coordinator vs Advisor/Admin)
// ============================================================================

function applyRoleVisibility() {
  if (!currentUser) return;
  const role = currentUser.role;
  const isStudent = role === 'STUDENT';
  const isAdminOrMgr = role === 'ADMIN' || role === 'CAMPUS_MGR';
  const isAdminMgrOrAdvisor = ['ADMIN', 'CAMPUS_MGR', 'ADVISOR'].includes(role);

  // 1. Admin Command Center Tab: Only visible to Admin, Campus Manager, Advisor
  document.getElementById('tab-btn-admin')?.classList.toggle('hidden', !isAdminMgrOrAdvisor);
  const tabAdminLabel = document.getElementById('tab-admin-label');
  if (tabAdminLabel) {
    if (role === 'CAMPUS_MGR') {
      tabAdminLabel.textContent = 'Campus Approvals & Management';
    } else if (role === 'ADVISOR') {
      tabAdminLabel.textContent = 'Advisor Center';
    } else {
      tabAdminLabel.textContent = 'Admin Command Center';
    }
  }

  // 2. Stretch Tab Label & Budget Section: Hide Budgets from regular Students
  const stretchBtn = document.getElementById('tab-btn-stretch');
  if (stretchBtn) {
    stretchBtn.textContent = isStudent ? 'Duty Leave & Gallery' : 'Budgets, Duty Leave & Gallery';
  }
  document.getElementById('card-stretch-budgets')?.classList.toggle('hidden', isStudent);

  // 3. Dashboard: Hide CSV Export & Governance Alerts from Students
  document.getElementById('btn-export-csv')?.classList.toggle('hidden', isStudent);
  document.getElementById('card-dash-alerts')?.classList.toggle('hidden', isStudent);

  // 4. Clubs Tab: Hide "+ Create Club" from Students/Coordinators/Advisors; Hide Enrolment Approval Table from Students
  document.getElementById('btn-create-club')?.classList.toggle('hidden', !isAdminOrMgr);
  document.getElementById('card-enrolment-requests')?.classList.toggle('hidden', isStudent);

  // 5. Sessions Tab: Hide "+ Plan Club Day Session" from regular Students
  document.getElementById('btn-plan-session')?.classList.toggle('hidden', isStudent);

  // 6. Events Tab: Hide "+ Create Event" from Students/Coordinators/Advisors
  document.getElementById('btn-create-event')?.classList.toggle('hidden', !isAdminOrMgr);

  // 7. Certificates Tab: Hide "+ Issue New Certificate" and all-student selector from Students
  document.getElementById('btn-issue-cert')?.classList.toggle('hidden', isStudent);
  document.getElementById('admin-transcript-selector')?.classList.toggle('hidden', isStudent);

  // 8. Club News Tab: Show "+ Post Club Announcement" for Club Presidents, Campus Managers, Admins, Advisors
  const canPostNews = ['PRESIDENT', 'COORDINATOR', 'CAMPUS_MGR', 'ADMIN', 'ADVISOR'].includes(role);
  document.getElementById('btn-post-news')?.classList.toggle('hidden', !canPostNews);
}

async function enterApp() {
  document.getElementById('hero-screen').classList.add('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app-screen').classList.remove('hidden');

  document.getElementById('nav-user-name').textContent = currentUser.full_name;
  document.getElementById('nav-user-meta').textContent = `${currentUser.email} • ${currentUser.campus_code}`;
  document.getElementById('nav-role-badge').textContent = currentUser.role;

  applyRoleVisibility();
  await refreshUsersAndClubsSelectors();
  await refreshPendingBadge();
  switchTab('dashboard');
}

async function refreshUsersAndClubsSelectors() {
  allUsersList = await apiFetch('/api/users');
  clubsList = await apiFetch('/api/clubs');
  eventsList = await apiFetch('/api/events');

  const approvedUsers = allUsersList.filter((u) => u.account_status === 'APPROVED');
  const advisors = approvedUsers.filter((u) => u.role === 'ADVISOR' || u.role === 'ADMIN' || u.role === 'CAMPUS_MGR');
  const students = approvedUsers.filter((u) => u.role === 'STUDENT' || u.role === 'COORDINATOR');

  const advSelect = document.getElementById('club-advisor');
  if (advSelect) {
    advSelect.innerHTML =
      `<option value="">-- Optional --</option>` +
      advisors.map((u) => `<option value="${u.id}">${u.full_name} (${u.role})</option>`).join('');
  }
  const coordSelect = document.getElementById('club-coordinator');
  if (coordSelect) {
    coordSelect.innerHTML =
      `<option value="">-- Optional --</option>` +
      students.map((u) => `<option value="${u.id}">${u.full_name}</option>`).join('');
  }

  const studentSelects = ['override-student', 'gal-student', 'cert-student', 'transcript-student-select'];
  studentSelects.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const prefix = id === 'gal-student' ? '<option value="">-- None --</option>' : '';
    const list = approvedUsers.length ? approvedUsers : [currentUser];
    el.innerHTML =
      prefix +
      list
        .map((u) => `<option value="${u.id}">${u.full_name} (${u.roll_number || u.role})</option>`)
        .join('');
  });

  const clubSelects = ['sess-club', 'budget-club', 'gal-club'];
  clubSelects.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const prefix = id === 'gal-club' ? '<option value="">-- None --</option>' : '';
    el.innerHTML =
      prefix +
      clubsList.map((c) => `<option value="${c.id}">${c.name} (${c.code})</option>`).join('');
  });

  const evSelects = ['dl-event', 'gal-event'];
  evSelects.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const prefix = id === 'gal-event' ? '<option value="">-- None --</option>' : '';
    el.innerHTML =
      prefix +
      eventsList.map((ev) => `<option value="${ev.id}">${ev.title} (${ev.code})</option>`).join('');
  });

  populateBatchCertTargets();
}

async function refreshPendingBadge() {
  if (!currentUser || !['ADMIN', 'CAMPUS_MGR', 'ADVISOR'].includes(currentUser.role)) return;
  try {
    const q = await apiFetch('/api/admin/pending-queue');
    const badge = document.getElementById('admin-pending-badge');
    if (badge) {
      if (q.total_pending > 0) {
        badge.textContent = q.total_pending;
        badge.classList.remove('hidden');
      } else {
        badge.classList.add('hidden');
      }
    }
  } catch (_) {}
}

// ============================================================================
// Tab Switching
// ============================================================================

function switchTab(tabName) {
  if (tabName === 'admin' && currentUser && !['ADMIN', 'CAMPUS_MGR', 'ADVISOR'].includes(currentUser.role)) {
    tabName = 'dashboard';
  }
  const tabs = ['dashboard', 'clubs', 'sessions', 'events', 'stretch', 'certificates', 'news', 'admin'];
  tabs.forEach((t) => {
    document.getElementById(`tab-${t}`)?.classList.toggle('hidden', t !== tabName);
    const btn = document.getElementById(`tab-btn-${t}`);
    if (btn && !btn.classList.contains('hidden')) {
      if (t === tabName) {
        btn.className = 'py-3 whitespace-nowrap tab-active flex items-center gap-1.5';
      } else {
        btn.className = 'py-3 whitespace-nowrap text-slate-600 hover:text-slate-900 flex items-center gap-1.5';
      }
    }
  });

  if (tabName === 'dashboard') loadDashboard();
  if (tabName === 'clubs') {
    loadClubs();
    if (currentUser.role !== 'STUDENT') loadEnrolments();
  }
  if (tabName === 'sessions') loadSessions();
  if (tabName === 'events') loadEvents();
  if (tabName === 'stretch') loadStretchGoals();
  if (tabName === 'certificates') loadCertificates();
  if (tabName === 'news') loadClubNews();
  if (tabName === 'admin') loadAdminCenter();
}

// ============================================================================
// TAB 1: Dashboard & Reports
// ============================================================================

async function loadDashboard() {
  const campusId = document.getElementById('dash-campus-filter')?.value || '';
  const data = await apiFetch(`/api/dashboard/overview${campusId ? `?campus_id=${campusId}` : ''}`);

  document.getElementById('dash-campus-cards').innerHTML = data.campus_breakdown
    .map(
      (c) => `
      <div class="bg-white rounded-xl border border-slate-200 p-4 space-y-2">
        <div class="flex items-center justify-between">
          <span class="font-bold text-sm text-slate-900">${c.campus_code}</span>
          <span class="text-xs font-semibold text-blue-600">${c.participation_rate_pct}% Active</span>
        </div>
        <div class="grid grid-cols-2 gap-2 text-xs text-slate-600 pt-1">
          <div>Clubs: <strong class="text-slate-900">${c.active_clubs}/${c.total_clubs}</strong></div>
          <div>Students: <strong class="text-slate-900">${c.total_students}</strong></div>
          <div>Check-ins: <strong class="text-slate-900">${c.verified_checkins}</strong></div>
          <div>Submissions: <strong class="text-slate-900">${c.deliverables_submitted}</strong></div>
        </div>
      </div>
    `
    )
    .join('');

  const tbody = document.getElementById('dash-monthly-tbody');
  if (!data.monthly_club_reports.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="px-4 py-6 text-center text-slate-400">No clubs registered yet.</td></tr>`;
  } else {
    tbody.innerHTML = data.monthly_club_reports
      .map(
        (r) => `
        <tr>
          <td class="px-4 py-3 font-semibold text-slate-900">${r.club_name} <span class="text-slate-400 font-normal">(${r.club_code})</span></td>
          <td class="px-4 py-3">${r.campus_code}</td>
          <td class="px-4 py-3"><span class="px-2 py-0.5 rounded-full text-[11px] font-semibold ${r.status === 'ACTIVE' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}">${r.status}</span></td>
          <td class="px-4 py-3">${r.approved_members}</td>
          <td class="px-4 py-3">${r.sessions_conducted}</td>
          <td class="px-4 py-3 font-semibold">${r.attendance_percentage}%</td>
          <td class="px-4 py-3">${r.total_submissions}</td>
          <td class="px-4 py-3 font-semibold text-blue-600">${r.average_rubric_score}</td>
        </tr>
      `
      )
      .join('');
  }

  const topEl = document.getElementById('dash-top-students');
  if (!data.top_contributors.length) {
    topEl.innerHTML = `<p class="text-slate-400">No student activity recorded yet.</p>`;
  } else {
    topEl.innerHTML = data.top_contributors
      .map(
        (s, i) => `
        <div class="flex items-center justify-between py-2 border-b border-slate-100">
          <div>
            <span class="font-bold text-slate-700 mr-2">#${i + 1}</span>
            <span class="font-semibold text-slate-900">${s.full_name}</span>
            <span class="text-slate-400 ml-1">(${s.campus_code})</span>
          </div>
          <div class="text-slate-600">
            ${s.sessions_attended} Sessions • <strong class="text-blue-600">${s.cumulative_rubric_score} pts</strong>
          </div>
        </div>
      `
      )
      .join('');
  }

  const alertsEl = document.getElementById('dash-alerts');
  if (alertsEl) {
    const inactiveHtml = data.inactive_clubs.map(
      (c) => `<div class="p-2.5 rounded-lg bg-amber-50 text-amber-800">Club <strong>${c.name}</strong> (${c.campus_code}): ${c.reason}</div>`
    );
    const zeroHtml = data.zero_participation_students
      .slice(0, 8)
      .map((s) => `<div class="p-2.5 rounded-lg bg-slate-100 text-slate-700">Student <strong>${s.full_name}</strong> (${s.campus_code}): 0 sessions & 0 events</div>`);
    alertsEl.innerHTML = [...inactiveHtml, ...zeroHtml].join('') || `<p class="text-slate-400">No inactive clubs or zero-participation alerts.</p>`;
  }

  // Pending Student Account Requests (Fast approval directly from Dashboard for Campus Manager / Admin)
  const banner = document.getElementById('dash-pending-students-banner');
  const countEl = document.getElementById('dash-pending-count');
  const listEl = document.getElementById('dash-pending-students-list');
  if (banner && (currentUser.role === 'CAMPUS_MGR' || currentUser.role === 'ADMIN')) {
    try {
      const queue = await apiFetch('/api/admin/pending-queue');
      const pendingStudents = queue.pending_accounts || [];
      if (pendingStudents.length > 0) {
        if (countEl) countEl.textContent = pendingStudents.length;
        if (listEl) {
          listEl.innerHTML = pendingStudents.map((u) => `
            <div class="p-3 rounded-xl bg-white/80 border border-amber-200/80 shadow-sm flex items-center justify-between gap-2">
              <div class="truncate">
                <div class="font-bold text-slate-900 text-xs truncate">${u.full_name}</div>
                <div class="text-[11px] text-slate-500 truncate">${u.email}</div>
                <div class="text-[10px] text-amber-700 font-semibold">${u.campus_code} • ${u.roll_number || 'No Roll #'}</div>
              </div>
              <div class="flex gap-1 shrink-0">
                <button onclick="decideUserAccount('${u.id}', 'APPROVED')" class="px-2.5 py-1 rounded-lg btn-gradient-emerald text-white text-[11px] font-bold">
                  Permit
                </button>
                <button onclick="decideUserAccount('${u.id}', 'REJECTED')" class="px-2 py-1 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-[11px] font-semibold">
                  Decline
                </button>
              </div>
            </div>
          `).join('');
        }
        banner.classList.remove('hidden');
      } else {
        banner.classList.add('hidden');
      }
    } catch (_) {
      banner.classList.add('hidden');
    }
  } else if (banner) {
    banner.classList.add('hidden');
  }
}

// ============================================================================
// TAB 2: Clubs & Enrolment
// ============================================================================

async function loadClubs() {
  const campusId = document.getElementById('clubs-campus-filter')?.value || '';
  clubsList = await apiFetch(`/api/clubs${campusId ? `?campus_id=${campusId}` : ''}`);
  await refreshUsersAndClubsSelectors();

  const grid = document.getElementById('clubs-grid');
  if (!clubsList.length) {
    grid.innerHTML = `<div class="col-span-full bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-500 text-sm">No clubs available yet.</div>`;
    return;
  }

  const canManageClub = currentUser.role === 'ADMIN' || currentUser.role === 'CAMPUS_MGR' || currentUser.role === 'ADVISOR';
  const studentOptions = allUsersList
    .filter((u) => u.account_status === 'APPROVED')
    .map((u) => `<option value="${u.id}">${u.full_name} (${u.role})</option>`)
    .join('');

  grid.innerHTML = clubsList
    .map((c) => {
      const myStatus = c.my_membership
        ? `<span class="px-2.5 py-1 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-semibold">My Membership: ${c.my_membership.tier} (${c.my_membership.status})</span>`
        : `
          <button onclick="enrolInClub('${c.id}', 'PRIMARY')" class="px-3 py-1.5 rounded-lg btn-gradient text-white text-xs font-semibold">
            Join as Primary Club
          </button>
          <button onclick="enrolInClub('${c.id}', 'SECONDARY')" class="px-3 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-semibold">
            Join as Secondary Club
          </button>
        `;

      const adminControls = canManageClub
        ? `
          <div class="pt-3 mt-3 border-t border-slate-100 space-y-2">
            <div class="flex items-center justify-between gap-2">
              <button onclick="toggleClubStatus('${c.id}', '${c.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE'}')" class="px-2.5 py-1 rounded border border-slate-300 text-[11px] font-medium hover:bg-slate-50">
                ${c.status === 'ACTIVE' ? 'Deactivate Club' : 'Activate Club'}
              </button>
              <div class="flex items-center gap-1">
                <select id="assign-coord-${c.id}" class="rounded border border-slate-300 px-2 py-1 text-[11px] bg-white max-w-[130px]">
                  ${studentOptions}
                </select>
                <button onclick="assignCoordinator('${c.id}')" class="px-2 py-1 rounded btn-gradient text-white text-[11px] font-semibold">Assign President</button>
              </div>
            </div>
            <div class="flex items-center justify-end gap-1">
              <select id="assign-adv-${c.id}" class="rounded border border-slate-300 px-2 py-1 text-[11px] bg-white max-w-[150px]">
                ${studentOptions}
              </select>
              <button onclick="assignAdvisor('${c.id}')" class="px-2 py-1 rounded bg-indigo-600 text-white text-[11px]">Assign Advisor</button>
            </div>
          </div>
        `
        : '';

      return `
        <div class="bg-white rounded-xl border border-slate-200 p-5 flex flex-col justify-between space-y-3">
          <div class="space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold text-blue-600">${c.code} • ${c.campus_code}</span>
              <span class="px-2 py-0.5 rounded-full text-[11px] font-semibold ${c.status === 'ACTIVE' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}">${c.status}</span>
            </div>
            <h3 class="text-sm font-bold text-slate-900">${c.name}</h3>
            <p class="text-xs text-slate-500">${c.description}</p>
            <div class="text-[11px] text-slate-600 space-y-0.5 pt-1">
              <div>Category: <strong>${c.category}</strong> • Members: <strong>${c.approved_members}/${c.capacity}</strong></div>
              <div>Advisor: <strong>${c.advisor_name}</strong></div>
              <div>Club President: <strong class="text-indigo-700">${c.coordinators.map((co) => co.name).join(', ') || 'None (Assigned by Campus Mgr)'}</strong></div>
              <div>Schedule: ${c.meeting_rules}</div>
            </div>
          </div>
          <div>
            <div class="flex flex-wrap gap-2 pt-2">${myStatus}</div>
            ${adminControls}
          </div>
        </div>
      `;
    })
    .join('');
}

async function submitCreateClub(e) {
  e.preventDefault();
  try {
    await apiFetch('/api/clubs', {
      method: 'POST',
      body: JSON.stringify({
        campus_id: document.getElementById('club-campus').value,
        code: document.getElementById('club-code').value,
        name: document.getElementById('club-name').value,
        category: document.getElementById('club-category').value,
        capacity: parseInt(document.getElementById('club-capacity').value, 10),
        description: document.getElementById('club-desc').value,
        advisor_id: document.getElementById('club-advisor').value || null,
        coordinator_id: document.getElementById('club-coordinator').value || null,
        meeting_rules: document.getElementById('club-rules').value,
      }),
    });
    closeModal('modal-create-club');
    showToast('Club created successfully');
    loadClubs();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function toggleClubStatus(clubId, status) {
  try {
    await apiFetch(`/api/clubs/${clubId}/status?status=${status}`, { method: 'PATCH' });
    showToast(`Club marked as ${status}`);
    loadClubs();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function assignCoordinator(clubId) {
  const studentId = document.getElementById(`assign-coord-${clubId}`)?.value;
  if (!studentId) return;
  try {
    const res = await apiFetch(`/api/clubs/${clubId}/assign-coordinator?student_id=${studentId}&tier=PRESIDENT`, { method: 'POST' });
    showToast(res.message || 'Club President assigned');
    loadClubs();
    if (currentUser.role !== 'STUDENT') loadEnrolments();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function assignAdvisor(clubId) {
  const advisorId = document.getElementById(`assign-adv-${clubId}`)?.value;
  if (!advisorId) return;
  try {
    const res = await apiFetch(`/api/clubs/${clubId}/assign-advisor?advisor_id=${advisorId}`, { method: 'PATCH' });
    showToast(res.message);
    loadClubs();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function enrolInClub(clubId, tier) {
  try {
    const res = await apiFetch(`/api/clubs/${clubId}/enrol`, {
      method: 'POST',
      body: JSON.stringify({ tier }),
    });
    showToast(res.message);
    loadClubs();
    if (currentUser.role !== 'STUDENT') loadEnrolments();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function loadEnrolments() {
  if (currentUser.role === 'STUDENT') return;
  const status = document.getElementById('enrolment-status-filter')?.value || '';
  const rows = await apiFetch(`/api/enrolments${status ? `?status=${status}` : ''}`);
  const tbody = document.getElementById('enrolments-tbody');
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-5 text-center text-slate-400">No membership requests found.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map(
      (r) => `
      <tr>
        <td class="px-4 py-2.5 font-semibold text-slate-900">${r.student_name}</td>
        <td class="px-4 py-2.5 text-slate-500">${r.roll_number || '-'}</td>
        <td class="px-4 py-2.5">${r.club_name}</td>
        <td class="px-4 py-2.5 font-semibold">${r.tier}</td>
        <td class="px-4 py-2.5">
          <span class="px-2 py-0.5 rounded-full text-[11px] font-semibold ${
            r.status === 'APPROVED' ? 'bg-emerald-50 text-emerald-700' : r.status === 'REJECTED' ? 'bg-rose-50 text-rose-700' : 'bg-amber-50 text-amber-700'
          }">${r.status}</span>
        </td>
        <td class="px-4 py-2.5">
          ${
            r.status === 'PENDING'
              ? `
                <button onclick="decideEnrolment('${r.id}', 'APPROVED')" class="px-2.5 py-1 rounded bg-emerald-600 text-white text-[11px] font-semibold mr-1">Approve</button>
                <button onclick="decideEnrolment('${r.id}', 'REJECTED')" class="px-2.5 py-1 rounded bg-rose-600 text-white text-[11px] font-semibold">Reject</button>
              `
              : '<span class="text-slate-400">—</span>'
          }
        </td>
      </tr>
    `
    )
    .join('');
}

async function decideEnrolment(membershipId, status) {
  try {
    await apiFetch(`/api/enrolments/${membershipId}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
    showToast(`Enrolment ${status.toLowerCase()}`);
    loadEnrolments();
    loadClubs();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// TAB 3: Club Day Sessions (7-Step Flow, QR Check-In, Deliverables, Rubrics)
// ============================================================================

function openPlanSessionModal() {
  if (!clubsList.length) {
    showToast('Create a club first before planning a session.', true);
    return;
  }
  openModal('modal-plan-session');
}

async function submitPlanSession(e) {
  e.preventDefault();
  try {
    await apiFetch('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({
        club_id: document.getElementById('sess-club').value,
        week_number: parseInt(document.getElementById('sess-week').value, 10),
        scheduled_date: document.getElementById('sess-date').value,
        topic: document.getElementById('sess-topic').value,
        format: document.getElementById('sess-format').value,
        venue: document.getElementById('sess-venue').value,
        deliverable_desc: document.getElementById('sess-deliverable').value,
        submission_deadline: document.getElementById('sess-deadline').value,
      }),
    });
    closeModal('modal-plan-session');
    showToast('Club Day session planned');
    loadSessions();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function loadSessions() {
  const sessions = await apiFetch('/api/sessions');
  const container = document.getElementById('sessions-list');
  if (!sessions.length) {
    container.innerHTML = `<div class="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-500 text-sm">No Club Day sessions scheduled yet.</div>`;
    return;
  }

  const isAdvisorOrAdmin = ['ADVISOR', 'CAMPUS_MGR', 'ADMIN'].includes(currentUser.role);
  const isStaffOrCoord = currentUser.role !== 'STUDENT';

  container.innerHTML = sessions
    .map((s) => {
      const approvalBtns =
        isAdvisorOrAdmin && s.plan_status !== 'APPROVED'
          ? `
            <button onclick="approveSessionPlan('${s.id}', 'APPROVED')" class="px-3 py-1.5 rounded-lg btn-gradient-emerald text-white text-xs font-semibold">
              Approve Plan
            </button>
            <button onclick="approveSessionPlan('${s.id}', 'CHANGES_REQUESTED')" class="px-3 py-1.5 rounded-lg border border-amber-300 bg-amber-50 text-amber-800 text-xs font-semibold">
              Request Changes
            </button>
          `
          : '';

      const announceBtn =
        isStaffOrCoord && s.plan_status === 'APPROVED' && !s.announced
          ? `<button onclick="announceSession('${s.id}')" class="px-3 py-1.5 rounded-lg border border-blue-300 bg-blue-50 text-blue-700 text-xs font-semibold">Announce to Members</button>`
          : '';

      const windowBtn =
        isStaffOrCoord && s.plan_status === 'APPROVED'
          ? s.checkin_status !== 'OPEN'
            ? `<button onclick="toggleCheckinWindow('${s.id}', 'OPEN')" class="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold">Open Check-In Window</button>`
            : `<button onclick="toggleCheckinWindow('${s.id}', 'CLOSE')" class="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold">Close Check-In Window</button>`
          : '';

      const checkinBtn =
        s.checkin_status === 'OPEN'
          ? `<button onclick="openCheckinModal('${s.id}')" class="px-3 py-1.5 rounded-lg btn-gradient text-white text-xs font-semibold">${
              isStaffOrCoord ? 'Show Live QR / Check-In' : 'Check In to Session'
            }</button>`
          : '';

      const manageRosterBtn = isStaffOrCoord
        ? `<button onclick="openSessionDetail('${s.id}')" class="px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-semibold">
            Manage Roster & Grade
          </button>`
        : '';

      return `
        <div class="bg-white rounded-xl border border-slate-200 p-5 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div class="space-y-1.5">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs font-bold text-blue-600">${s.club_name} (${s.club_code})</span>
              <span class="text-xs text-slate-500">Week ${s.week_number} • ${s.scheduled_date} • ${s.venue}</span>
              <span class="px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                s.plan_status === 'APPROVED' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
              }">Plan: ${s.plan_status}</span>
              <span class="px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                s.checkin_status === 'OPEN' ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-600'
              }">Check-In: ${s.checkin_status}</span>
            </div>
            <h3 class="text-sm font-bold text-slate-900">${s.topic} <span class="text-xs font-normal text-slate-500">[${s.format}]</span></h3>
            <p class="text-xs text-slate-600">Deliverable: <strong>${s.deliverable_desc}</strong> (Deadline: ${s.submission_deadline})</p>
            <div class="text-xs text-slate-500">
              Checked In: <strong>${s.attendance_count}</strong> • Submissions: <strong>${s.submission_count}</strong>
              ${s.my_attendance ? ` • <span class="text-emerald-700 font-semibold">My Attendance: ${s.my_attendance.status}</span>` : ''}
              ${s.my_submission ? ` • <span class="text-blue-700 font-semibold">My Deliverable: ${s.my_submission.score !== null ? 'Graded ' + s.my_submission.score + '/30' : 'Submitted (Pending Grade)'}</span>` : ''}
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-2">
            ${approvalBtns}
            ${announceBtn}
            ${windowBtn}
            ${checkinBtn}
            <button onclick="openSubmitWorkModal('${s.id}')" class="px-3 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-semibold">
              Submit Deliverable
            </button>
            ${manageRosterBtn}
          </div>
        </div>
      `;
    })
    .join('');
}

async function approveSessionPlan(sessionId, planStatus) {
  try {
    await apiFetch(`/api/sessions/${sessionId}/approval`, {
      method: 'PATCH',
      body: JSON.stringify({ plan_status: planStatus, advisor_feedback: `Reviewed by ${currentUser.full_name}` }),
    });
    showToast(`Session plan ${planStatus.toLowerCase()}`);
    loadSessions();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function announceSession(sessionId) {
  try {
    await apiFetch(`/api/sessions/${sessionId}/announce`, { method: 'POST' });
    showToast('Session announced to club members');
    loadSessions();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function toggleCheckinWindow(sessionId, action) {
  try {
    await apiFetch(`/api/sessions/${sessionId}/checkin-window`, {
      method: 'POST',
      body: JSON.stringify({ action, duration_minutes: 45, late_after_minutes: 15 }),
    });
    showToast(`Check-in window ${action === 'OPEN' ? 'opened' : 'closed'}`);
    loadSessions();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function openCheckinModal(sessionId) {
  document.getElementById('checkin-session-id').value = sessionId;
  document.getElementById('checkin-otp-input').value = '';
  openModal('modal-checkin');
  await refreshLiveQr(sessionId);
  if (qrIntervalTimer) clearInterval(qrIntervalTimer);
  qrIntervalTimer = setInterval(() => refreshLiveQr(sessionId), 5000);
}

function closeCheckinModal() {
  if (qrIntervalTimer) clearInterval(qrIntervalTimer);
  closeModal('modal-checkin');
}

async function refreshLiveQr(sessionId) {
  try {
    const data = await apiFetch(`/api/sessions/${sessionId}/qr`);
    currentLiveQrPayload = data;
    document.getElementById('live-qr-img').src = data.qr_image_base64;
    document.getElementById('live-otp-code').textContent = data.otp_code;
  } catch (err) {
    showToast(err.message, true);
  }
}

async function checkinWithLiveQr() {
  const sessionId = document.getElementById('checkin-session-id').value;
  if (!currentLiveQrPayload) return;
  try {
    const res = await apiFetch(`/api/sessions/${sessionId}/checkin`, {
      method: 'POST',
      body: JSON.stringify({ qr_token: currentLiveQrPayload.qr_token }),
    });
    showToast(res.message);
    closeCheckinModal();
    loadSessions();
    if (activeSessionIdForDetail === sessionId) openSessionDetail(sessionId);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function submitStudentCheckin(e) {
  e.preventDefault();
  const sessionId = document.getElementById('checkin-session-id').value;
  const otp = document.getElementById('checkin-otp-input').value.trim();
  if (!otp) {
    showToast('Enter the 6-digit code or click Scan / Check In with QR.', true);
    return;
  }
  try {
    const res = await apiFetch(`/api/sessions/${sessionId}/checkin`, {
      method: 'POST',
      body: JSON.stringify({ otp_code: otp }),
    });
    showToast(res.message);
    closeCheckinModal();
    loadSessions();
    if (activeSessionIdForDetail === sessionId) openSessionDetail(sessionId);
  } catch (err) {
    showToast(err.message, true);
  }
}

function openSubmitWorkModal(sessionId) {
  document.getElementById('sub-session-id').value = sessionId;
  document.getElementById('sub-title').value = '';
  document.getElementById('sub-link').value = '';
  document.getElementById('sub-notes').value = '';
  document.getElementById('sub-file-input').value = '';
  openModal('modal-submit-work');
}

async function submitDeliverableForm(e) {
  e.preventDefault();
  const sessionId = document.getElementById('sub-session-id').value;
  const fileInput = document.getElementById('sub-file-input');
  let uploadedUrl = null;

  try {
    if (fileInput.files.length > 0) {
      const fd = new FormData();
      fd.append('file', fileInput.files[0]);
      const up = await apiFetch('/api/upload', { method: 'POST', body: fd });
      uploadedUrl = up.file_url;
    }

    const res = await apiFetch(`/api/sessions/${sessionId}/submissions`, {
      method: 'POST',
      body: JSON.stringify({
        title: document.getElementById('sub-title').value,
        deliverable_type: document.getElementById('sub-type').value,
        file_url: uploadedUrl,
        external_link: document.getElementById('sub-link').value || null,
        notes: document.getElementById('sub-notes').value || null,
      }),
    });
    closeModal('modal-submit-work');
    showToast(res.message);
    loadSessions();
    if (activeSessionIdForDetail === sessionId) openSessionDetail(sessionId);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function openSessionDetail(sessionId) {
  if (currentUser.role === 'STUDENT') return;
  activeSessionIdForDetail = sessionId;
  await refreshUsersAndClubsSelectors();
  const data = await apiFetch(`/api/sessions/${sessionId}/details`);
  const panel = document.getElementById('session-detail-panel');
  panel.classList.remove('hidden');

  document.getElementById('detail-session-title').textContent = `${data.session.topic} (Week ${data.session.week_number})`;
  document.getElementById('detail-session-meta').textContent = `Date: ${data.session.scheduled_date} • Venue: ${data.session.venue} • Deliverable: ${data.session.deliverable_desc}`;

  const attContainer = document.getElementById('detail-attendance-list');
  if (!data.attendances.length) {
    attContainer.innerHTML = `<p class="text-slate-400">No students checked in yet.</p>`;
  } else {
    attContainer.innerHTML = data.attendances
      .map(
        (a) => `
        <div class="p-3 rounded-xl glass-subcard flex items-center justify-between gap-2">
          <div>
            <div class="font-semibold text-slate-900">${a.student_name} <span class="text-slate-400 font-normal">(${a.roll_number || ''})</span></div>
            <div class="text-[11px] text-slate-500">
              Status: <strong>${a.status}</strong> via ${a.method}
              ${a.is_presenter ? ' • <span class="text-blue-600 font-semibold">Presenter</span>' : ''}
              ${a.override_reason ? ` • Reason: ${a.override_reason}` : ''}
            </div>
          </div>
          <button onclick="togglePresenter('${sessionId}', '${a.student_id}', ${!a.is_presenter})" class="px-2.5 py-1 rounded border border-slate-300 text-[11px] hover:bg-slate-50">
            ${a.is_presenter ? 'Unmark Presenter' : 'Mark Presenter'}
          </button>
        </div>
      `
      )
      .join('');
  }

  const subContainer = document.getElementById('detail-submissions-list');
  if (!data.submissions.length) {
    subContainer.innerHTML = `<p class="text-slate-400">No deliverables submitted yet.</p>`;
  } else {
    subContainer.innerHTML = data.submissions
      .map(
        (s) => `
        <div class="p-3 rounded-xl glass-subcard space-y-1.5">
          <div class="flex items-center justify-between">
            <span class="font-semibold text-slate-900">${s.title} <span class="text-slate-400 font-normal">by ${s.student_name}</span></span>
            ${
              s.evaluation
                ? `<span class="px-2 py-0.5 rounded bg-blue-50 text-blue-700 font-bold">${s.evaluation.total_score}/30</span>`
                : `<span class="text-amber-600 font-medium">Ungraded</span>`
            }
          </div>
          <div class="text-[11px] text-slate-500 flex flex-wrap gap-3">
            <span>Type: ${s.deliverable_type}</span>
            ${s.file_url ? `<a href="${s.file_url}" target="_blank" class="text-blue-600 underline">Download File</a>` : ''}
            ${s.external_link ? `<a href="${s.external_link}" target="_blank" class="text-blue-600 underline">Open Link</a>` : ''}
          </div>
          ${s.evaluation ? `<div class="text-[11px] text-slate-600">Feedback: ${s.evaluation.comments}</div>` : ''}
          <div class="pt-1">
            <button onclick="openEvaluateModal('${s.id}')" class="px-2.5 py-1 rounded bg-slate-900 text-white text-[11px] font-semibold">
              ${s.evaluation ? 'Update Score' : 'Score Rubric (/30)'}
            </button>
          </div>
        </div>
      `
      )
      .join('');
  }
}

function closeSessionDetail() {
  activeSessionIdForDetail = null;
  document.getElementById('session-detail-panel').classList.add('hidden');
}

async function togglePresenter(sessionId, studentId, isPresenter) {
  try {
    await apiFetch(`/api/sessions/${sessionId}/presenter`, {
      method: 'PATCH',
      body: JSON.stringify({ student_id: studentId, is_presenter: isPresenter }),
    });
    showToast('Presenter status updated');
    openSessionDetail(sessionId);
  } catch (err) {
    showToast(err.message, true);
  }
}

function openManualOverrideModal() {
  if (!activeSessionIdForDetail) return;
  openModal('modal-manual-override');
}

async function submitManualOverride(e) {
  e.preventDefault();
  try {
    await apiFetch(`/api/sessions/${activeSessionIdForDetail}/attendance/override`, {
      method: 'POST',
      body: JSON.stringify({
        student_id: document.getElementById('override-student').value,
        status: document.getElementById('override-status').value,
        reason: document.getElementById('override-reason').value,
      }),
    });
    closeModal('modal-manual-override');
    showToast('Attendance override recorded');
    openSessionDetail(activeSessionIdForDetail);
    loadSessions();
  } catch (err) {
    showToast(err.message, true);
  }
}

function openEvaluateModal(submissionId) {
  document.getElementById('eval-submission-id').value = submissionId;
  openModal('modal-evaluate');
}

async function submitEvaluationForm(e) {
  e.preventDefault();
  const subId = document.getElementById('eval-submission-id').value;
  try {
    await apiFetch(`/api/submissions/${subId}/evaluate`, {
      method: 'POST',
      body: JSON.stringify({
        content_score: parseFloat(document.getElementById('eval-content').value),
        presentation_score: parseFloat(document.getElementById('eval-presentation').value),
        participation_score: parseFloat(document.getElementById('eval-participation').value),
        comments: document.getElementById('eval-comments').value,
      }),
    });
    closeModal('modal-evaluate');
    showToast('Rubric evaluation saved');
    if (activeSessionIdForDetail) openSessionDetail(activeSessionIdForDetail);
    loadSessions();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// TAB 4: Events & Teams
// ============================================================================

async function loadEvents() {
  eventsList = await apiFetch('/api/events');
  await refreshUsersAndClubsSelectors();

  const grid = document.getElementById('events-grid');
  if (!eventsList.length) {
    grid.innerHTML = `<div class="col-span-full bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-500 text-sm">No events scheduled yet.</div>`;
    return;
  }

  const canManage = currentUser.role !== 'STUDENT';

  grid.innerHTML = eventsList
    .map((ev) => {
      const teamsHtml = ev.teams.length
        ? ev.teams
            .map(
              (t) => `
              <div class="p-2.5 rounded-xl glass-subcard flex flex-wrap items-center justify-between gap-2 text-xs">
                <div>
                  <span class="font-bold text-slate-800">${t.team_name}</span>
                  <span class="font-mono text-[11px] bg-white border border-slate-200 px-1.5 py-0.5 rounded ml-1">Code: ${t.invite_code}</span>
                  <div class="text-[11px] text-slate-500">Members: ${t.member_count}/${ev.max_team_size} • Result: <strong>${t.result_position || 'Pending'}</strong></div>
                </div>
                ${
                  canManage
                    ? `
                      <select onchange="setTeamResult('${t.id}', this.value)" class="rounded border border-slate-300 bg-white px-2 py-1 text-[11px]">
                        <option value="">Set Result...</option>
                        <option value="WINNER">WINNER</option>
                        <option value="RUNNER_UP">RUNNER_UP</option>
                        <option value="FINALIST">FINALIST</option>
                        <option value="PARTICIPANT">PARTICIPANT</option>
                      </select>
                    `
                    : ''
                }
              </div>
            `
            )
            .join('')
        : `<p class="text-xs text-slate-400">No teams formed yet.</p>`;

      return `
        <div class="glass-card rounded-2xl p-5 space-y-4 animate-enter">
          <div class="flex items-start justify-between gap-2">
            <div>
              <span class="text-xs font-bold text-blue-600">${ev.code} • ${ev.category} (${ev.scope})</span>
              <h3 class="text-base font-bold text-slate-900 mt-0.5">${ev.title}</h3>
              <p class="text-xs text-slate-500">${ev.start_date} to ${ev.end_date} • ${ev.venue}</p>
            </div>
            <span class="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-blue-50 text-blue-700">${ev.total_registrations} Registered</span>
          </div>
          <p class="text-xs text-slate-600">${ev.description}</p>

          <div class="flex flex-wrap gap-2">
            ${
              ev.my_registration
                ? `
                  <span class="px-3 py-1.5 rounded-lg bg-emerald-50 text-emerald-700 text-xs font-semibold">✓ Registered</span>
                  ${
                    !ev.my_registration.checked_in
                      ? `<button onclick="checkinToEvent('${ev.id}')" class="px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-semibold">Check In Now</button>`
                      : `<span class="px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 text-xs font-semibold">✓ Checked In</span>`
                  }
                `
                : `<button onclick="openRegisterEventModal('${ev.id}')" class="px-3.5 py-1.5 rounded-lg btn-gradient text-white text-xs font-semibold">Register for Event</button>`
            }
          </div>

          <div class="space-y-2 pt-2 border-t border-slate-100">
            <h4 class="text-xs font-bold uppercase text-slate-500">Registered Teams & Invite Codes</h4>
            ${teamsHtml}
          </div>
        </div>
      `;
    })
    .join('');
}

async function submitCreateEvent(e) {
  e.preventDefault();
  try {
    await apiFetch('/api/events', {
      method: 'POST',
      body: JSON.stringify({
        code: document.getElementById('ev-code').value,
        category: document.getElementById('ev-category').value,
        title: document.getElementById('ev-title').value,
        scope: document.getElementById('ev-scope').value,
        max_team_size: parseInt(document.getElementById('ev-team-size').value, 10),
        start_date: document.getElementById('ev-start').value,
        end_date: document.getElementById('ev-end').value,
        venue: document.getElementById('ev-venue').value,
        description: document.getElementById('ev-desc').value,
        duty_leave_eligible: document.getElementById('ev-dutyleave').checked,
      }),
    });
    closeModal('modal-create-event');
    showToast('Event created');
    loadEvents();
  } catch (err) {
    showToast(err.message, true);
  }
}

function openRegisterEventModal(eventId) {
  document.getElementById('reg-event-id').value = eventId;
  document.getElementById('reg-event-mode').value = 'INDIVIDUAL';
  toggleEventRegFields();
  openModal('modal-register-event');
}

function toggleEventRegFields() {
  const mode = document.getElementById('reg-event-mode').value;
  document.getElementById('reg-create-team-fields').classList.toggle('hidden', mode !== 'CREATE_TEAM');
  document.getElementById('reg-join-team-fields').classList.toggle('hidden', mode !== 'JOIN_TEAM');
}

async function submitEventRegistration(e) {
  e.preventDefault();
  const eventId = document.getElementById('reg-event-id').value;
  try {
    const res = await apiFetch(`/api/events/${eventId}/register`, {
      method: 'POST',
      body: JSON.stringify({
        mode: document.getElementById('reg-event-mode').value,
        team_name: document.getElementById('reg-team-name').value || null,
        project_title: document.getElementById('reg-project-title').value || null,
        invite_code: document.getElementById('reg-invite-code').value || null,
      }),
    });
    closeModal('modal-register-event');
    showToast(res.message);
    loadEvents();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function checkinToEvent(eventId) {
  try {
    await apiFetch(`/api/events/${eventId}/checkin`, { method: 'POST' });
    showToast('Checked into event');
    loadEvents();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function setTeamResult(teamId, position) {
  if (!position) return;
  try {
    await apiFetch(`/api/teams/${teamId}/result`, {
      method: 'PATCH',
      body: JSON.stringify({ result_position: position }),
    });
    showToast(`Team marked as ${position}`);
    loadEvents();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// TAB 5: Budgets, Duty Leave & Event Photo Gallery
// ============================================================================

async function loadStretchGoals() {
  await refreshUsersAndClubsSelectors();
  const [budgets, leaves, gallery] = await Promise.all([
    apiFetch('/api/budgets'),
    apiFetch('/api/duty-leaves'),
    apiFetch(`/api/gallery?include_hidden=${document.getElementById('gallery-show-hidden')?.checked ? 'true' : 'false'}`),
  ]);

  const canReviewBudget = ['ADVISOR', 'CAMPUS_MGR', 'ADMIN'].includes(currentUser.role);
  const canReviewLeave = ['CAMPUS_MGR', 'ADMIN'].includes(currentUser.role);

  if (currentUser.role !== 'STUDENT') {
    const bTbody = document.getElementById('budgets-tbody');
    bTbody.innerHTML = budgets.length
      ? budgets
          .map(
            (b) => `
            <tr>
              <td class="px-4 py-2.5 font-semibold">${b.club_name}</td>
              <td class="px-4 py-2.5"><strong>${b.title}</strong> <span class="text-slate-400">(${b.category})</span></td>
              <td class="px-4 py-2.5 font-semibold">₹${b.amount_inr.toLocaleString()}</td>
              <td class="px-4 py-2.5">${b.requested_by}</td>
              <td class="px-4 py-2.5"><span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-100 text-slate-700">${b.status}</span></td>
              <td class="px-4 py-2.5">
                ${
                  canReviewBudget && b.status !== 'APPROVED' && b.status !== 'REJECTED'
                    ? `
                      <button onclick="decideBudget('${b.id}', 'APPROVE')" class="px-2.5 py-1 rounded bg-emerald-600 text-white text-[11px] font-semibold mr-1">Approve</button>
                      <button onclick="decideBudget('${b.id}', 'REJECT')" class="px-2.5 py-1 rounded bg-rose-600 text-white text-[11px] font-semibold">Reject</button>
                    `
                    : '<span class="text-slate-400">—</span>'
                }
              </td>
            </tr>
          `
          )
          .join('')
      : `<tr><td colspan="6" class="px-4 py-5 text-center text-slate-400">No budget requests yet.</td></tr>`;
  }

  const visibleLeaves = currentUser.role === 'STUDENT' ? leaves.filter((l) => l.student_id === currentUser.id) : leaves;
  const dlTbody = document.getElementById('dutyleaves-tbody');
  dlTbody.innerHTML = visibleLeaves.length
    ? visibleLeaves
        .map(
          (d) => `
          <tr>
            <td class="px-4 py-2.5 font-semibold">${d.student_name} <span class="text-slate-400">(${d.roll_number || ''})</span></td>
            <td class="px-4 py-2.5">${d.event_title}</td>
            <td class="px-4 py-2.5">${d.leave_dates}</td>
            <td class="px-4 py-2.5 text-slate-500">${d.reason}</td>
            <td class="px-4 py-2.5"><span class="px-2 py-0.5 rounded-full text-[11px] font-semibold ${
              d.status === 'APPROVED' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
            }">${d.status}</span></td>
            <td class="px-4 py-2.5">
              ${
                canReviewLeave && d.status === 'PENDING_CM_APPROVAL'
                  ? `
                    <button onclick="decideDutyLeave('${d.id}', 'APPROVED')" class="px-2.5 py-1 rounded bg-emerald-600 text-white text-[11px] font-semibold mr-1">Approve</button>
                    <button onclick="decideDutyLeave('${d.id}', 'REJECTED')" class="px-2.5 py-1 rounded bg-rose-600 text-white text-[11px] font-semibold">Reject</button>
                  `
                  : '<span class="text-slate-400">—</span>'
              }
            </td>
          </tr>
        `
        )
        .join('')
    : `<tr><td colspan="6" class="px-4 py-5 text-center text-slate-400">No Duty Leave requests yet.</td></tr>`;

  const galGrid = document.getElementById('gallery-grid');
  galGrid.innerHTML = gallery.length
    ? gallery
        .map(
          (g) => `
          <div class="glass-card rounded-2xl overflow-hidden flex flex-col justify-between animate-enter">
            <img src="${g.media_url}" alt="${g.caption}" class="w-full h-40 object-cover bg-slate-200" />
            <div class="p-3.5 space-y-2 text-xs">
              <div class="font-semibold text-slate-900">${g.caption}</div>
              <div class="text-[11px] text-slate-500">
                ${g.club_name || g.event_title || 'Campus Activity'}
                ${g.tagged_student_name ? ` • Tagged: ${g.tagged_student_name}` : ''}
              </div>
              <div class="flex items-center justify-between pt-1">
                <span class="px-2 py-0.5 rounded text-[11px] font-semibold ${
                  g.student_consent ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'
                }">${g.student_consent ? 'Consent: Public' : 'Consent Revoked'}</span>
                <button onclick="togglePhotoConsent('${g.id}', ${!g.student_consent})" class="px-2.5 py-1 rounded border border-slate-300 bg-white text-[11px] font-medium">
                  ${g.student_consent ? 'Hide Photo' : 'Restore Consent'}
                </button>
              </div>
            </div>
          </div>
        `
        )
        .join('')
    : `<div class="col-span-full text-center py-6 text-slate-400 text-xs">No photos uploaded yet.</div>`;
}

function openBudgetModal() {
  if (!clubsList.length) {
    showToast('Create a club first before requesting a budget.', true);
    return;
  }
  openModal('modal-create-budget');
}

async function submitBudgetRequest(e) {
  e.preventDefault();
  try {
    await apiFetch('/api/budgets', {
      method: 'POST',
      body: JSON.stringify({
        club_id: document.getElementById('budget-club').value,
        title: document.getElementById('budget-title').value,
        category: document.getElementById('budget-category').value,
        amount_inr: parseFloat(document.getElementById('budget-amount').value),
        description: document.getElementById('budget-desc').value,
      }),
    });
    closeModal('modal-create-budget');
    showToast('Budget request submitted');
    loadStretchGoals();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function decideBudget(budgetId, decision) {
  try {
    await apiFetch(`/api/budgets/${budgetId}/approve`, {
      method: 'PATCH',
      body: JSON.stringify({ decision, notes: `Reviewed by ${currentUser.full_name}` }),
    });
    showToast('Budget status updated');
    loadStretchGoals();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

function openDutyLeaveModal() {
  if (!eventsList.length) {
    showToast('No events available yet for Duty Leave.', true);
    return;
  }
  openModal('modal-create-dutyleave');
}

async function submitDutyLeaveRequest(e) {
  e.preventDefault();
  try {
    await apiFetch('/api/duty-leaves', {
      method: 'POST',
      body: JSON.stringify({
        event_id: document.getElementById('dl-event').value,
        leave_dates: document.getElementById('dl-dates').value,
        reason: document.getElementById('dl-reason').value,
      }),
    });
    closeModal('modal-create-dutyleave');
    showToast('Duty Leave request submitted');
    loadStretchGoals();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function decideDutyLeave(leaveId, status) {
  try {
    await apiFetch(`/api/duty-leaves/${leaveId}/approve`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
    showToast(`Duty Leave ${status.toLowerCase()}`);
    loadStretchGoals();
    refreshPendingBadge();
  } catch (err) {
    showToast(err.message, true);
  }
}

function openGalleryModal() {
  openModal('modal-create-gallery');
}

async function submitGalleryPhoto(e) {
  e.preventDefault();
  const fileInput = document.getElementById('gal-file');
  let mediaUrl = document.getElementById('gal-url').value.trim();

  try {
    if (fileInput.files.length > 0) {
      const fd = new FormData();
      fd.append('file', fileInput.files[0]);
      const up = await apiFetch('/api/upload', { method: 'POST', body: fd });
      mediaUrl = up.file_url;
    }
    if (!mediaUrl) {
      showToast('Upload an image file or provide an image URL.', true);
      return;
    }
    await apiFetch('/api/gallery', {
      method: 'POST',
      body: JSON.stringify({
        club_id: document.getElementById('gal-club').value || null,
        event_id: document.getElementById('gal-event').value || null,
        caption: document.getElementById('gal-caption').value,
        media_url: mediaUrl,
        tagged_student_id: document.getElementById('gal-student').value || null,
        student_consent: true,
      }),
    });
    closeModal('modal-create-gallery');
    showToast('Photo added to gallery');
    loadStretchGoals();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function togglePhotoConsent(itemId, consent) {
  try {
    await apiFetch(`/api/gallery/${itemId}/consent`, {
      method: 'PATCH',
      body: JSON.stringify({ student_consent: consent }),
    });
    showToast('Photo consent updated');
    loadStretchGoals();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// TAB 6: Certificates, Transcripts & Public Verification
// ============================================================================

async function loadCertificates() {
  await refreshUsersAndClubsSelectors();
  const query = currentUser.role === 'STUDENT' ? `?student_id=${currentUser.id}` : '';
  const certs = await apiFetch(`/api/certificates${query}`);
  const tbody = document.getElementById('certificates-tbody');
  if (!certs.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-6 text-center text-slate-400">No certificates or transcripts issued yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = certs
    .map(
      (c) => `
      <tr>
        <td class="px-4 py-2.5 font-mono font-semibold text-blue-600">${c.serial_number}</td>
        <td class="px-4 py-2.5 font-semibold">${c.student_name}</td>
        <td class="px-4 py-2.5">${c.cert_type}</td>
        <td class="px-4 py-2.5">${c.title}</td>
        <td class="px-4 py-2.5 text-slate-500">${c.issued_by_name}</td>
        <td class="px-4 py-2.5 flex gap-2">
          <a href="${c.download_url}" target="_blank" class="px-2.5 py-1 rounded bg-slate-900 text-white text-[11px] font-semibold">Download PDF</a>
          <button onclick="quickVerifySerial('${c.serial_number}')" class="px-2.5 py-1 rounded border border-slate-300 text-[11px] font-medium">Verify</button>
        </td>
      </tr>
    `
    )
    .join('');
}

function openIssueCertModal() {
  openModal('modal-issue-cert');
}

async function submitIssueCertificate(e) {
  e.preventDefault();
  try {
    const res = await apiFetch('/api/certificates/issue', {
      method: 'POST',
      body: JSON.stringify({
        student_id: document.getElementById('cert-student').value,
        cert_type: document.getElementById('cert-type').value,
        title: document.getElementById('cert-title').value,
        citation: document.getElementById('cert-citation').value,
        verification_evidence: document.getElementById('cert-evidence').value,
      }),
    });
    closeModal('modal-issue-cert');
    showToast(`Issued ${res.serial_number}`);
    loadCertificates();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function generateStudentTranscript() {
  const studentId =
    currentUser.role === 'STUDENT'
      ? currentUser.id
      : document.getElementById('transcript-student-select').value || currentUser.id;
  try {
    const res = await apiFetch(`/api/transcripts/generate/${studentId}`, { method: 'POST' });
    showToast(`Transcript ${res.serial_number} generated`);
    loadCertificates();
    window.open(res.download_url, '_blank');
  } catch (err) {
    showToast(err.message, true);
  }
}

function quickVerifySerial(serial) {
  document.getElementById('verify-serial-input').value = serial;
  verifySerialNumber();
}

async function verifySerialNumber() {
  const serial = document.getElementById('verify-serial-input').value.trim();
  if (!serial) return;
  const box = document.getElementById('verify-serial-result');
  try {
    const res = await apiFetch(`/api/verify/${encodeURIComponent(serial)}`);
    if (res.verified) {
      box.innerHTML = `
        <div class="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 space-y-1">
          <div class="font-bold">✓ Authentic Verified Record (${res.serial_number})</div>
          <div>Recipient: <strong>${res.recipient.full_name}</strong> (${res.recipient.campus})</div>
          <div>Title: ${res.title}</div>
          <div>Evidence: ${res.verification_evidence}</div>
        </div>
      `;
    } else {
      box.innerHTML = `<div class="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-semibold">✗ ${res.message}</div>`;
    }
  } catch (err) {
    box.innerHTML = `<div class="text-rose-600">${err.message}</div>`;
  }
}

async function verifyUploadedPdf() {
  const fileInput = document.getElementById('verify-pdf-file');
  const box = document.getElementById('verify-pdf-result');
  if (!fileInput.files.length) {
    showToast('Select a PDF file first.', true);
    return;
  }
  const fd = new FormData();
  fd.append('file', fileInput.files[0]);
  try {
    const res = await apiFetch('/api/verify/pdf', { method: 'POST', body: fd });
    if (res.verified) {
      box.innerHTML = `
        <div class="p-3 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 space-y-1">
          <div class="font-bold">✓ Untampered Official PDF</div>
          <div>Serial: <strong>${res.serial_number}</strong> • Recipient: ${res.student_name}</div>
          <div>${res.title}</div>
        </div>
      `;
    } else {
      box.innerHTML = `<div class="p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-semibold">✗ ${res.message}</div>`;
    }
  } catch (err) {
    box.innerHTML = `<div class="text-rose-600">${err.message}</div>`;
  }
}

// ============================================================================
// TAB 7: Admin Command Center (Account Permissions, Approvals Inbox, Onboarding)
// ============================================================================

function populateBatchCertTargets() {
  const typeEl = document.getElementById('batch-cert-target-type');
  const targetEl = document.getElementById('batch-cert-target-id');
  if (!typeEl || !targetEl) return;

  if (typeEl.value === 'EVENT') {
    targetEl.innerHTML = eventsList.length
      ? eventsList.map((e) => `<option value="${e.id}">${e.title} (${e.code})</option>`).join('')
      : `<option value="">-- No Events Created --</option>`;
  } else {
    targetEl.innerHTML = clubsList.length
      ? clubsList.map((c) => `<option value="${c.id}">${c.name} (${c.code})</option>`).join('')
      : `<option value="">-- No Clubs Created --</option>`;
  }
}

async function loadAdminCenter() {
  await refreshUsersAndClubsSelectors();
  const [queue, sysStatus, auditLogs] = await Promise.all([
    apiFetch('/api/admin/pending-queue'),
    apiFetch('/api/system/status'),
    apiFetch('/api/audit-logs?limit=35'),
  ]);

  await refreshPendingBadge();

  if (sysStatus.configs) {
    document.getElementById('cfg-max-primary').value = sysStatus.configs.max_primary_clubs || '1';
    document.getElementById('cfg-max-secondary').value = sysStatus.configs.max_secondary_clubs || '1';
    document.getElementById('cfg-qr-seconds').value = sysStatus.configs.qr_rotation_seconds || '15';
    document.getElementById('cfg-geofence').value = sysStatus.configs.geofence_check_enabled || 'true';
  }

  // Render Database Provider Status
  const dbInfo = sysStatus.database || {};
  const badgeEl = document.getElementById('admin-db-provider-badge');
  const descEl = document.getElementById('admin-db-provider-desc');
  const iconEl = document.getElementById('admin-db-status-icon');
  const actionEl = document.getElementById('admin-db-action-container');
  if (badgeEl && descEl) {
    if (dbInfo.is_supabase_postgres) {
      badgeEl.className = 'px-2 py-0.5 rounded-full font-mono text-[11px] font-bold bg-emerald-100 text-emerald-800';
      badgeEl.textContent = 'Supabase Cloud PostgreSQL (Connected & Permanent)';
      descEl.textContent = 'All student registrations, passwords, and club records persist permanently across deployments.';
      if (iconEl) iconEl.className = 'w-8 h-8 rounded-xl flex items-center justify-center font-bold text-sm shrink-0 bg-emerald-100 text-emerald-700';
      if (actionEl) actionEl.innerHTML = `<span class="px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-700 font-semibold border border-emerald-200">✓ Cloud Database Online</span>`;
    } else if (dbInfo.is_ephemeral_vercel_sqlite) {
      badgeEl.className = 'px-2 py-0.5 rounded-full font-mono text-[11px] font-bold bg-rose-100 text-rose-800';
      badgeEl.textContent = 'Vercel Ephemeral /tmp SQLite (Supabase URL Missing)';
      descEl.innerHTML = '<strong class="text-rose-700">Warning:</strong> Running on temporary Vercel storage. Add <code class="bg-rose-50 px-1 py-0.5 rounded font-mono font-bold">SUPABASE_DB_URL</code> to your Vercel Environment Variables to permanently store all accounts.';
      if (iconEl) iconEl.className = 'w-8 h-8 rounded-xl flex items-center justify-center font-bold text-sm shrink-0 bg-rose-100 text-rose-700';
      if (actionEl) actionEl.innerHTML = `<button onclick="alert('To make your accounts permanent on Vercel:\n1. Copy the SUPABASE_DB_URL connection string from Supabase (Project Settings -> Database -> Connection string URI).\n2. Add it to Vercel (Project -> Settings -> Environment Variables -> SUPABASE_DB_URL).\n3. Redeploy your project.')" class="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-semibold">How to Connect Supabase</button>`;
    } else {
      badgeEl.className = 'px-2 py-0.5 rounded-full font-mono text-[11px] font-bold bg-slate-100 text-slate-800';
      badgeEl.textContent = 'Local SQLite Engine (data/msot_club_tracker.db)';
      descEl.textContent = 'Running locally on disk. To persist data when deployed on Vercel, connect your Supabase PostgreSQL database.';
      if (iconEl) iconEl.className = 'w-8 h-8 rounded-xl flex items-center justify-center font-bold text-sm shrink-0 bg-indigo-100 text-indigo-700';
      if (actionEl) actionEl.innerHTML = `<span class="text-slate-500 font-medium">Local Disk Storage Active</span>`;
    }
  }

  // 1. Render Unified Pending Queue (Starting with Pending Student Account Requests!)
  const qContainer = document.getElementById('admin-pending-queue-container');
  const cards = [];

  (queue.pending_accounts || []).forEach((u) => {
    cards.push(`
      <div class="p-3.5 rounded-xl bg-rose-50/80 border border-rose-200 flex items-center justify-between gap-2">
        <div>
          <span class="text-[10px] font-bold uppercase text-rose-700">Student Account Request (${u.campus_code})</span>
          <div class="font-bold text-slate-900">${u.full_name}</div>
          <div class="text-[11px] text-slate-600">${u.email} ${u.roll_number ? '• ' + u.roll_number : ''}</div>
        </div>
        <div class="flex gap-1 shrink-0">
          <button onclick="decideUserAccount('${u.id}', 'APPROVED')" class="px-2.5 py-1.5 rounded-lg btn-gradient-emerald text-white font-semibold text-[11px]">
            Permit
          </button>
          <button onclick="decideUserAccount('${u.id}', 'REJECTED')" class="px-2 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-semibold text-[11px]">
            Decline
          </button>
        </div>
      </div>
    `);
  });

  queue.pending_clubs.forEach((c) => {
    cards.push(`
      <div class="p-3.5 rounded-xl bg-amber-50/70 border border-amber-200 flex items-center justify-between gap-2">
        <div>
          <span class="text-[10px] font-bold uppercase text-amber-700">Pending Club</span>
          <div class="font-bold text-slate-900">${c.name} (${c.code})</div>
          <div class="text-[11px] text-slate-500">${c.campus_code} • ${c.category}</div>
        </div>
        <button onclick="toggleClubStatus('${c.id}', 'ACTIVE'); setTimeout(loadAdminCenter, 300);" class="px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white font-semibold text-[11px]">
          Activate
        </button>
      </div>
    `);
  });

  queue.pending_enrolments.forEach((m) => {
    cards.push(`
      <div class="p-3.5 rounded-xl bg-blue-50/60 border border-blue-200 flex items-center justify-between gap-2">
        <div>
          <span class="text-[10px] font-bold uppercase text-blue-700">Pending Enrolment (${m.tier})</span>
          <div class="font-bold text-slate-900">${m.student_name}</div>
          <div class="text-[11px] text-slate-500">Club: ${m.club_name}</div>
        </div>
        <button onclick="decideEnrolment('${m.id}', 'APPROVED'); setTimeout(loadAdminCenter, 300);" class="px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white font-semibold text-[11px]">
          Approve
        </button>
      </div>
    `);
  });

  queue.pending_sessions.forEach((s) => {
    cards.push(`
      <div class="p-3.5 rounded-xl bg-indigo-50/60 border border-indigo-200 flex items-center justify-between gap-2">
        <div>
          <span class="text-[10px] font-bold uppercase text-indigo-700">Pending Session Plan</span>
          <div class="font-bold text-slate-900">${s.topic}</div>
          <div class="text-[11px] text-slate-500">${s.club_name} • Week ${s.week_number} (${s.scheduled_date})</div>
        </div>
        <button onclick="approveSessionPlan('${s.id}', 'APPROVED'); setTimeout(loadAdminCenter, 300);" class="px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white font-semibold text-[11px]">
          Approve
        </button>
      </div>
    `);
  });

  queue.pending_budgets.forEach((b) => {
    cards.push(`
      <div class="p-3.5 rounded-xl bg-purple-50/60 border border-purple-200 flex items-center justify-between gap-2">
        <div>
          <span class="text-[10px] font-bold uppercase text-purple-700">Pending Budget (₹${b.amount_inr})</span>
          <div class="font-bold text-slate-900">${b.title}</div>
          <div class="text-[11px] text-slate-500">${b.club_name} • ${b.status}</div>
        </div>
        <button onclick="decideBudget('${b.id}', 'APPROVE'); setTimeout(loadAdminCenter, 300);" class="px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white font-semibold text-[11px]">
          Approve
        </button>
      </div>
    `);
  });

  queue.pending_duty_leaves.forEach((d) => {
    cards.push(`
      <div class="p-3.5 rounded-xl bg-teal-50/60 border border-teal-200 flex items-center justify-between gap-2">
        <div>
          <span class="text-[10px] font-bold uppercase text-teal-700">Pending Duty Leave</span>
          <div class="font-bold text-slate-900">${d.student_name}</div>
          <div class="text-[11px] text-slate-500">${d.event_title} (${d.leave_dates})</div>
        </div>
        <button onclick="decideDutyLeave('${d.id}', 'APPROVED'); setTimeout(loadAdminCenter, 300);" class="px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white font-semibold text-[11px]">
          Approve
        </button>
      </div>
    `);
  });

  qContainer.innerHTML = cards.length
    ? cards.join('')
    : `<div class="col-span-full py-6 text-center text-slate-400">All caught up! Zero pending account requests or approvals across all campuses.</div>`;

  // 2. Render User Directory with Account Access Status & Role Switcher
  document.getElementById('admin-users-count').textContent = `${allUsersList.length} Total User(s)`;
  const uTbody = document.getElementById('admin-users-tbody');
  uTbody.innerHTML = allUsersList
    .map((u) => {
      const statusBadge =
        u.account_status === 'APPROVED'
          ? `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700">PERMITTED</span>`
          : u.account_status === 'REJECTED'
          ? `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700">DECLINED</span>`
          : `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-100 text-amber-800">AWAITING ADMIN</span>`;

      const accessButtons =
        u.account_status !== 'APPROVED'
          ? `<button onclick="decideUserAccount('${u.id}', 'APPROVED')" class="px-2.5 py-1 rounded btn-gradient-emerald text-white text-[11px] font-semibold mr-1">Permit Access</button>`
          : u.id !== currentUser.id
          ? `<button onclick="decideUserAccount('${u.id}', 'REJECTED')" class="px-2 py-1 rounded border border-rose-200 text-rose-600 hover:bg-rose-50 text-[11px] font-medium mr-1">Revoke</button>`
          : '';

      return `
        <tr>
          <td class="px-4 py-2.5">
            <div class="font-semibold text-slate-900">${u.full_name}</div>
            <div class="text-[11px] text-slate-500">${u.email}</div>
          </td>
          <td class="px-4 py-2.5 font-mono text-slate-600">${u.roll_number || '—'}</td>
          <td class="px-4 py-2.5">${u.campus_code}</td>
          <td class="px-4 py-2.5">${statusBadge}</td>
          <td class="px-4 py-2.5">
            <select onchange="updateUserRole('${u.id}', this.value)" class="rounded border border-slate-300 bg-white px-2 py-1 text-xs">
              <option value="STUDENT" ${u.role === 'STUDENT' ? 'selected' : ''}>STUDENT</option>
              <option value="PRESIDENT" ${u.role === 'PRESIDENT' || u.role === 'COORDINATOR' ? 'selected' : ''}>PRESIDENT</option>
              <option value="ADVISOR" ${u.role === 'ADVISOR' ? 'selected' : ''}>ADVISOR</option>
              <option value="CAMPUS_MGR" ${u.role === 'CAMPUS_MGR' ? 'selected' : ''}>CAMPUS_MGR</option>
              <option value="ADMIN" ${u.role === 'ADMIN' ? 'selected' : ''}>ADMIN</option>
            </select>
          </td>
          <td class="px-4 py-2.5">${accessButtons}</td>
        </tr>
      `;
    })
    .join('');

  // 3. Render Audit Logs
  const aTbody = document.getElementById('admin-audit-tbody');
  aTbody.innerHTML = auditLogs.length
    ? auditLogs
        .map(
          (l) => `
          <tr>
            <td class="px-4 py-2 text-[11px] text-slate-400 whitespace-nowrap">${l.created_at ? l.created_at.slice(0, 19).replace('T', ' ') : ''}</td>
            <td class="px-4 py-2 font-semibold text-slate-700">${l.actor_name}</td>
            <td class="px-4 py-2"><span class="px-2 py-0.5 rounded bg-slate-100 font-mono text-[11px]">${l.action}</span></td>
            <td class="px-4 py-2 text-slate-600">${l.details}</td>
          </tr>
        `
        )
        .join('')
    : `<tr><td colspan="4" class="px-4 py-5 text-center text-slate-400">No audit events recorded yet.</td></tr>`;
}

async function submitAdminCreateUser(e) {
  e.preventDefault();
  try {
    const res = await apiFetch('/api/admin/users/create', {
      method: 'POST',
      body: JSON.stringify({
        full_name: document.getElementById('adm-user-name').value.trim(),
        email: document.getElementById('adm-user-email').value.trim(),
        password: document.getElementById('adm-user-password').value,
        role: document.getElementById('adm-user-role').value,
        campus_id: document.getElementById('adm-user-campus').value,
        roll_number: document.getElementById('adm-user-roll').value.trim() || null,
        track: document.getElementById('adm-user-track').value,
      }),
    });
    closeModal('modal-admin-add-user');
    document.getElementById('adm-user-name').value = '';
    document.getElementById('adm-user-email').value = '';
    document.getElementById('adm-user-roll').value = '';
    showToast(res.message);
    loadAdminCenter();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function decideUserAccount(userId, accountStatus) {
  try {
    const updated = await apiFetch(`/api/admin/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify({ account_status: accountStatus }),
    });
    showToast(
      accountStatus === 'APPROVED'
        ? `Permitted account for ${updated.full_name}`
        : `Revoked/declined account for ${updated.full_name}`
    );
    await refreshPendingBadge();
    const adminTab = document.getElementById('tab-admin');
    if (adminTab && !adminTab.classList.contains('hidden')) {
      await loadAdminCenter();
    }
    const dashTab = document.getElementById('tab-dashboard');
    if (dashTab && !dashTab.classList.contains('hidden')) {
      await loadDashboard();
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

async function bulkApproveCategory(category) {
  try {
    const res = await apiFetch(`/api/admin/approve-all?category=${category}`, { method: 'POST' });
    showToast(res.message);
    loadAdminCenter();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function updateUserRole(userId, newRole) {
  try {
    const updated = await apiFetch(`/api/admin/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify({ role: newRole }),
    });
    showToast(`Updated ${updated.full_name} to ${updated.role}`);
    if (currentUser && userId === currentUser.id) {
      currentUser.role = updated.role;
      document.getElementById('nav-role-badge').textContent = currentUser.role;
      applyRoleVisibility();
    }
    loadAdminCenter();
  } catch (err) {
    showToast(err.message, true);
  }
}

function fillSampleCsvUsers() {
  document.getElementById('bulk-users-csv').value = [
    'Dr. Meera Krishnan, meera.advisor@college.edu, ADVISOR, HI-Tech, FAC-HT-01, pass123',
    'Rohan Verma, rohan.coord@college.edu, COORDINATOR, HI-Tech, MSOT-HT-2501, pass123',
    'Ananya Reddy, ananya@college.edu, STUDENT, HI-Tech, MSOT-HT-2502, pass123',
    'Karthik Nair, karthik@college.edu, STUDENT, Ratnam, MSOT-RT-2503, pass123',
  ].join('\n');
}

async function submitBulkUserOnboarding() {
  const csvText = document.getElementById('bulk-users-csv').value.trim();
  if (!csvText) {
    showToast('Paste CSV user lines or click Fill Sample Template first.', true);
    return;
  }
  try {
    const res = await apiFetch('/api/admin/users/bulk', {
      method: 'POST',
      body: JSON.stringify({ csv_text: csvText }),
    });
    document.getElementById('bulk-users-csv').value = '';
    showToast(res.message);
    loadAdminCenter();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function submitSystemConfig(e) {
  e.preventDefault();
  try {
    const res = await apiFetch('/api/admin/config', {
      method: 'PUT',
      body: JSON.stringify({
        max_primary_clubs: document.getElementById('cfg-max-primary').value,
        max_secondary_clubs: document.getElementById('cfg-max-secondary').value,
        qr_rotation_seconds: document.getElementById('cfg-qr-seconds').value,
        geofence_check_enabled: document.getElementById('cfg-geofence').value,
      }),
    });
    showToast(res.message);
    loadAdminCenter();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function submitUpsertCampus(e) {
  e.preventDefault();
  try {
    const res = await apiFetch('/api/admin/campuses', {
      method: 'POST',
      body: JSON.stringify({
        code: document.getElementById('camp-code').value,
        city: document.getElementById('camp-city').value,
        name: document.getElementById('camp-name').value,
        lat: parseFloat(document.getElementById('camp-lat').value),
        lng: parseFloat(document.getElementById('camp-lng').value),
        geofence_radius_m: parseFloat(document.getElementById('camp-radius').value),
      }),
    });
    closeModal('modal-upsert-campus');
    showToast(res.message);
    await loadCampuses();
    loadAdminCenter();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function submitBatchCertificates(e) {
  e.preventDefault();
  const targetId = document.getElementById('batch-cert-target-id').value;
  if (!targetId) {
    showToast('Select a valid Club or Event first.', true);
    return;
  }
  try {
    const res = await apiFetch('/api/admin/certificates/batch', {
      method: 'POST',
      body: JSON.stringify({
        target_type: document.getElementById('batch-cert-target-type').value,
        target_id: targetId,
        cert_type: 'PARTICIPATION',
        title: document.getElementById('batch-cert-title').value,
        citation: document.getElementById('batch-cert-citation').value,
      }),
    });
    showToast(res.message);
    loadAdminCenter();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// TAB: Club News & Announcements
// ============================================================================

async function loadClubNews() {
  const container = document.getElementById('club-news-feed');
  const subtitle = document.getElementById('news-tab-subtitle');
  if (!container) return;

  // Populate news club selector for posting
  const newsClubSelect = document.getElementById('news-club-id');
  if (newsClubSelect) {
    let allowedClubs = clubsList;
    if (currentUser.role === 'STUDENT' || currentUser.role === 'PRESIDENT' || currentUser.role === 'COORDINATOR') {
      // Filter to clubs user belongs to
      allowedClubs = clubsList.filter((c) => c.my_membership && c.my_membership.status === 'APPROVED');
    }
    newsClubSelect.innerHTML = allowedClubs.length
      ? allowedClubs.map((c) => `<option value="${c.id}">${c.name} (${c.code})</option>`).join('')
      : `<option value="">-- No Approved Club --</option>`;
  }

  if (subtitle) {
    if (currentUser.role === 'STUDENT') {
      subtitle.textContent = 'Showing official news and announcements exclusively for your enrolled club(s).';
    } else if (currentUser.role === 'PRESIDENT') {
      subtitle.textContent = 'Showing news for your club. You can broadcast announcements directly to all members.';
    } else {
      subtitle.textContent = 'Official updates across campus clubs. Campus Managers and Presidents can post news.';
    }
  }

  try {
    const items = await apiFetch('/api/club-news');
    if (!items.length) {
      container.innerHTML = `
        <div class="col-span-full bg-white rounded-2xl border border-slate-200 p-8 text-center text-slate-500 text-sm">
          <p class="font-semibold text-slate-700">No announcements posted yet.</p>
          <p class="text-xs text-slate-400 mt-1">
            ${currentUser.role === 'STUDENT' ? 'Once your Campus Manager or Club President posts news for your club, it will appear here.' : 'Click "+ Post Club Announcement" to broadcast news to club members.'}
          </p>
        </div>
      `;
      return;
    }

    container.innerHTML = items
      .map((n) => {
        const canDelete =
          ['ADMIN', 'CAMPUS_MGR'].includes(currentUser.role) || n.author_id === currentUser.id;
        const deleteBtn = canDelete
          ? `<button onclick="deleteClubNews('${n.id}')" class="text-xs text-rose-500 hover:text-rose-700">Delete</button>`
          : '';

        const pinBadge = n.pinned
          ? `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-200">PINNED</span>`
          : '';

        const dateStr = n.created_at ? n.created_at.slice(0, 10) : '';

        return `
          <div class="glass-card rounded-2xl p-5 flex flex-col justify-between space-y-3 relative ${n.pinned ? 'border-amber-300' : ''}">
            <div class="space-y-2">
              <div class="flex items-center justify-between gap-2">
                <span class="text-xs font-bold text-indigo-600 truncate">${n.club_name} (${n.club_code})</span>
                <div class="flex items-center gap-1.5 shrink-0">
                  ${pinBadge}
                  <span class="text-[11px] text-slate-400">${dateStr}</span>
                </div>
              </div>
              <h3 class="text-sm font-bold text-slate-900 leading-snug">${n.title}</h3>
              <p class="text-xs text-slate-600 whitespace-pre-line leading-relaxed">${n.content}</p>
            </div>
            <div class="pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
              <span>Posted by <strong>${n.author_name}</strong></span>
              ${deleteBtn}
            </div>
          </div>
        `;
      })
      .join('');
  } catch (err) {
    container.innerHTML = `<div class="col-span-full p-4 rounded-xl bg-rose-50 text-rose-700 text-xs">${err.message}</div>`;
  }
}

async function submitClubNews(e) {
  e.preventDefault();
  const clubId = document.getElementById('news-club-id').value;
  if (!clubId) {
    showToast('Select a club first.', true);
    return;
  }
  try {
    const res = await apiFetch('/api/club-news', {
      method: 'POST',
      body: JSON.stringify({
        club_id: clubId,
        title: document.getElementById('news-title').value.trim(),
        content: document.getElementById('news-content').value.trim(),
        pinned: document.getElementById('news-pinned').checked,
      }),
    });
    closeModal('modal-create-news');
    document.getElementById('news-title').value = '';
    document.getElementById('news-content').value = '';
    document.getElementById('news-pinned').checked = false;
    showToast(res.message);
    loadClubNews();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function deleteClubNews(newsId) {
  if (!confirm('Are you sure you want to delete this news post?')) return;
  try {
    const res = await apiFetch(`/api/club-news/${newsId}`, { method: 'DELETE' });
    showToast(res.message);
    loadClubNews();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ============================================================================
// Initialize Application on Page Load
// ============================================================================

window.addEventListener('DOMContentLoaded', async () => {
  await loadCampuses();
  if (authToken) {
    try {
      currentUser = await apiFetch('/api/auth/me');
      await enterApp();
    } catch (_) {
      handleLogout();
    }
  } else {
    showHeroScreen();
  }
});
