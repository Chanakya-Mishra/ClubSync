let authToken = sessionStorage.getItem('clubsync_token') || localStorage.getItem('clubsync_token') || '';
let currentUser = null;
let campusesList = [];
let allUsersList = [];
let clubsList = [];
let eventsList = [];
let activeSessionIdForDetail = null;
let qrIntervalTimer = null;
let currentLiveQrPayload = null;

// ============================================================================
// SWR (Stale-While-Revalidate) Instant Cache Engine
// ============================================================================
const SWR_PREFIX = 'clubsync_swr_';

function getSwr(key) {
  try {
    const raw = localStorage.getItem(SWR_PREFIX + key);
    if (!raw) return null;
    const item = JSON.parse(raw);
    return item ? item.data : null;
  } catch (_) {
    return null;
  }
}

function setSwr(key, data) {
  try {
    localStorage.setItem(SWR_PREFIX + key, JSON.stringify({ data, ts: Date.now() }));
  } catch (_) {}
}

function clearSwr(key) {
  try {
    if (key) {
      localStorage.removeItem(SWR_PREFIX + key);
    } else {
      Object.keys(localStorage).forEach((k) => {
        if (k.startsWith(SWR_PREFIX)) localStorage.removeItem(k);
      });
    }
  } catch (_) {}
}

/**
 * High-performance SWR fetcher:
 * 1. If cached data exists in localStorage, fires onData(cachedData, true) in 0ms.
 * 2. Asynchronously fetches latest data from the API in background.
 * 3. If fresh data differs from cache, updates cache and re-fires onData(freshData, false).
 */
async function swrFetch(key, path, options = {}, onData = null) {
  const cached = getSwr(key);
  if (cached !== null && onData) {
    onData(cached, true);
  }

  try {
    const freshData = await apiFetch(path, options);
    const freshStr = JSON.stringify(freshData);
    const cachedStr = cached !== null ? JSON.stringify(cached) : null;
    setSwr(key, freshData);
    if (onData && freshStr !== cachedStr) {
      onData(freshData, false);
    }
    return freshData;
  } catch (err) {
    if (cached !== null) {
      return cached;
    }
    throw err;
  }
}

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
  const passInput = document.getElementById('login-password');
  if (passInput) passInput.value = '';
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
  const input = document.getElementById('hero-verify-serial-input');
  if (!input) return;
  const serial = input.value.trim();
  if (!serial) return;
  const box = document.getElementById('hero-verify-result');
  if (!box) return;
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
  const forgotForm = document.getElementById('forgot-form');
  const tabLogin = document.getElementById('auth-tab-login');
  const tabReg = document.getElementById('auth-tab-register');
  document.getElementById('auth-error').classList.add('hidden');
  document.getElementById('auth-success').classList.add('hidden');

  if (mode === 'login') {
    loginForm.classList.remove('hidden');
    regForm.classList.add('hidden');
    if (forgotForm) forgotForm.classList.add('hidden');
    tabLogin.className = 'py-2 rounded-md bg-white text-slate-900 shadow-sm';
    tabReg.className = 'py-2 rounded-md text-slate-600 hover:text-slate-900';
  } else if (mode === 'register') {
    loginForm.classList.add('hidden');
    regForm.classList.remove('hidden');
    if (forgotForm) forgotForm.classList.add('hidden');
    tabReg.className = 'py-2 rounded-md bg-white text-slate-900 shadow-sm';
    tabLogin.className = 'py-2 rounded-md text-slate-600 hover:text-slate-900';
    updateRegRoleNotice();
  } else if (mode === 'forgot') {
    loginForm.classList.add('hidden');
    regForm.classList.add('hidden');
    if (forgotForm) {
      forgotForm.classList.remove('hidden');
      document.getElementById('forgot-step-1')?.classList.remove('hidden');
      document.getElementById('forgot-step-2')?.classList.add('hidden');
      const loginEmail = document.getElementById('login-email')?.value.trim();
      const forgotEmailInput = document.getElementById('forgot-email');
      if (loginEmail && forgotEmailInput && !forgotEmailInput.value) {
        forgotEmailInput.value = loginEmail;
      }
    }
    tabLogin.className = 'py-2 rounded-md text-slate-600 hover:text-slate-900';
    tabReg.className = 'py-2 rounded-md text-slate-600 hover:text-slate-900';
  }
}

function updateRegRoleNotice() {
  const role = document.getElementById('reg-role')?.value || 'STUDENT';
  const notice = document.getElementById('reg-approval-notice');
  const btn = document.getElementById('reg-submit-btn');
  if (!notice || !btn) return;
  const roleLabels = {
    STUDENT: 'Student',
    PRESIDENT: 'Club President',
    ADVISOR: 'Faculty Advisor',
    CAMPUS_MGR: 'Campus Manager',
    ADMIN: 'System Admin',
  };
  const label = roleLabels[role] || role;
  notice.classList.remove('hidden');
  notice.innerHTML = `<strong>Campus Manager Approval Required:</strong> All <em>${label}</em> accounts must be reviewed and permitted by your Campus Manager before you can sign in.`;
  btn.textContent = `Submit ${label} Account Request`;
}

async function handleSendResetOtp() {
  const emailInput = document.getElementById('forgot-email');
  const email = emailInput ? emailInput.value.trim() : '';
  if (!email) {
    showAuthError('Please enter your email address to receive the verification OTP.');
    return;
  }
  const btn = document.getElementById('forgot-send-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Sending Code...';
  }
  try {
    const res = await apiFetch('/api/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
    showAuthSuccess(res.message || 'Verification code sent! Check your inbox.');
    document.getElementById('forgot-step-1')?.classList.add('hidden');
    document.getElementById('forgot-step-2')?.classList.remove('hidden');
    const otpInput = document.getElementById('forgot-otp');
    if (otpInput) {
      otpInput.value = '';
      otpInput.focus();
    }
  } catch (err) {
    showAuthError(err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Send 6-Digit Code';
    }
  }
}

async function handleResendResetOtp() {
  document.getElementById('forgot-step-2')?.classList.add('hidden');
  document.getElementById('forgot-step-1')?.classList.remove('hidden');
  await handleSendResetOtp();
}

async function handleCompleteReset() {
  const email = document.getElementById('forgot-email')?.value.trim();
  const otp = document.getElementById('forgot-otp')?.value.trim();
  const newPassword = document.getElementById('forgot-new-password')?.value;
  const confirmPassword = document.getElementById('forgot-confirm-password')?.value;

  if (!otp || otp.length < 6) {
    showAuthError('Please enter the 6-digit verification code sent to your email.');
    return;
  }
  if (!newPassword || newPassword.length < 4) {
    showAuthError('New password must be at least 4 characters.');
    return;
  }
  if (newPassword !== confirmPassword) {
    showAuthError('Passwords do not match. Please re-enter.');
    return;
  }

  const btn = document.getElementById('forgot-reset-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Resetting Password...';
  }

  try {
    const res = await apiFetch('/api/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({
        email,
        otp,
        new_password: newPassword,
      }),
    });
    switchAuthMode('login');
    const loginEmailInput = document.getElementById('login-email');
    if (loginEmailInput) loginEmailInput.value = email;
    showAuthSuccess(res.message || 'Password reset successfully! You can now sign in.');
  } catch (err) {
    showAuthError(err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Reset Password & Sign In';
    }
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

function formatCampusLabel(c) {
  const codeLower = (c.code || '').toLowerCase();
  if (codeLower.includes('hi-tech') || codeLower.includes('hitech')) {
    return c.code;
  }
  if (codeLower.includes('rathinam')) {
    return c.code;
  }
  if (c.city) {
    return `${c.code} (${c.city})`;
  }
  return c.code;
}

function populateCampusSelects(list) {
  if (!list || !list.length) return;
  const selects = ['reg-campus', 'club-campus', 'adm-user-campus'];
  selects.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.innerHTML = list
        .map((c) => `<option value="${c.id}">${formatCampusLabel(c)}</option>`)
        .join('');
    }
  });
  const filterSelects = ['dash-campus-filter', 'clubs-campus-filter'];
  filterSelects.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.innerHTML =
        `<option value="">All Campuses</option>` +
        list.map((c) => `<option value="${c.id}">${c.code}</option>`).join('');
    }
  });
}

async function loadCampuses() {
  const cached = getSwr('campuses');
  if (cached && cached.length) {
    campusesList = cached;
    populateCampusSelects(campusesList);
  }
  return swrFetch('campuses', '/api/campuses', {}, (fresh) => {
    campusesList = fresh;
    populateCampusSelects(campusesList);
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
    sessionStorage.setItem('clubsync_token', authToken);
    localStorage.setItem('clubsync_token', authToken);
    currentUser = data.user;
    setSwr('currentUser', currentUser);
    // Clear password input immediately after successful authentication
    const passInput = document.getElementById('login-password');
    if (passInput) passInput.value = '';
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
      track: document.getElementById('reg-track')?.value || 'Mirai Track',
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
    sessionStorage.setItem('clubsync_token', authToken);
    localStorage.setItem('clubsync_token', authToken);
    currentUser = data.user;
    setSwr('currentUser', currentUser);
    await enterApp();
  } catch (err) {
    showAuthError(err.message);
  }
}

function handleLogout() {
  authToken = '';
  currentUser = null;
  sessionStorage.removeItem('clubsync_token');
  localStorage.removeItem('clubsync_token');
  clearSwr();

  // Clear all login input fields so browser does not retain or auto-submit
  const emailInput = document.getElementById('login-email');
  const passInput = document.getElementById('login-password');
  if (emailInput) emailInput.value = '';
  if (passInput) passInput.value = '';

  showHeroScreen();
  showToast('Signed out successfully.');
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

  // 5. Sessions Tab: Hide "+ Plan Club Day Session" & Quick QR from regular Students
  document.getElementById('btn-plan-session')?.classList.toggle('hidden', isStudent);
  document.getElementById('btn-quick-qr')?.classList.toggle('hidden', isStudent);

  // 6. Events Tab: Hide "+ Create Event" from Students/Coordinators/Advisors
  document.getElementById('btn-create-event')?.classList.toggle('hidden', !isAdminOrMgr);

  // 7. Certificates Tab: Hide "+ Issue New Certificate" and all-student selector from Students
  document.getElementById('btn-issue-cert')?.classList.toggle('hidden', isStudent);
  document.getElementById('admin-transcript-selector')?.classList.toggle('hidden', isStudent);

  // 8. Club News Tab: Show "+ Post Club Announcement" for Club Presidents, Campus Managers, Admins, Advisors
  const canPostNews = ['PRESIDENT', 'COORDINATOR', 'CAMPUS_MGR', 'ADMIN', 'ADVISOR'].includes(role);
  document.getElementById('btn-post-news')?.classList.toggle('hidden', !canPostNews);

  // 9. Attendance Tab: Dedicated only for Club Presidents and Leadership
  const isPresident = ['PRESIDENT', 'COORDINATOR', 'CAMPUS_MGR', 'ADMIN'].includes(role);
  document.getElementById('tab-btn-attendance')?.classList.toggle('hidden', !isPresident);
}

async function enterApp() {
  document.getElementById('hero-screen').classList.add('hidden');
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app-screen').classList.remove('hidden');

  document.getElementById('nav-user-name').textContent = currentUser.full_name;
  document.getElementById('nav-user-meta').textContent = `${currentUser.email} • ${currentUser.campus_code}`;
  document.getElementById('nav-role-badge').textContent = currentUser.role;

  applyRoleVisibility();
  switchTab('dashboard'); // Instant view transition in 0ms!
  // Run background updates asynchronously without blocking user view
  refreshUsersAndClubsSelectors();
  refreshPendingBadge();
}

let _selectorsCacheTime = 0;
async function refreshUsersAndClubsSelectors(force = false) {
  const now = Date.now();
  if (!force && allUsersList.length > 0 && (now - _selectorsCacheTime < 60000)) {
    return;
  }
  const [users, clubs, events] = await Promise.all([
    apiFetch('/api/users'),
    apiFetch('/api/clubs'),
    apiFetch('/api/events'),
  ]);
  allUsersList = users;
  clubsList = clubs;
  eventsList = events;
  _selectorsCacheTime = now;

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

let cachedPendingQueue = null;
let cachedPendingQueueTime = 0;
async function fetchPendingQueue(force = false) {
  const now = Date.now();
  if (!force && cachedPendingQueue && (now - cachedPendingQueueTime < 25000)) {
    return cachedPendingQueue;
  }
  cachedPendingQueue = await apiFetch('/api/admin/pending-queue');
  cachedPendingQueueTime = now;
  return cachedPendingQueue;
}

async function refreshPendingBadge(force = false) {
  if (!currentUser || !['ADMIN', 'CAMPUS_MGR', 'ADVISOR'].includes(currentUser.role)) return;
  try {
    const q = await fetchPendingQueue(force);
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
  if (tabName === 'attendance' && currentUser && !['PRESIDENT', 'COORDINATOR', 'CAMPUS_MGR', 'ADMIN'].includes(currentUser.role)) {
    tabName = 'dashboard';
  }
  const tabs = ['dashboard', 'clubs', 'sessions', 'events', 'stretch', 'certificates', 'news', 'admin', 'attendance'];
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
  if (tabName === 'attendance') loadPresidentAttendance();
}

// ============================================================================
// TAB 1: Dashboard & Reports
// ============================================================================

function renderDashboardOverview(data) {
  if (!data) return;

  // 1. Personal Attendance Card (for all accounts)
  if (data.my_attendance) {
    const ma = data.my_attendance;
    const pctEl = document.getElementById('dash-my-att-pct');
    if (pctEl) pctEl.textContent = `${ma.attendance_percentage}%`;
    const countEl = document.getElementById('dash-my-att-count');
    if (countEl) countEl.textContent = `${ma.attended_sessions} of ${ma.total_sessions} sessions attended`;
    const presEl = document.getElementById('dash-my-att-present');
    if (presEl) presEl.textContent = ma.present_count;
    const lateEl = document.getElementById('dash-my-att-late');
    if (lateEl) lateEl.textContent = ma.late_count;
    const barEl = document.getElementById('dash-my-att-bar');
    if (barEl) barEl.style.width = `${Math.min(100, Math.max(0, ma.attendance_percentage))}%`;

    const standingEl = document.getElementById('dash-my-att-standing');
    if (standingEl) {
      if (ma.standing === 'EXCELLENT') {
        standingEl.className = 'px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-blue-50 text-blue-700 border border-blue-200';
        standingEl.textContent = 'Excellent (90%+)';
      } else if (ma.standing === 'GOOD_STANDING') {
        standingEl.className = 'px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200';
        standingEl.textContent = 'Good Standing';
      } else {
        standingEl.className = 'px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-rose-50 text-rose-700 border border-rose-200';
        standingEl.textContent = 'Attendance Warning';
      }
    }
  }

  // 2. President Club Attendance Card (visible to Presidents / Coordinators / Leadership)
  const presCard = document.getElementById('dash-president-attendance-card');
  if (presCard) {
    const ps = data.president_club_summary;
    const isLeadership = currentUser && ['PRESIDENT', 'COORDINATOR', 'CAMPUS_MGR', 'ADMIN'].includes(currentUser.role);
    if (ps && isLeadership) {
      presCard.classList.remove('hidden');
      const titleEl = document.getElementById('dash-pres-club-title');
      if (titleEl) titleEl.textContent = `${ps.club_name} (${ps.club_code})`;
      const metaEl = document.getElementById('dash-pres-club-meta');
      if (metaEl) metaEl.textContent = `President Attendance Dashboard • ${ps.total_members} Members`;
      const pctEl = document.getElementById('dash-pres-club-pct');
      if (pctEl) pctEl.textContent = `${ps.overall_attendance_pct}%`;
      const memEl = document.getElementById('dash-pres-club-members');
      if (memEl) memEl.textContent = ps.total_members;
      const sessEl = document.getElementById('dash-pres-club-sessions');
      if (sessEl) sessEl.textContent = ps.total_sessions;
      const checkinEl = document.getElementById('dash-pres-club-checkins');
      if (checkinEl) checkinEl.textContent = ps.verified_checkins;
    } else {
      presCard.classList.add('hidden');
    }
  }

  const cardsEl = document.getElementById('dash-campus-cards');
  if (cardsEl && data.campus_breakdown) {
    cardsEl.innerHTML = data.campus_breakdown
      .map(
        (c) => `
        <div class="glass-subcard rounded-xl p-4 space-y-2">
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
  }

  const tbody = document.getElementById('dash-monthly-tbody');
  if (tbody && data.monthly_club_reports) {
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
  }

  const topEl = document.getElementById('dash-top-students');
  if (topEl && data.top_contributors) {
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
  }

  const alertsEl = document.getElementById('dash-alerts');
  if (alertsEl && data.inactive_clubs && data.zero_participation_students) {
    const inactiveHtml = data.inactive_clubs.map(
      (c) => `<div class="p-2.5 rounded-lg bg-amber-50 text-amber-800">Club <strong>${c.name}</strong> (${c.campus_code}): ${c.reason}</div>`
    );
    const zeroHtml = data.zero_participation_students
      .slice(0, 8)
      .map((s) => `<div class="p-2.5 rounded-lg bg-slate-100 text-slate-700">Student <strong>${s.full_name}</strong> (${s.campus_code}): 0 sessions & 0 events</div>`);
    alertsEl.innerHTML = [...inactiveHtml, ...zeroHtml].join('') || `<p class="text-slate-400">No inactive clubs or zero-participation alerts.</p>`;
  }
}

async function refreshDashboardPendingBanner() {
  const banner = document.getElementById('dash-pending-students-banner');
  const countEl = document.getElementById('dash-pending-count');
  const listEl = document.getElementById('dash-pending-students-list');
  if (banner && currentUser && (currentUser.role === 'CAMPUS_MGR' || currentUser.role === 'ADMIN')) {
    try {
      const queue = await fetchPendingQueue();
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
                <button onclick="decideUserAccount('${u.id}', 'REJECTED')" class="px-2 py-1 rounded-lg border border-amber-300 text-amber-800 hover:bg-amber-50 text-[11px] font-semibold">
                  Decline
                </button>
                <button onclick="handleDeleteUser('${u.id}', '${(u.full_name || '').replace(/'/g, "\\'")}', '${u.role || 'User'}')" class="px-2 py-1 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-[11px] font-semibold" title="Permanently remove account">
                  Remove
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

async function loadDashboard() {
  const campusId = document.getElementById('dash-campus-filter')?.value || '';
  const cacheKey = `dash_overview_${campusId || 'all'}`;
  const url = `/api/dashboard/overview${campusId ? `?campus_id=${campusId}` : ''}`;

  swrFetch(cacheKey, url, {}, (data) => {
    renderDashboardOverview(data);
  });

  refreshDashboardPendingBanner();
}

// ============================================================================
// TAB 2: Clubs & Enrolment
// ============================================================================

function renderClubsGrid(list) {
  const grid = document.getElementById('clubs-grid');
  if (!grid) return;
  if (!list || !list.length) {
    grid.innerHTML = `<div class="col-span-full glass-card rounded-2xl p-8 text-center text-slate-500 text-sm">No clubs available yet.</div>`;
    return;
  }

  const canManageClub = currentUser && (currentUser.role === 'ADMIN' || currentUser.role === 'CAMPUS_MGR' || currentUser.role === 'ADVISOR');
  const studentOptions = allUsersList
    .filter((u) => u.account_status === 'APPROVED')
    .map((u) => `<option value="${u.id}">${u.full_name} (${u.role})</option>`)
    .join('');

  grid.innerHTML = list
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
        <div class="glass-card rounded-2xl p-5 flex flex-col justify-between space-y-3">
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

async function loadClubs() {
  const campusId = document.getElementById('clubs-campus-filter')?.value || '';
  const cacheKey = `clubs_list_${campusId || 'all'}`;
  const url = `/api/clubs${campusId ? `?campus_id=${campusId}` : ''}`;

  swrFetch(cacheKey, url, {}, (list) => {
    clubsList = list;
    renderClubsGrid(clubsList);
  });
  refreshUsersAndClubsSelectors();
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

function renderSessionsList(sessions) {
  const container = document.getElementById('sessions-list');
  if (!container) return;
  const isStaffOrCoord = currentUser && currentUser.role !== 'STUDENT';
  const isAdvisorOrAdmin = currentUser && ['ADVISOR', 'CAMPUS_MGR', 'ADMIN'].includes(currentUser.role);

  if (!sessions || !sessions.length) {
    container.innerHTML = `
      <div class="glass-card rounded-2xl p-8 text-center space-y-3">
        <div class="w-12 h-12 mx-auto rounded-2xl bg-indigo-50 border border-indigo-200 flex items-center justify-center text-xl">📅</div>
        <p class="font-bold text-slate-800 text-sm">No Club Day sessions scheduled yet.</p>
        <p class="text-xs text-slate-500 max-w-sm mx-auto">Launch an active session to generate live rotating QR codes and track attendance.</p>
        ${
          isStaffOrCoord
            ? `<button onclick="quickStartSessionAndQr()" class="px-4 py-2 rounded-xl btn-gradient-emerald text-white text-xs font-bold inline-flex items-center gap-1.5 shadow-sm">
                <span>⚡ Instant Live Session & Rotating QR</span>
              </button>`
            : ''
        }
      </div>
    `;
    return;
  }

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
          ? `<button onclick="announceSession('${s.id}')" class="px-3 py-1.5 rounded-lg border border-blue-300 bg-blue-50 text-blue-700 text-xs font-semibold">Announce</button>`
          : '';

      const isWindowOpen = s.checkin_status === 'OPEN';
      let checkinActionButtons = '';

      if (isStaffOrCoord) {
        if (isWindowOpen) {
          checkinActionButtons = `
            <button onclick="openCheckinModal('${s.id}')" class="px-3.5 py-1.5 rounded-lg btn-gradient text-white text-xs font-bold flex items-center gap-1.5 shadow-sm">
              <span>⛶ Show Live Rotating QR</span>
            </button>
            <button onclick="toggleCheckinWindow('${s.id}', 'CLOSE')" class="px-2.5 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold">
              Close Window
            </button>
          `;
        } else {
          checkinActionButtons = `
            <button onclick="toggleCheckinWindowAndQr('${s.id}')" class="px-3 py-1.5 rounded-lg btn-gradient-emerald text-white text-xs font-bold flex items-center gap-1.5 shadow-sm">
              <span>⚡ Open & Launch Live QR</span>
            </button>
            <button onclick="openCheckinModal('${s.id}')" class="px-2.5 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-medium">
              Preview QR
            </button>
          `;
        }
      } else {
        // Regular Student
        if (isWindowOpen) {
          checkinActionButtons = `
            <button onclick="openCheckinModal('${s.id}')" class="px-3.5 py-1.5 rounded-lg btn-gradient text-white text-xs font-bold flex items-center gap-1.5">
              <span>⚡ Check In to Session</span>
            </button>
          `;
        } else {
          checkinActionButtons = `
            <span class="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-500 text-xs font-medium">Check-In Closed</span>
          `;
        }
      }

      const manageRosterBtn = isStaffOrCoord
        ? `<button onclick="openSessionDetail('${s.id}')" class="px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs font-semibold">
            Manage Roster & Grade
          </button>`
        : '';

      return `
        <div class="glass-card rounded-2xl p-5 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
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
            ${checkinActionButtons}
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

async function loadSessions() {
  swrFetch('sessions_list', '/api/sessions', {}, (sessions) => {
    renderSessionsList(sessions);
  });
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
      body: JSON.stringify({ action, duration_minutes: 60, late_after_minutes: 15 }),
    });
    showToast(`Check-in window ${action === 'OPEN' ? 'opened' : 'closed'}`);
    loadSessions();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function toggleCheckinWindowAndQr(sessionId) {
  try {
    await apiFetch(`/api/sessions/${sessionId}/checkin-window`, {
      method: 'POST',
      body: JSON.stringify({ action: 'OPEN', duration_minutes: 60, late_after_minutes: 15 }),
    });
    showToast('Check-in window opened! Rotating QR is live.');
    loadSessions();
    openCheckinModal(sessionId);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function quickStartSessionAndQr(clubId = null) {
  try {
    const res = await apiFetch('/api/sessions/quick-start', {
      method: 'POST',
      body: JSON.stringify({ club_id: clubId }),
    });
    showToast(res.message);
    loadSessions();
    if (currentUser && ['ADMIN', 'CAMPUS_MGR', 'ADVISOR'].includes(currentUser.role)) {
      loadAdminCenter();
    }
    openCheckinModal(res.id);
  } catch (err) {
    showToast(err.message, true);
  }
}

let qrCountdownSeconds = 15;
let qrTickTimer = null;
let currentSessionForQr = null;

function updateQrCountdownUi() {
  const textEl = document.getElementById('qr-countdown-text');
  const barEl = document.getElementById('qr-progress-bar');
  if (textEl) textEl.textContent = `${qrCountdownSeconds}s`;
  if (barEl) {
    const pct = Math.max(0, Math.min(100, (qrCountdownSeconds / 15) * 100));
    barEl.style.width = `${pct}%`;
    if (qrCountdownSeconds <= 3) {
      barEl.className = 'bg-rose-500 h-1.5 rounded-full transition-all duration-1000 ease-linear';
    } else {
      barEl.className = 'bg-indigo-600 h-1.5 rounded-full transition-all duration-1000 ease-linear';
    }
  }
}

function tickQrCountdown() {
  if (!currentSessionForQr) return;
  qrCountdownSeconds--;
  if (qrCountdownSeconds <= 0) {
    qrCountdownSeconds = 15;
    refreshLiveQr(currentSessionForQr);
  } else {
    updateQrCountdownUi();
  }
}

async function refreshLiveQr(sessionId) {
  try {
    const data = await apiFetch(`/api/sessions/${sessionId}/qr`);
    currentLiveQrPayload = data;
    qrCountdownSeconds = data.expires_in_sec || 15;
    updateQrCountdownUi();

    const imgEl = document.getElementById('live-qr-img');
    const otpEl = document.getElementById('live-otp-code');
    const qrSrc = data.qr_image_data_url || data.qr_image_base64 || '';
    if (imgEl && qrSrc) {
      imgEl.src = qrSrc;
    }
    if (otpEl) {
      otpEl.textContent = data.otp_code || '------';
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

async function openCheckinModal(sessionId) {
  currentSessionForQr = sessionId;
  document.getElementById('checkin-session-id').value = sessionId;
  document.getElementById('checkin-otp-input').value = '';
  openModal('modal-checkin');

  await refreshLiveQr(sessionId);

  if (qrTickTimer) clearInterval(qrTickTimer);
  qrTickTimer = setInterval(tickQrCountdown, 1000);
}

function closeCheckinModal() {
  if (qrTickTimer) clearInterval(qrTickTimer);
  qrTickTimer = null;
  currentSessionForQr = null;
  toggleQrFullscreen(false);
  closeModal('modal-checkin');
}

function toggleQrFullscreen(forceState = null) {
  const container = document.getElementById('checkin-modal-container');
  const imgEl = document.getElementById('live-qr-img');
  const btn = document.getElementById('btn-qr-projector');
  if (!container || !imgEl) return;

  const isEnlarged = container.classList.contains('max-w-2xl');
  const makeEnlarged = forceState !== null ? forceState : !isEnlarged;

  if (makeEnlarged) {
    container.classList.remove('max-w-md');
    container.classList.add('max-w-2xl');
    imgEl.classList.remove('w-52', 'h-52');
    imgEl.classList.add('w-80', 'h-80');
    if (btn) btn.textContent = '✕ Standard';
  } else {
    container.classList.remove('max-w-2xl');
    container.classList.add('max-w-md');
    imgEl.classList.remove('w-80', 'h-80');
    imgEl.classList.add('w-52', 'h-52');
    if (btn) btn.textContent = '⛶ Projector';
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

function renderEventsGrid(list) {
  const grid = document.getElementById('events-grid');
  if (!grid) return;
  if (!list || !list.length) {
    grid.innerHTML = `<div class="col-span-full glass-card rounded-2xl p-8 text-center text-slate-500 text-sm">No events scheduled yet.</div>`;
    return;
  }

  const canManage = currentUser && currentUser.role !== 'STUDENT';

  grid.innerHTML = list
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

async function loadEvents() {
  swrFetch('events_list', '/api/events', {}, (list) => {
    eventsList = list;
    renderEventsGrid(eventsList);
  });
  refreshUsersAndClubsSelectors();
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
    fetchPendingQueue(true),
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

  // Populate Admin Live Rotating QR Station
  try {
    const adminSessions = await apiFetch('/api/sessions');
    const qrSelect = document.getElementById('admin-qr-session-select');
    if (qrSelect) {
      if (adminSessions && adminSessions.length) {
        qrSelect.innerHTML = adminSessions
          .map((s) => `<option value="${s.id}" data-status="${s.checkin_status}">${s.club_name} — ${s.topic} (${s.checkin_status})</option>`)
          .join('');
        onAdminQrSessionChanged();
      } else {
        qrSelect.innerHTML = `<option value="">No sessions scheduled yet (click Instant Live Session)</option>`;
        const pill = document.getElementById('admin-qr-status-pill');
        if (pill) pill.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-400"></span> No active session`;
      }
    }
  } catch (_) {}

  // 1. Render Unified Pending Queue (Starting with Pending Student Account Requests!)
  const qContainer = document.getElementById('admin-pending-queue-container');
  const cards = [];

  (queue.pending_accounts || []).forEach((u) => {
    cards.push(`
      <div class="p-3.5 rounded-xl bg-rose-50/80 border border-rose-200 flex items-center justify-between gap-2">
        <div>
          <span class="text-[10px] font-bold uppercase text-rose-700">${u.role || 'User'} Account Request (${u.campus_code})</span>
          <div class="font-bold text-slate-900">${u.full_name}</div>
          <div class="text-[11px] text-slate-600">${u.email} ${u.roll_number ? '• ' + u.roll_number : ''}</div>
        </div>
        <div class="flex gap-1 shrink-0">
          <button onclick="decideUserAccount('${u.id}', 'APPROVED')" class="px-2.5 py-1.5 rounded-lg btn-gradient-emerald text-white font-semibold text-[11px]">
            Permit
          </button>
          <button onclick="decideUserAccount('${u.id}', 'REJECTED')" class="px-2 py-1.5 rounded-lg border border-amber-300 text-amber-800 hover:bg-amber-50 text-[11px] font-semibold">
            Decline
          </button>
          <button onclick="handleDeleteUser('${u.id}', '${(u.full_name || '').replace(/'/g, "\\'")}', '${u.role || 'User'}')" class="px-2 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white font-semibold text-[11px]" title="Permanently remove account">
            Remove
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
          ? `<button onclick="decideUserAccount('${u.id}', 'APPROVED')" class="px-2.5 py-1 rounded btn-gradient-emerald text-white text-[11px] font-semibold mr-1">Permit</button>`
          : u.id !== currentUser.id
          ? `<button onclick="decideUserAccount('${u.id}', 'REJECTED')" class="px-2 py-1 rounded border border-amber-300 text-amber-700 hover:bg-amber-50 text-[11px] font-medium mr-1">Revoke</button>`
          : '';

      const canDelete = u.id !== currentUser.id && (currentUser.role === 'ADMIN' || u.role !== 'ADMIN');
      const deleteButton = canDelete
        ? `<button onclick="handleDeleteUser('${u.id}', '${(u.full_name || '').replace(/'/g, "\\'")}', '${u.role}')" class="px-2 py-1 rounded border border-rose-300 bg-rose-50/80 text-rose-700 hover:bg-rose-100 hover:border-rose-400 text-[11px] font-semibold transition-colors" title="Permanently remove this account">Remove</button>`
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
          <td class="px-4 py-2.5 flex items-center gap-1">${accessButtons} ${deleteButton}</td>
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

function onAdminQrSessionChanged() {
  const qrSelect = document.getElementById('admin-qr-session-select');
  const pill = document.getElementById('admin-qr-status-pill');
  const toggleBtn = document.getElementById('admin-btn-toggle-window');
  if (!qrSelect || !qrSelect.value) {
    if (pill) pill.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-400"></span> No session selected`;
    return;
  }
  const selectedOpt = qrSelect.options[qrSelect.selectedIndex];
  const status = selectedOpt ? selectedOpt.getAttribute('data-status') : 'CLOSED';
  if (pill) {
    if (status === 'OPEN') {
      pill.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span> <span class="text-emerald-700">Check-In Window OPEN (Active)</span>`;
    } else {
      pill.innerHTML = `<span class="w-2 h-2 rounded-full bg-slate-400"></span> <span class="text-slate-600">Window Closed</span>`;
    }
  }
  if (toggleBtn) {
    toggleBtn.textContent = status === 'OPEN' ? 'Close Window' : 'Open Window';
    toggleBtn.className = status === 'OPEN'
      ? 'px-3 py-2 rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold shrink-0'
      : 'px-3 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold shrink-0';
  }
}

async function launchAdminSelectedQr() {
  const qrSelect = document.getElementById('admin-qr-session-select');
  if (!qrSelect || !qrSelect.value) {
    quickStartSessionAndQr();
    return;
  }
  const sessionId = qrSelect.value;
  const selectedOpt = qrSelect.options[qrSelect.selectedIndex];
  const status = selectedOpt ? selectedOpt.getAttribute('data-status') : 'CLOSED';
  if (status !== 'OPEN') {
    try {
      await apiFetch(`/api/sessions/${sessionId}/checkin-window`, {
        method: 'POST',
        body: JSON.stringify({ action: 'OPEN', duration_minutes: 60, late_after_minutes: 15 }),
      });
      showToast('Check-in window opened! Rotating QR is live.');
      if (selectedOpt) selectedOpt.setAttribute('data-status', 'OPEN');
      onAdminQrSessionChanged();
      loadSessions();
    } catch (_) {}
  }
  openCheckinModal(sessionId);
}

async function toggleAdminSelectedWindow() {
  const qrSelect = document.getElementById('admin-qr-session-select');
  if (!qrSelect || !qrSelect.value) {
    showToast('Select a session first or click Instant Live Session.', true);
    return;
  }
  const sessionId = qrSelect.value;
  const selectedOpt = qrSelect.options[qrSelect.selectedIndex];
  const currentStatus = selectedOpt ? selectedOpt.getAttribute('data-status') : 'CLOSED';
  const newAction = currentStatus === 'OPEN' ? 'CLOSE' : 'OPEN';
  try {
    await apiFetch(`/api/sessions/${sessionId}/checkin-window`, {
      method: 'POST',
      body: JSON.stringify({ action: newAction, duration_minutes: 60, late_after_minutes: 15 }),
    });
    showToast(`Check-in window ${newAction === 'OPEN' ? 'opened' : 'closed'}`);
    if (selectedOpt) selectedOpt.setAttribute('data-status', newAction === 'OPEN' ? 'OPEN' : 'CLOSED');
    onAdminQrSessionChanged();
    loadSessions();
    if (newAction === 'OPEN') {
      openCheckinModal(sessionId);
    }
  } catch (err) {
    showToast(err.message, true);
  }
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

async function handleDeleteUser(userId, userName, userRole) {
  const confirmed = confirm(
    `Are you sure you want to permanently remove the ${userRole || 'User'} account for "${userName}"?\n\nThis will permanently delete their account profile, club memberships, and related records from the database. This action cannot be undone.`
  );
  if (!confirmed) return;

  try {
    const res = await apiFetch(`/api/admin/users/${userId}`, {
      method: 'DELETE',
    });
    showToast(res.message || `Account for "${userName}" removed successfully.`);
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
    'Karthik Nair, karthik@college.edu, STUDENT, Rathinam, MSOT-RT-2503, pass123',
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

function renderClubNewsFeed(items) {
  const container = document.getElementById('club-news-feed');
  if (!container) return;
  if (!items || !items.length) {
    container.innerHTML = `
      <div class="col-span-full glass-card rounded-2xl p-8 text-center text-slate-500 text-sm">
        <p class="font-semibold text-slate-700">No announcements posted yet.</p>
        <p class="text-xs text-slate-400 mt-1">
          ${currentUser && currentUser.role === 'STUDENT' ? 'Once your Campus Manager or Club President posts news for your club, it will appear here.' : 'Click "+ Post Club Announcement" to broadcast news to club members.'}
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
}

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
    await swrFetch('club_news', '/api/club-news', {}, (items) => {
      renderClubNewsFeed(items);
    });
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
// TAB 8: President Exclusive Member Attendance Tracker
// ============================================================================

let currentPresidentAttendanceData = null;

async function loadPresidentAttendance(clubId = '') {
  try {
    const url = `/api/president/club-attendance${clubId ? `?club_id=${clubId}` : ''}`;
    const cacheKey = `pres_attendance_${clubId || 'default'}`;

    swrFetch(cacheKey, url, {}, (data) => {
      currentPresidentAttendanceData = data;
      renderPresidentAttendance(data);
    });
  } catch (err) {
    showToast(err.message, true);
  }
}

function renderPresidentAttendance(data) {
  if (!data) return;

  // 1. Populate Club Selector
  const clubSelect = document.getElementById('pres-att-club-select');
  if (clubSelect && data.available_clubs) {
    clubSelect.innerHTML = data.available_clubs
      .map(
        (c) => `<option value="${c.id}" ${data.club && c.id === data.club.id ? 'selected' : ''}>${c.name} (${c.code}) - ${c.campus_code}</option>`
      )
      .join('');
  }

  // 2. Populate 5 KPI Cards
  const summary = data.summary || {};
  const totMemEl = document.getElementById('pres-att-total-members');
  if (totMemEl) totMemEl.textContent = summary.total_members || 0;
  const totSessEl = document.getElementById('pres-att-total-sessions');
  if (totSessEl) totSessEl.textContent = summary.total_sessions || 0;
  const avgPctEl = document.getElementById('pres-att-avg-pct');
  if (avgPctEl) avgPctEl.textContent = `${summary.average_attendance_pct || 0}%`;
  const perfEl = document.getElementById('pres-att-perfect-count');
  if (perfEl) perfEl.textContent = summary.perfect_attendance_count || 0;
  const lowEl = document.getElementById('pres-att-low-count');
  if (lowEl) lowEl.textContent = summary.low_attendance_count || 0;

  // 3. Render Member Roster
  renderPresidentAttendanceMembers(data.members || []);

  // 4. Render Sessions Turnout
  renderPresidentAttendanceSessions(data.sessions || []);
}

function renderPresidentAttendanceMembers(members) {
  const tbody = document.getElementById('pres-att-table-body');
  const badge = document.getElementById('pres-att-table-badge');
  if (badge) badge.textContent = `${members.length} member${members.length === 1 ? '' : 's'}`;
  if (!tbody) return;

  if (!members || !members.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="px-4 py-8 text-center text-slate-400">No members registered in this club roster yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = members
    .map((m) => {
      let badgeClass = 'bg-emerald-50 text-emerald-700 border-emerald-200';
      let badgeText = 'Good Standing';
      if (m.attendance_percentage >= 90) {
        badgeClass = 'bg-blue-50 text-blue-700 border-blue-200';
        badgeText = 'Excellent (90%+)';
      } else if (m.attendance_percentage < 75 && m.total_sessions > 0) {
        badgeClass = 'bg-rose-50 text-rose-700 border-rose-200';
        badgeText = 'At-Risk (<75%)';
      }

      let tierBadgeClass = 'bg-slate-100 text-slate-700';
      if (m.tier === 'PRIMARY') tierBadgeClass = 'bg-indigo-50 text-indigo-700 border border-indigo-200';
      if (m.tier === 'PRESIDENT' || m.tier === 'COORDINATOR') tierBadgeClass = 'bg-amber-50 text-amber-800 border border-amber-200';

      return `
        <tr class="hover:bg-white/40 transition">
          <td class="px-4 py-3">
            <div class="flex items-center gap-2.5">
              <div class="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-500 to-purple-600 text-white font-bold text-xs flex items-center justify-center shrink-0">
                ${m.full_name ? m.full_name.charAt(0).toUpperCase() : '?'}
              </div>
              <div>
                <div class="font-bold text-slate-900">${m.full_name}</div>
                <div class="text-[11px] text-slate-400">${m.email}</div>
              </div>
            </div>
          </td>
          <td class="px-4 py-3 font-mono text-slate-600 font-medium">${m.roll_number}</td>
          <td class="px-4 py-3">
            <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${tierBadgeClass}">${m.tier}</span>
          </td>
          <td class="px-4 py-3 text-center font-semibold text-slate-700">${m.total_sessions}</td>
          <td class="px-4 py-3 text-center">
            <span class="font-bold text-emerald-600">${m.attended_sessions}</span>
            ${m.late_sessions > 0 ? `<span class="text-[10px] text-amber-600 ml-1">(${m.late_sessions} late)</span>` : ''}
          </td>
          <td class="px-4 py-3 text-center font-semibold text-slate-500">${m.missed_sessions}</td>
          <td class="px-4 py-3 text-center">
            <div class="font-black text-xs ${m.attendance_percentage >= 75 ? 'text-emerald-600' : 'text-rose-600'}">
              ${m.attendance_percentage}%
            </div>
            <div class="w-16 bg-slate-100 rounded-full h-1.5 mx-auto mt-1 overflow-hidden">
              <div class="h-1.5 rounded-full ${m.attendance_percentage >= 75 ? 'bg-emerald-500' : 'bg-rose-500'}" style="width: ${Math.min(100, m.attendance_percentage)}%"></div>
            </div>
          </td>
          <td class="px-4 py-3 text-slate-600 text-[11px]">
            ${m.last_attended_date ? `<div>${m.last_attended_date}</div><div class="text-[10px] text-slate-400 truncate max-w-[120px]">${m.last_session_topic || ''}</div>` : '<span class="text-slate-400">Never checked in</span>'}
          </td>
          <td class="px-4 py-3 text-center">
            <span class="px-2 py-0.5 rounded-full text-[10px] font-bold border ${badgeClass}">${badgeText}</span>
          </td>
        </tr>
      `;
    })
    .join('');
}

function renderPresidentAttendanceSessions(sessions) {
  const tbody = document.getElementById('pres-att-sessions-body');
  if (!tbody) return;

  if (!sessions || !sessions.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-6 text-center text-slate-400">No sessions conducted for this club yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = sessions
    .map((s) => `
      <tr class="hover:bg-white/40 transition">
        <td class="px-4 py-3 font-semibold text-slate-900">${s.topic}</td>
        <td class="px-4 py-3 text-slate-600">${s.scheduled_date}</td>
        <td class="px-4 py-3"><span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-100 text-slate-700">${s.format}</span></td>
        <td class="px-4 py-3">
          <span class="px-2 py-0.5 rounded-full text-[10px] font-bold ${s.checkin_status === 'OPEN' ? 'bg-emerald-50 text-emerald-700 animate-pulse' : 'bg-slate-100 text-slate-600'}">
            ${s.checkin_status}
          </span>
        </td>
        <td class="px-4 py-3 text-center font-bold text-slate-800">${s.present_count} / ${s.total_expected}</td>
        <td class="px-4 py-3 text-center">
          <span class="font-black text-xs ${s.attendance_pct >= 75 ? 'text-emerald-600' : 'text-slate-700'}">${s.attendance_pct}%</span>
        </td>
      </tr>
    `)
    .join('');
}

function filterPresidentAttendanceTable() {
  if (!currentPresidentAttendanceData || !currentPresidentAttendanceData.members) return;
  const q = (document.getElementById('pres-att-search')?.value || '').toLowerCase().trim();
  const tier = document.getElementById('pres-att-tier-filter')?.value || '';

  const filtered = currentPresidentAttendanceData.members.filter((m) => {
    const matchesQ = !q || m.full_name.toLowerCase().includes(q) || m.email.toLowerCase().includes(q) || (m.roll_number && m.roll_number.toLowerCase().includes(q));
    const matchesTier = !tier || m.tier === tier;
    return matchesQ && matchesTier;
  });

  renderPresidentAttendanceMembers(filtered);
}

function exportPresidentAttendanceCsv() {
  const clubSelect = document.getElementById('pres-att-club-select');
  const clubId = clubSelect ? clubSelect.value : '';
  const url = `/api/president/club-attendance/export-csv${clubId ? `?club_id=${clubId}` : ''}`;
  window.open(url, '_blank');
}

// ============================================================================
// Initialize Application on Page Load
// ============================================================================

window.addEventListener('DOMContentLoaded', async () => {
  // 1. Instant hydration of campuses from SWR cache (0ms)
  const cachedCampuses = getSwr('campuses');
  if (cachedCampuses && cachedCampuses.length) {
    campusesList = cachedCampuses;
    populateCampusSelects(campusesList);
  }

  // 2. Instant hydration of authenticated user from SWR cache (0ms)
  const cachedUser = getSwr('currentUser');
  if (authToken && cachedUser) {
    currentUser = cachedUser;
    enterApp(); // 0ms transition straight to user dashboard!

    // Silently revalidate user and campuses with single bootstrap query in background
    try {
      const boot = await apiFetch('/api/bootstrap');
      if (boot && boot.user) {
        currentUser = boot.user;
        setSwr('currentUser', currentUser);
        const nameEl = document.getElementById('nav-user-name');
        const metaEl = document.getElementById('nav-user-meta');
        const roleEl = document.getElementById('nav-role-badge');
        if (nameEl) nameEl.textContent = currentUser.full_name;
        if (metaEl) metaEl.textContent = `${currentUser.email} • ${currentUser.campus_code}`;
        if (roleEl) roleEl.textContent = currentUser.role;
      }
      if (boot && boot.campuses) {
        campusesList = boot.campuses;
        setSwr('campuses', campusesList);
        populateCampusSelects(campusesList);
      }
      if (typeof boot.total_pending === 'number') {
        const badge = document.getElementById('admin-pending-badge');
        if (badge) {
          if (boot.total_pending > 0) {
            badge.textContent = boot.total_pending;
            badge.classList.remove('hidden');
          } else {
            badge.classList.add('hidden');
          }
        }
      }
    } catch (err) {
      if (err.message && (err.message.includes('401') || err.message.toLowerCase().includes('token') || err.message.toLowerCase().includes('credential'))) {
        handleLogout();
        showHeroScreen();
      }
    }
  } else if (authToken) {
    // Auth token exists without cached user profile -> single round-trip bootstrap
    document.getElementById('hero-screen')?.classList.add('hidden');
    try {
      const boot = await apiFetch('/api/bootstrap');
      currentUser = boot.user;
      setSwr('currentUser', currentUser);
      campusesList = boot.campuses;
      setSwr('campuses', campusesList);
      populateCampusSelects(campusesList);
      await enterApp();
    } catch (_) {
      handleLogout();
      showHeroScreen();
    }
  } else {
    // Unauthenticated visitor -> instant render hero screen & warm campus selects
    loadCampuses();
    showHeroScreen();
  }
});
