const app = document.getElementById("app");
const toastRoot = document.getElementById("toast-root");

const state = {
  bootstrap: null,
  auth: null,
  route: "landing",
  params: {},
  toast: null,
  theme: localStorage.getItem("reima-theme") || "light",
  cache: {}
};

const navByRole = {
  ADMIN: ["dashboard", "pending-approvals", "approval-history", "team-expenses", "employees", "workflow", "company-settings", "all-expenses", "reports", "audit-logs", "profile"],
  EMPLOYEE: ["dashboard", "submit-expense", "my-expenses", "profile"],
  MANAGER: ["dashboard", "pending-approvals", "approval-history", "team-expenses", "profile"],
  FINANCE: ["dashboard", "pending-approvals", "approval-history", "team-expenses", "reports", "profile"],
  DIRECTOR: ["dashboard", "pending-approvals", "approval-history", "team-expenses", "reports", "profile"]
};

const routeLabels = {
  landing: "Landing",
  "login-selector": "Login",
  "admin-selector": "Admin Access",
  signup: "Create Company",
  "admin-login": "Admin Login",
  "staff-login": "Staff Login",
  "forgot-password": "Forgot Password",
  "resend-verification": "Resend Verification",
  "verify-email": "Verify Email",
  "reset-password": "Reset Password",
  dashboard: "Dashboard",
  employees: "Employees",
  workflow: "Approval Workflow",
  "company-settings": "Company Settings",
  "all-expenses": "All Expenses",
  "submit-expense": "Submit Expense",
  "my-expenses": "My Expenses",
  "expense-details": "Expense Details",
  "pending-approvals": "Pending Approvals",
  "approval-history": "Approval History",
  "team-expenses": "Team Expenses",
  reports: "Reports",
  "audit-logs": "Audit Logs",
  profile: "Profile"
};

document.addEventListener("click", handleClick);
document.addEventListener("submit", handleSubmit);
document.addEventListener("change", handleChange);
window.addEventListener("hashchange", syncRoute);

start();

async function start() {
  applyTheme();
  syncRoute();
  await bootstrap();
  await render();
}

function syncRoute() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path = "", query = ""] = raw.split("?");
  state.route = path || "landing";
  state.params = Object.fromEntries(new URLSearchParams(query));
  if (state.bootstrap) {
    render();
  }
}

function setRoute(route, params = {}) {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== "")
  ).toString();
  window.location.hash = `/${route}${query ? `?${query}` : ""}`;
}

async function bootstrap() {
  const data = await api("/api/bootstrap");
  state.bootstrap = data;
  state.auth = data.auth || null;
  if (state.auth && ["landing", "signup", "admin-login", "staff-login", "forgot-password", "resend-verification", "verify-email", "reset-password"].includes(state.route)) {
    state.route = "dashboard";
    setRoute("dashboard");
  }
}

function applyTheme() {
  document.body.classList.toggle("dark", state.theme === "dark");
}

function showToast(message, tone = "info") {
  state.toast = { message, tone };
  updateToast();
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    state.toast = null;
    updateToast();
  }, 3500);
}

async function api(url, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.auth?.csrf_token && ["POST", "PATCH", "DELETE"].includes((options.method || "GET").toUpperCase())) {
    headers["X-CSRF-Token"] = state.auth.csrf_token;
  }
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed.");
  }
  return data;
}

async function loadPageData(route) {
  if (!state.auth) return null;
  switch (route) {
    case "dashboard":
      return api("/api/dashboard");
    case "employees":
      return api("/api/users");
    case "workflow":
      return api("/api/workflow");
    case "company-settings":
      return api("/api/profile");
    case "submit-expense":
      if (state.params.id) return api(`/api/expenses/${state.params.id}`);
      return null;
    case "my-expenses":
      return api("/api/expenses/my");
    case "all-expenses":
      return api("/api/expenses/company");
    case "expense-details":
      return api(`/api/expenses/${state.params.id}`);
    case "pending-approvals":
      return api("/api/approvals/pending");
    case "approval-history":
      return api("/api/approvals/history");
    case "team-expenses":
      return api("/api/expenses/team");
    case "reports":
      return api("/api/reports");
    case "audit-logs":
      return api("/api/audit-logs");
    case "profile":
      return api("/api/profile");
    default:
      return null;
  }
}

async function render() {
  if (!state.bootstrap) {
    app.innerHTML = `<div class="public-shell"><div class="public-wrap"><div class="panel"><p>Loading...</p></div></div></div>`;
    return;
  }

  if (!state.auth) {
    app.innerHTML = renderPublic();
    syncDynamicInputs();
    return;
  }

  const allowed = navByRole[state.auth.user.role] || [];
  if (!allowed.includes(state.route) && state.route !== "expense-details") {
    setRoute("dashboard");
    return;
  }

  let pageData = null;
  try {
    pageData = await loadPageData(state.route);
    state.cache[state.route] = pageData;
  } catch (error) {
    showToast(error.message, "danger");
    if (error.message.includes("Authentication")) {
      state.auth = null;
      await bootstrap();
      return;
    }
  }

  app.innerHTML = renderPrivate(pageData);
  syncDynamicInputs();
}

function renderPublic() {
  if (state.route === "login-selector") return renderLoginSelectorPage();
  if (state.route === "admin-selector") return renderAdminSelectorPage();
  if (state.route === "signup") return renderSignupPage();
  if (state.route === "admin-login") return renderLoginPage("admin");
  if (state.route === "staff-login") return renderLoginPage("staff");
  if (state.route === "forgot-password") return renderForgotPasswordPage();
  if (state.route === "resend-verification") return renderResendVerificationPage();
  if (state.route === "verify-email") return renderVerifyEmailPage();
  if (state.route === "reset-password") return renderResetPasswordPage();
  return renderLandingPage();
}

function renderLandingPage() {
  return `
    <div class="public-shell">
      <div class="public-wrap">
        ${renderPublicTopbar()}
        <section class="hero">
          <div class="brand">
            <div class="brand-mark">R</div>
            <div class="brand-copy">
              <strong>Reima</strong>
              <span class="helper">Secure expense approvals for real teams</span>
            </div>
          </div>
          <span class="eyebrow">Deployable product | role-based approvals | audit ready</span>
          <h1>Expense approvals with real security and real workflows.</h1>
          <p>
            Reima is now built as a backend-driven product with SQLite persistence, hashed passwords,
            server-side sessions, CSRF protection, role-based routing, admin-only governance tools, and a
            clean solid-color interface for day and night use.
          </p>
        </section>

        <section class="hero-grid">
          <div class="panel">
            <div class="page-head">
              <div>
                <span class="badge">Admin View</span>
                <h2>Approval rules and company control</h2>
              </div>
            </div>
            <div class="stack-list">
              <div class="notice"><strong>User management</strong><p>Create managers, employees, and finance approvers. The admin account acts as the director-level authority.</p></div>
              <div class="notice"><strong>Approval logic</strong><p>Define ordered approvers, mandatory steps, and percentage or hybrid rules.</p></div>
              <div class="notice"><strong>Security</strong><p>Passwords use salted scrypt. Sessions are HttpOnly and SameSite=Strict with CSRF protection.</p></div>
            </div>
          </div>
          <div class="panel">
            <div class="page-head">
              <div>
                <span class="badge">Employee + Manager</span>
                <h2>Submit, track, and approve expenses</h2>
              </div>
            </div>
            <div class="list-stack">
              <div class="notice"><strong>Employee view</strong><p>Upload receipt, enter expense details, and track approval status.</p></div>
              <div class="notice"><strong>Manager view</strong><p>Review approvals with request owner, category, amount, current status, and actions.</p></div>
              <div class="notice"><strong>Live references</strong><p>Country/currency and exchange rates are pulled from public APIs with local fallback.</p></div>
            </div>
          </div>
        </section>
      </div>
    </div>
  `;
}

function renderLoginSelectorPage() {
  return `
    <div class="public-shell">
      <div class="public-wrap">
        ${renderPublicTopbar()}
        <section class="auth-card">
          <div class="page-head">
            <div>
              <span class="badge">Login</span>
              <h2>Choose your access type</h2>
              <p>Admins manage the company workspace and also serve as the director-level approver. Staff includes managers, employees, and finance approvers.</p>
            </div>
          </div>
          <div class="split-grid">
            <div class="panel">
              <span class="badge">Admin</span>
              <h3>Governance access</h3>
              <p>Use this for company setup, employee management, workflow rules, currency, reports, and audit.</p>
              <div class="button-row">
                <button class="button" data-route="admin-selector">Continue as Admin</button>
              </div>
            </div>
            <div class="panel">
              <span class="badge">Staff</span>
              <h3>Operational access</h3>
              <p>Managers review approvals. Employees submit requests. Finance approves where needed. Admin covers director-level decisions.</p>
              <div class="button-row">
                <button class="button" data-route="staff-login">Continue as Staff</button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  `;
}

function renderAdminSelectorPage() {
  return `
    <div class="public-shell">
      <div class="public-wrap">
        ${renderPublicTopbar()}
        <section class="auth-card">
          <div class="page-head">
            <div>
              <span class="badge">Admin Access</span>
              <h2>Login or create a company</h2>
              <p>Existing admins can sign in. New organizations should create the company workspace first.</p>
            </div>
          </div>
          <div class="split-grid">
            <div class="panel">
              <span class="badge">Admin Login</span>
              <h3>Access an existing company</h3>
              <p>Sign in to manage users, rules, audit logs, and company-level controls.</p>
              <div class="button-row">
                <button class="button" data-route="admin-login">Admin Login</button>
              </div>
            </div>
            <div class="panel">
              <span class="badge">Create Company</span>
              <h3>Start a new workspace</h3>
              <p>Create the company, create the first admin, and initialize the default approval flow.</p>
              <div class="button-row">
                <button class="button" data-route="signup">Create Company</button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  `;
}

function renderSignupPage() {
  const defaultCountry = state.bootstrap.countries[0]?.name || "";
  const defaultCurrency = currencyForCountryName(defaultCountry);
  return `
    <div class="public-shell">
      <div class="public-wrap">
        ${renderPublicTopbar()}
        <section class="auth-card">
          <div class="page-head">
            <div>
              <span class="badge">Company Setup</span>
              <h2>Create your Reima workspace</h2>
            </div>
            <button class="button-secondary" data-route="landing">Back</button>
          </div>
          <form id="signup-form" class="form-grid">
            <div class="field">
              <label for="companyName">Company Name</label>
              <input id="companyName" name="company_name" required />
            </div>
            <div class="field">
              <label for="country">Country</label>
              <select id="country" name="country" required>
                ${renderCountryOptions(defaultCountry)}
              </select>
            </div>
            <div class="field">
              <label for="signupBaseCurrency">Base Currency</label>
              <input id="signupBaseCurrency" value="${defaultCurrency}" readonly />
            </div>
            <div class="field">
              <label for="adminName">Admin Name</label>
              <input id="adminName" name="admin_name" required />
            </div>
            <div class="field">
              <label for="adminEmail">Admin Email</label>
              <input id="adminEmail" name="admin_email" type="email" required />
            </div>
            <div class="field">
              <label for="signupPassword">Password</label>
              <input id="signupPassword" name="password" type="password" minlength="8" required />
            </div>
            <div class="field">
              <label for="confirmPassword">Confirm Password</label>
              <input id="confirmPassword" name="confirm_password" type="password" minlength="8" required />
            </div>
            <div class="field full">
              <p class="helper">Company signup creates the admin account, company record, base currency, default approval flow, approval rule, and sends an email verification link to the admin.</p>
            </div>
            <div class="field full">
              <div class="button-row">
                <button class="button" type="submit">Create Workspace</button>
                <button class="button-secondary" type="button" data-route="admin-login">Go to Admin Login</button>
              </div>
            </div>
          </form>
        </section>
      </div>
    </div>
  `;
}

function renderLoginPage(kind) {
  const title = kind === "admin" ? "Admin Login" : "Staff Login";
  const helper =
    kind === "admin"
      ? "Use this entry only for company admins."
      : "Managers, employees, finance, and directors all use this shared login.";
  return `
    <div class="public-shell">
      <div class="public-wrap">
        ${renderPublicTopbar()}
        <section class="auth-card">
          <div class="page-head">
            <div>
              <span class="badge">${title}</span>
              <h2>${title}</h2>
              <p>${helper}</p>
            </div>
            <button class="button-secondary" data-route="landing">Back</button>
          </div>
          <form id="${kind}-login-form" class="form-grid">
            <div class="field">
              <label for="${kind}Email">Email</label>
              <input id="${kind}Email" name="email" type="email" required />
            </div>
            <div class="field">
              <label for="${kind}Password">Password</label>
              <input id="${kind}Password" name="password" type="password" required />
            </div>
            <div class="field full">
              <div class="button-row">
                <button class="button" type="submit">Login</button>
                ${kind === "admin" ? `<button class="button-secondary" type="button" data-route="signup">Create Company</button>` : ""}
              </div>
            </div>
            <div class="field full">
              <div class="button-row">
                <button class="link-button" type="button" data-route="forgot-password">Forgot password</button>
                <button class="link-button" type="button" data-route="resend-verification">Resend verification email</button>
              </div>
            </div>
          </form>
        </section>
      </div>
    </div>
  `;
}

function renderForgotPasswordPage() {
  return `
    <div class="public-shell">
      <div class="public-wrap">
        ${renderPublicTopbar()}
        <section class="auth-card">
          <div class="page-head">
            <div>
              <span class="badge">Password Reset</span>
              <h2>Forgot your password?</h2>
              <p>Enter your work email and we will send a secure reset link.</p>
            </div>
            <button class="button-secondary" data-route="landing">Back</button>
          </div>
          <form id="forgot-password-form" class="form-grid">
            <div class="field full">
              <label for="forgotEmail">Email</label>
              <input id="forgotEmail" name="email" type="email" required />
            </div>
            <div class="field full"><button class="button" type="submit">Send Reset Link</button></div>
          </form>
        </section>
      </div>
    </div>
  `;
}

function renderResendVerificationPage() {
  return `
    <div class="public-shell">
      <div class="public-wrap">
        ${renderPublicTopbar()}
        <section class="auth-card">
          <div class="page-head">
            <div>
              <span class="badge">Verification</span>
              <h2>Resend verification email</h2>
              <p>Use the email on your Reima account and we will send a fresh verification link.</p>
            </div>
            <button class="button-secondary" data-route="landing">Back</button>
          </div>
          <form id="request-verification-form" class="form-grid">
            <div class="field full">
              <label for="verificationEmail">Email</label>
              <input id="verificationEmail" name="email" type="email" required />
            </div>
            <div class="field full"><button class="button" type="submit">Send Verification Link</button></div>
          </form>
        </section>
      </div>
    </div>
  `;
}

function renderVerifyEmailPage() {
  const token = state.params.token || "";
  return `
    <div class="public-shell">
      <div class="public-wrap">
        ${renderPublicTopbar()}
        <section class="auth-card">
          <div class="page-head">
            <div>
              <span class="badge">Verify Email</span>
              <h2>Complete your account verification</h2>
              <p>Use the verification link from your inbox. If you opened the email link directly, the token is already filled in.</p>
            </div>
            <button class="button-secondary" data-route="landing">Back</button>
          </div>
          <form id="verify-email-form" class="form-grid">
            <div class="field full">
              <label for="verifyToken">Verification Token</label>
              <input id="verifyToken" name="token" value="${escapeHtml(token)}" required />
            </div>
            <div class="field full"><button class="button" type="submit">Verify Email</button></div>
          </form>
        </section>
      </div>
    </div>
  `;
}

function renderResetPasswordPage() {
  const token = state.params.token || "";
  return `
    <div class="public-shell">
      <div class="public-wrap">
        ${renderPublicTopbar()}
        <section class="auth-card">
          <div class="page-head">
            <div>
              <span class="badge">Reset Password</span>
              <h2>Choose a new password</h2>
              <p>Use a strong password with at least 8 characters.</p>
            </div>
            <button class="button-secondary" data-route="landing">Back</button>
          </div>
          <form id="reset-password-form" class="form-grid">
            <div class="field full">
              <label for="resetToken">Reset Token</label>
              <input id="resetToken" name="token" value="${escapeHtml(token)}" required />
            </div>
            <div class="field">
              <label for="resetPassword">New Password</label>
              <input id="resetPassword" name="password" type="password" minlength="8" required />
            </div>
            <div class="field">
              <label for="resetConfirmPassword">Confirm Password</label>
              <input id="resetConfirmPassword" name="confirm_password" type="password" minlength="8" required />
            </div>
            <div class="field full"><button class="button" type="submit">Reset Password</button></div>
          </form>
        </section>
      </div>
    </div>
  `;
}

function renderPublicTopbar() {
  const isLanding = state.route === "landing";
  return `
    <div class="topbar">
      <div class="brand">
        <div class="brand-mark">R</div>
        <div class="brand-copy">
          <strong>Reima</strong>
          <span class="helper">Expense approval workflow system</span>
        </div>
      </div>
      <div class="topbar-right">
        ${isLanding ? `<button class="button" data-route="login-selector">Login</button>` : `<button class="button-secondary" data-route="landing">Back</button>`}
        <button class="button-secondary" data-action="toggle-theme">${state.theme === "dark" ? "Light Mode" : "Dark Mode"}</button>
      </div>
    </div>
  `;
}

function renderPrivate(data) {
  const navItems = navByRole[state.auth.user.role] || [];
  return `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">R</div>
          <div class="brand-copy">
            <strong>Reima</strong>
            <span class="helper">${state.auth.company.name}</span>
          </div>
        </div>
        <div class="surface">
          <strong>${state.auth.user.name}</strong>
          <p>${state.auth.user.role} | ${state.auth.user.department}</p>
        </div>
        <div class="sidebar-section">
          ${navItems.map((route) => `<button class="nav-button ${state.route === route ? "active" : ""}" data-route="${route}">${routeLabels[route]}</button>`).join("")}
        </div>
      </aside>
      <main class="content">
        <header class="topbar">
          <div class="topbar-left">
            <div>
              <span class="badge">${routeLabels[state.route] || "Reima"}</span>
              <h2>${routeLabels[state.route] || "Reima"}</h2>
            </div>
          </div>
          <div class="topbar-right">
            <span class="role-chip">${state.auth.user.role}</span>
            <button class="button-secondary" data-action="toggle-theme">${state.theme === "dark" ? "Light Mode" : "Dark Mode"}</button>
            <button class="button-secondary" data-route="profile">Profile</button>
            <button class="button-danger" data-action="logout">Logout</button>
          </div>
        </header>
        ${renderPrivatePage(data)}
      </main>
    </div>
  `;
}

function renderPrivatePage(data) {
  switch (state.route) {
    case "dashboard":
      return renderDashboard(data);
    case "employees":
      return renderEmployeesPage(data);
    case "workflow":
      return renderWorkflowPage(data);
    case "company-settings":
      return renderCompanySettingsPage(data);
    case "submit-expense":
      return renderSubmitExpensePage(data);
    case "my-expenses":
      return renderExpensesPage("My Expenses", data?.expenses || [], true);
    case "all-expenses":
      return renderExpensesPage("All Expenses", data?.expenses || [], false);
    case "team-expenses":
      return renderExpensesPage("Team Expenses", data?.expenses || [], false);
    case "expense-details":
      return renderExpenseDetailsPage(data?.expense);
    case "pending-approvals":
      return renderPendingApprovalsPage(data?.approvals || []);
    case "approval-history":
      return renderApprovalHistoryPage(data?.approvals || []);
    case "reports":
      return renderReportsPage(data);
    case "audit-logs":
      return renderAuditLogsPage(data?.logs || []);
    case "profile":
      return renderProfilePage(data);
    default:
      return `<section class="panel"><p>Page not found.</p></section>`;
  }
}

function renderDashboard(data) {
  if (!data) return `<section class="panel"><p>Loading...</p></section>`;
  const stats = data.stats || {};
  const cards = Object.entries(stats).map(
    ([key, value]) => `
      <div class="metric-card">
        <span class="helper">${humanize(key)}</span>
        <strong>${typeof value === "number" ? value : value}</strong>
      </div>
    `
  );

  const secondary =
    data.role === "ADMIN"
      ? renderExpenseTable(data.expenses || [], false)
      : data.role === "EMPLOYEE"
        ? renderExpenseTable(data.expenses || [], false)
        : renderApprovalsTable(data.pending || []);

  const feed =
    data.role === "ADMIN"
      ? renderFeed(data.logs || [], "description")
      : data.role === "EMPLOYEE"
        ? renderFeed(data.notifications || [], "message")
        : renderFeed(data.history || [], "comment");

  return `
    <section class="stats-grid">${cards.join("")}</section>
    <section class="dashboard-grid">
      <div class="table-card">
        <div class="page-head">
          <div>
            <span class="badge">${data.role}</span>
            <h3>${data.role === "ADMIN" ? "Company activity" : data.role === "EMPLOYEE" ? "Recent expenses" : "Approval queue"}</h3>
          </div>
        </div>
        ${secondary}
      </div>
      <div class="panel">
        <div class="page-head">
          <div>
            <span class="badge">Updates</span>
            <h3>${data.role === "ADMIN" ? "Audit feed" : "Recent updates"}</h3>
          </div>
        </div>
        ${feed}
      </div>
    </section>
  `;
}

function renderEmployeesPage(data) {
  const users = data?.users || [];
  const managers = users.filter((user) => user.role === "MANAGER" && user.status === "ACTIVE");
  return `
    <section class="split-grid">
      <div class="panel">
        <div class="page-head">
          <div>
            <span class="badge">Create User</span>
            <h3>Add employee, manager, or finance approver</h3>
          </div>
        </div>
        <form id="user-form" class="form-grid">
          <div class="field"><label>Name</label><input name="name" required /></div>
          <div class="field"><label>Email</label><input name="email" type="email" required /></div>
          <div class="field">
            <label>Role</label>
            <select name="role" required>
              <option value="EMPLOYEE">Employee</option>
              <option value="MANAGER">Manager</option>
              <option value="FINANCE">Finance</option>
            </select>
          </div>
          <div class="field">
            <label>Manager</label>
            <select name="manager_id">
              <option value="">None</option>
              ${managers.map((manager) => `<option value="${manager.id}">${escapeHtml(manager.name)}</option>`).join("")}
            </select>
          </div>
          <div class="field"><label>Department</label><input name="department" required /></div>
          <div class="field"><label>Temporary Password</label><input name="password" type="password" minlength="8" required /></div>
          <div class="field full"><button class="button" type="submit">Create User</button></div>
        </form>
      </div>
      <div class="table-card">
        <div class="page-head">
          <div><span class="badge">Team Directory</span><h3>Company users</h3></div>
        </div>
        ${renderUserTable(users)}
      </div>
    </section>
  `;
}

function renderWorkflowPage(data) {
  const steps = data?.steps || [];
  const approvers = data?.approvers || [];
  const rule = data?.rule || {};
  return `
    <section class="split-grid">
      <div class="panel">
        <div class="page-head"><div><span class="badge">Approval Rules</span><h3>Manager first, then configured approvers</h3></div></div>
        <div class="notice">
          <strong>Workflow model</strong>
          <p>Employees save drafts, submit to manager review, and then configured approvers continue through the workflow. The admin account serves as the director-level approver.</p>
        </div>
        <div class="notice">
          <strong>Mandatory vs optional</strong>
          <p>Mandatory steps require an active approver for that role. Optional steps are skipped if nobody in that role is active. When a role has multiple active users, Reima sends the same step to all of them automatically.</p>
        </div>
        <div class="list-stack">
          ${steps
            .map(
              (step) => `
              <div class="notice">
                <strong>Step ${step.step_order}: ${step.approver_role}</strong>
                <p>${step.is_mandatory ? "Mandatory" : "Optional"}</p>
                <div class="inline-actions">
                  <button class="button-secondary" data-action="move-step" data-id="${step.id}" data-direction="up">Up</button>
                  <button class="button-secondary" data-action="move-step" data-id="${step.id}" data-direction="down">Down</button>
                  <button class="button-secondary" data-action="toggle-step" data-id="${step.id}" data-mandatory="${step.is_mandatory ? "0" : "1"}">${step.is_mandatory ? "Make Optional" : "Make Mandatory"}</button>
                  <button class="button-danger" data-action="delete-step" data-id="${step.id}">Delete</button>
                </div>
              </div>
            `
            )
            .join("")}
        </div>
      </div>
      <div class="panel">
        <div class="page-head"><div><span class="badge">Rules</span><h3>Approval settings</h3></div></div>
        <form id="step-form" class="form-grid">
          <div class="field">
            <label>Approver Role</label>
            <select name="approver_role">
              <option value="MANAGER">Manager</option>
              <option value="FINANCE">Finance</option>
              <option value="DIRECTOR">Director / Admin</option>
            </select>
          </div>
          <div class="field">
            <label>Mandatory</label>
            <select name="is_mandatory">
              <option value="true">Mandatory</option>
              <option value="false">Optional</option>
            </select>
          </div>
          <div class="field full"><button class="button" type="submit">Add Step</button></div>
        </form>
        <form id="rule-form" class="form-grid">
          <div class="field">
            <label>Rule Type</label>
            <select name="type" id="ruleType">
              <option value="PERCENTAGE" ${rule.type === "PERCENTAGE" ? "selected" : ""}>Percentage</option>
              <option value="SPECIFIC" ${rule.type === "SPECIFIC" ? "selected" : ""}>Specific Approver</option>
              <option value="HYBRID" ${rule.type === "HYBRID" ? "selected" : ""}>Hybrid</option>
            </select>
          </div>
          <div class="field">
            <label>Threshold Percentage</label>
            <input id="ruleThreshold" name="threshold_percentage" type="number" min="1" max="100" value="${rule.threshold_percentage || 60}" />
          </div>
          <div class="field full">
            <label>Specific Approver</label>
            <select id="specificApprover" name="specific_user_id">
              <option value="">None</option>
              ${approvers.map((user) => `<option value="${user.id}" ${String(rule.specific_user_id || "") === String(user.id) ? "selected" : ""}>${escapeHtml(user.name)} (${user.role})</option>`).join("")}
            </select>
          </div>
          <div class="field full">
            <p class="helper">Specific and hybrid rules require a specific approver. Percentage and hybrid rules require a threshold percentage. Multiple approvers are picked up automatically from active users in the selected stage role.</p>
          </div>
          <div class="field full"><button class="button" type="submit">Save Rule</button></div>
        </form>
      </div>
    </section>
  `;
}

function renderCompanySettingsPage(data) {
  const company = data?.company || state.auth.company;
  return `
    <section class="split-grid">
      <div class="panel">
        <div class="page-head"><div><span class="badge">Currency</span><h3>Company settings</h3></div></div>
        <form id="company-settings-form" class="form-grid">
          <div class="field">
            <label>Country</label>
            <select name="country" id="companyCountry">
              ${renderCountryOptions(company.country)}
            </select>
          </div>
          <div class="field">
            <label>Base Currency</label>
            <select name="base_currency" id="companyBaseCurrency">
              ${state.bootstrap.currencies.map((currency) => `<option value="${currency}" ${company.base_currency === currency ? "selected" : ""}>${currency}</option>`).join("")}
            </select>
          </div>
          <div class="field full"><button class="button" type="submit">Save Settings</button></div>
        </form>
      </div>
      <div class="panel">
        <div class="page-head"><div><span class="badge">Company</span><h3>${escapeHtml(company.name)}</h3></div></div>
        <div class="list-stack">
          <div class="notice">Country: ${escapeHtml(company.country)}</div>
          <div class="notice">Base currency: ${escapeHtml(company.base_currency)}</div>
          <div class="notice">Company admins can change reporting currency and governance settings from here.</div>
        </div>
      </div>
    </section>
  `;
}

function renderSubmitExpensePage(data) {
  const expense = data?.expense || null;
  const isDraft = Boolean(expense?.is_draft);
  return `
    <section class="split-grid">
      <div class="panel">
        <div class="page-head"><div><span class="badge">${expense ? "Edit Expense" : "Create Expense"}</span><h3>${expense ? `Expense #${expense.id}` : "Submit Expense"}</h3></div></div>
        <form id="expense-form" class="form-grid" data-expense-id="${expense?.id || ""}">
          <div class="field"><label>Amount</label><input name="amount" type="number" min="0" step="0.01" value="${expense?.amount || ""}" required /></div>
          <div class="field"><label>Currency</label><select name="currency">${state.bootstrap.currencies.map((currency) => `<option value="${currency}" ${expense?.currency === currency || (!expense && currency === state.auth.company.base_currency) ? "selected" : ""}>${currency}</option>`).join("")}</select></div>
          <div class="field"><label>Category</label><input name="category" value="${escapeHtml(expense?.category || "")}" required /></div>
          <div class="field"><label>Date</label><input name="expense_date" type="date" value="${expense?.expense_date || new Date().toISOString().slice(0, 10)}" required /></div>
          <div class="field"><label>Vendor</label><input name="vendor" value="${escapeHtml(expense?.vendor || "")}" required /></div>
          <div class="field"><label>Receipt Name</label><input name="receipt_name" value="${escapeHtml(expense?.receipt_name || "")}" /></div>
          <div class="field full"><label>Description</label><textarea name="description" required>${escapeHtml(expense?.description || "")}</textarea></div>
          <div class="field full"><label>Receipt Data URL (optional)</label><textarea name="receipt_data">${escapeHtml(expense?.receipt_data || "")}</textarea></div>
          <div class="field full"><div class="button-row"><button class="button-secondary" type="submit" value="draft">${expense ? "Save Draft" : "Save as Draft"}</button><button class="button" type="submit" value="submit">${expense && isDraft ? "Submit for Approval" : "Submit Expense"}</button><button class="button-secondary" type="button" data-route="my-expenses">Back to My Expenses</button></div></div>
        </form>
      </div>
      <div class="panel">
        <div class="page-head"><div><span class="badge">Flow</span><h3>How this request will move</h3></div></div>
        <div class="timeline">
          <div class="timeline-step"><strong>Draft</strong><p>Employee can save and edit before submission.</p></div>
          <div class="timeline-step"><strong>Waiting Approval</strong><p>Manager reviews first, then configured approvers continue the workflow.</p></div>
          <div class="timeline-step"><strong>Approved / Rejected</strong><p>Final outcome becomes visible on the employee table and locks edits.</p></div>
        </div>
      </div>
    </section>
  `;
}

function renderExpensesPage(title, expenses, ownerView) {
  return `
    <section class="table-card">
      <div class="page-head">
        <div><span class="badge">Expenses</span><h3>${title}</h3></div>
        ${ownerView ? `<button class="button" data-route="submit-expense">Submit Expense</button>` : ""}
      </div>
      ${renderExpenseTable(expenses, ownerView)}
    </section>
  `;
}

function renderExpenseDetailsPage(expense) {
  if (!expense) return `<section class="panel"><div class="empty">Expense not found.</div></section>`;
  return `
    <section class="split-grid">
      <div class="panel">
        <div class="page-head">
          <div><span class="badge">Expense #${expense.id}</span><h3>${escapeHtml(expense.category)}</h3></div>
          <span class="status ${expense.display_status.toLowerCase()}">${expense.display_status}</span>
        </div>
        <div class="list-stack">
          <div class="notice">Employee: ${escapeHtml(expense.employee_name)}</div>
          <div class="notice">Amount: ${formatMoney(expense.amount, expense.currency)}</div>
          <div class="notice">Converted: ${formatMoney(expense.converted_amount, expense.base_currency)}</div>
          <div class="notice">Vendor: ${escapeHtml(expense.vendor)}</div>
          <div class="notice">Date: ${escapeHtml(expense.expense_date)}</div>
          <div class="notice">${escapeHtml(expense.description)}</div>
        </div>
        <div class="inline-actions">
          ${state.auth.user.role === "EMPLOYEE" && expense.is_draft ? `<button class="button-secondary" data-route="submit-expense" data-id="${expense.id}">Edit</button>` : ""}
          ${state.auth.user.role === "EMPLOYEE" && expense.is_draft ? `<button class="button-danger" data-action="delete-expense" data-id="${expense.id}">Delete</button>` : ""}
        </div>
      </div>
      <div class="panel">
        <div class="page-head"><div><span class="badge">Timeline</span><h3>Approval progress</h3></div></div>
        <div class="timeline">
          ${expense.approvals.map((approval) => `<div class="timeline-step"><strong>Step ${approval.step_order}: ${approval.approver_role}</strong><p>${escapeHtml(approval.approver_name || "Unassigned")} | ${approval.status}${approval.comment ? ` | ${escapeHtml(approval.comment)}` : ""}</p></div>`).join("")}
        </div>
      </div>
    </section>
  `;
}

function renderPendingApprovalsPage(approvals) {
  return `
    <section class="table-card">
      <div class="page-head"><div><span class="badge">Queue</span><h3>Pending approvals</h3></div></div>
      ${renderApprovalsTable(approvals)}
    </section>
  `;
}

function renderApprovalHistoryPage(approvals) {
  return `
    <section class="table-card">
      <div class="page-head"><div><span class="badge">History</span><h3>Approval history</h3></div></div>
      ${renderApprovalHistoryTable(approvals)}
    </section>
  `;
}

function renderReportsPage(data) {
  const summary = data?.summary || {};
  return `
    <section class="report-grid">
      <div class="panel">
        <span class="badge">Summary</span>
        <div class="stats-grid">
          <div class="metric-card"><span class="helper">Approved Total</span><strong>${formatMoney(summary.approved_total || 0, state.auth.company.base_currency)}</strong></div>
          <div class="metric-card"><span class="helper">Pending Total</span><strong>${formatMoney(summary.pending_total || 0, state.auth.company.base_currency)}</strong></div>
          <div class="metric-card"><span class="helper">Approved Count</span><strong>${summary.approved_count || 0}</strong></div>
          <div class="metric-card"><span class="helper">Pending Count</span><strong>${summary.pending_count || 0}</strong></div>
        </div>
      </div>
      <div class="panel">${renderKeyValueList("Monthly", data?.monthly || {})}</div>
      <div class="panel">${renderKeyValueList("Categories", data?.categories || {})}</div>
      <div class="panel">${renderKeyValueList("Employees", data?.employees || {})}</div>
    </section>
  `;
}

function renderAuditLogsPage(logs) {
  return `
    <section class="table-card">
      <div class="page-head"><div><span class="badge">Audit</span><h3>Audit logs</h3></div></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Description</th></tr></thead>
          <tbody>
            ${logs.length ? logs.map((log) => `<tr><td>${formatDateTime(log.created_at)}</td><td>${escapeHtml(log.actor_name || "System")}</td><td>${escapeHtml(log.action)}</td><td>${escapeHtml(`${log.target_type} ${log.target_id || ""}`)}</td><td>${escapeHtml(log.description)}</td></tr>`).join("") : `<tr><td colspan="5"><div class="empty">No audit entries yet.</div></td></tr>`}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderProfilePage(data) {
  const profile = data?.profile || state.auth.user;
  const verificationLabel = profile.email_verified ? "Verified" : "Pending Verification";
  return `
    <section class="split-grid">
      <div class="panel">
        <div class="page-head"><div><span class="badge">Profile</span><h3>Update your account</h3></div></div>
        <form id="profile-form" class="form-grid">
          <div class="field"><label>Name</label><input name="name" value="${escapeHtml(profile.name)}" required /></div>
          <div class="field"><label>Email</label><input name="email" type="email" value="${escapeHtml(profile.email)}" required /></div>
          <div class="field"><label>Department</label><input name="department" value="${escapeHtml(profile.department || "")}" required /></div>
          <div class="field"><label>New Password</label><input name="password" type="password" minlength="8" /></div>
          <div class="field full"><button class="button" type="submit">Save Profile</button></div>
        </form>
      </div>
      <div class="panel">
        <div class="page-head"><div><span class="badge">Access</span><h3>Current workspace</h3></div></div>
        <div class="list-stack">
          <div class="notice">Role: ${escapeHtml(profile.role)}</div>
          <div class="notice">Email Status: <span class="status ${profile.email_verified ? "verified" : "unverified"}">${verificationLabel}</span></div>
          <div class="notice">Company: ${escapeHtml(state.auth.company.name)}</div>
          <div class="notice">Base Currency: ${escapeHtml(state.auth.company.base_currency)}</div>
          ${profile.email_verified ? "" : `<div class="notice"><button class="button-secondary" data-action="resend-current-verification">Resend verification email</button></div>`}
        </div>
      </div>
    </section>
  `;
}

function renderCountryOptions(selectedName) {
  return (state.bootstrap?.countries || [])
    .map((country) => `<option value="${country.name}" ${country.name === selectedName ? "selected" : ""}>${escapeHtml(country.name)}</option>`)
    .join("");
}

function currencyForCountryName(countryName) {
  return (state.bootstrap?.countries || []).find((country) => country.name === countryName)?.currency || "USD";
}

function renderExpenseTable(expenses, ownerView) {
  if (!expenses.length) return `<div class="empty">No expenses available yet.</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>ID</th><th>Owner</th><th>Description</th><th>Date</th><th>Paid By</th><th>Amount</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>
          ${expenses
            .map(
              (expense) => `
              <tr>
                <td>#${expense.id}</td>
                <td>${escapeHtml(expense.employee_name || state.auth.user.name)}</td>
                <td>${escapeHtml(expense.description || expense.category || "-")}</td>
                <td>${escapeHtml(expense.expense_date)}</td>
                <td>${escapeHtml(expense.vendor || "-")}</td>
                <td>${formatMoney(expense.amount, expense.currency)}</td>
                <td><span class="status ${expense.display_status.toLowerCase()}">${expense.display_status}</span></td>
                <td>
                  <div class="inline-actions">
                    <button class="button-secondary" data-route="expense-details" data-id="${expense.id}">View</button>
                    ${ownerView && expense.is_draft ? `<button class="button-secondary" data-route="submit-expense" data-id="${expense.id}">Edit</button>` : ""}
                  </div>
                </td>
              </tr>
            `
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderApprovalsTable(approvals) {
  if (!approvals.length) return `<div class="empty">No pending approvals right now.</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Approval Status</th><th>Request Owner</th><th>Category</th><th>Request Status</th><th>Total Amount</th><th>Current Step</th><th>Actions</th></tr></thead>
        <tbody>
          ${approvals
            .map(
              (approval) => `
              <tr>
                <td><span class="status pending">${approval.status}</span></td>
                <td>${escapeHtml(approval.employee_name)}</td>
                <td>${escapeHtml(approval.category || "-")}</td>
                <td>${escapeHtml(approval.expense_status || "-")}</td>
                <td>${formatMoney(approval.amount, approval.currency)}</td>
                <td>${approval.step_order} | ${approval.approver_role}</td>
                <td>
                  <div class="inline-actions">
                    <button class="button" data-action="approval" data-mode="approve" data-id="${approval.id}">Approve</button>
                    <button class="button-danger" data-action="approval" data-mode="reject" data-id="${approval.id}">Reject</button>
                    <button class="button-secondary" data-route="expense-details" data-id="${approval.expense_id}">View</button>
                  </div>
                </td>
              </tr>
            `
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderApprovalHistoryTable(approvals) {
  if (!approvals.length) return `<div class="empty">No approval history yet.</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Expense</th><th>Employee</th><th>Decision</th><th>Request Status</th><th>Step</th><th>Comment</th><th>At</th></tr></thead>
        <tbody>
          ${approvals
            .map(
              (approval) => `
              <tr>
                <td>#${approval.expense_id}</td>
                <td>${escapeHtml(approval.employee_name)}</td>
                <td><span class="status ${approval.status.toLowerCase()}">${approval.status}</span></td>
                <td>${escapeHtml(approval.expense_status || "-")}</td>
                <td>${approval.step_order} | ${approval.approver_role}</td>
                <td>${escapeHtml(approval.comment || "-")}</td>
                <td>${formatDateTime(approval.action_date)}</td>
              </tr>
            `
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderUserTable(users) {
  if (!users.length) return `<div class="empty">No users created yet.</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Name</th><th>Email</th><th>Verification</th><th>Role</th><th>Department</th><th>Status</th><th>Manager</th><th>Actions</th></tr></thead>
        <tbody>
          ${users
            .map(
              (user) => `
              <tr>
                <td>${escapeHtml(user.name)}</td>
                <td>${escapeHtml(user.email)}</td>
                <td><span class="status ${user.email_verified ? "verified" : "unverified"}">${user.email_verified ? "Verified" : "Pending"}</span></td>
                <td>${escapeHtml(user.role)}</td>
                <td>${escapeHtml(user.department)}</td>
                <td><span class="status ${user.status.toLowerCase()}">${user.status}</span></td>
                <td>${escapeHtml(user.manager_name || "-")}</td>
                <td>${user.role !== "ADMIN" ? `<button class="button-secondary" data-action="toggle-user-status" data-id="${user.id}">${user.status === "ACTIVE" ? "Deactivate" : "Activate"}</button>` : ""}</td>
              </tr>
            `
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderFeed(items, field) {
  if (!items.length) return `<div class="empty">No updates yet.</div>`;
  return `
    <div class="list-stack">
      ${items
        .map((item) => `<div class="feed-item"><strong>${escapeHtml(item[field] || item.description || "Update")}</strong><p>${formatDateTime(item.created_at || item.action_date)}</p></div>`)
        .join("")}
    </div>
  `;
}

function renderKeyValueList(title, values) {
  const entries = Object.entries(values);
  return `
    <span class="badge">${title}</span>
    <div class="list-stack">
      ${entries.length ? entries.map(([label, value]) => `<div class="notice"><strong>${escapeHtml(label)}</strong><p>${formatMoney(value, state.auth.company.base_currency)}</p></div>`).join("") : `<div class="empty">No data yet.</div>`}
    </div>
  `;
}

function updateToast() {
  if (!toastRoot) return;
  toastRoot.innerHTML = state.toast ? `<div class="toast"><strong>${escapeHtml(state.toast.message)}</strong></div>` : "";
}

async function handleClick(event) {
  const routeTarget = event.target.closest("[data-route]");
  if (routeTarget) {
    setRoute(routeTarget.dataset.route, routeTarget.dataset.id ? { id: routeTarget.dataset.id } : {});
    return;
  }

  const actionTarget = event.target.closest("[data-action]");
  if (!actionTarget) return;
  const action = actionTarget.dataset.action;

  try {
    if (action === "toggle-theme") {
      state.theme = state.theme === "dark" ? "light" : "dark";
      localStorage.setItem("reima-theme", state.theme);
      applyTheme();
      render();
      return;
    }

    if (action === "logout") {
      await api("/api/auth/logout", { method: "POST", body: "{}" });
      state.auth = null;
      state.cache = {};
      await bootstrap();
      setRoute("landing");
      showToast("Logged out successfully.");
      return;
    }

    if (action === "approval") {
      const mode = actionTarget.dataset.mode;
      const comment = window.prompt(mode === "approve" ? "Optional approval comment" : "Rejection comment");
      if (mode === "reject" && !comment) return;
      await api(`/api/approvals/${actionTarget.dataset.id}/${mode === "approve" ? "approve" : "reject"}`, {
        method: "POST",
        body: JSON.stringify({ comment: comment || "" })
      });
      showToast(`Expense ${mode}d successfully.`);
      await render();
      return;
    }

    if (action === "toggle-user-status") {
      await api(`/api/users/${actionTarget.dataset.id}/status`, { method: "PATCH", body: "{}" });
      showToast("User status updated.");
      await render();
      return;
    }

    if (action === "resend-current-verification") {
      await api("/api/auth/request-verification", {
        method: "POST",
        body: JSON.stringify({ email: state.auth.user.email })
      });
      showToast("Verification email sent.");
      return;
    }

    if (action === "move-step") {
      await api(`/api/workflow/steps/${actionTarget.dataset.id}/move`, {
        method: "POST",
        body: JSON.stringify({ direction: actionTarget.dataset.direction })
      });
      showToast("Approval step moved.");
      await render();
      return;
    }

    if (action === "toggle-step") {
      await api(`/api/workflow/steps/${actionTarget.dataset.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_mandatory: actionTarget.dataset.mandatory === "1" })
      });
      showToast("Approval step updated.");
      await render();
      return;
    }

    if (action === "delete-step") {
      if (!window.confirm("Delete this approval step?")) return;
      await api(`/api/workflow/steps/${actionTarget.dataset.id}`, { method: "DELETE", body: "{}" });
      showToast("Approval step deleted.");
      await render();
      return;
    }

    if (action === "delete-expense") {
      if (!window.confirm("Delete this pending expense?")) return;
      await api(`/api/expenses/${actionTarget.dataset.id}`, { method: "DELETE", body: "{}" });
      showToast("Expense deleted.");
      setRoute("my-expenses");
      await render();
    }
  } catch (error) {
    showToast(error.message, "danger");
  }
}

async function handleSubmit(event) {
  event.preventDefault();
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.workflow_action = event.submitter?.value || payload.workflow_action || "submit";

  try {
    if (form.id === "signup-form") {
      const data = await api("/api/auth/signup", { method: "POST", body: JSON.stringify(payload) });
      state.auth = null;
      showToast(data.message || "Company account created. Verify email before logging in.");
      setRoute("admin-login");
      await render();
      return;
    }
    if (form.id === "admin-login-form") {
      const data = await api("/api/auth/login-admin", { method: "POST", body: JSON.stringify(payload) });
      state.auth = data.auth;
      showToast("Admin login successful.");
      setRoute("dashboard");
      await render();
      return;
    }
    if (form.id === "staff-login-form") {
      const data = await api("/api/auth/login-staff", { method: "POST", body: JSON.stringify(payload) });
      state.auth = data.auth;
      showToast("Staff login successful.");
      setRoute("dashboard");
      await render();
      return;
    }
    if (form.id === "forgot-password-form") {
      const data = await api("/api/auth/forgot-password", { method: "POST", body: JSON.stringify(payload) });
      showToast(data.message || "If the account exists, a reset link has been sent.");
      setRoute("login-selector");
      await render();
      return;
    }
    if (form.id === "request-verification-form") {
      const data = await api("/api/auth/request-verification", { method: "POST", body: JSON.stringify(payload) });
      showToast(data.message || "Verification email sent.");
      setRoute("login-selector");
      await render();
      return;
    }
    if (form.id === "verify-email-form") {
      const data = await api("/api/auth/verify-email", { method: "POST", body: JSON.stringify(payload) });
      showToast(data.message || "Email verified.");
      setRoute("login-selector");
      await render();
      return;
    }
    if (form.id === "reset-password-form") {
      const data = await api("/api/auth/reset-password", { method: "POST", body: JSON.stringify(payload) });
      showToast(data.message || "Password reset successful.");
      setRoute("login-selector");
      await render();
      return;
    }
    if (form.id === "user-form") {
      const data = await api("/api/users", { method: "POST", body: JSON.stringify(payload) });
      form.reset();
      showToast(data.message || "User created successfully.");
      await render();
      return;
    }
    if (form.id === "expense-form") {
      const expenseId = form.dataset.expenseId;
      if (expenseId) {
        await api(`/api/expenses/${expenseId}`, { method: "PATCH", body: JSON.stringify(payload) });
        showToast("Expense updated.");
      } else {
        await api("/api/expenses", { method: "POST", body: JSON.stringify(payload) });
        showToast("Expense submitted.");
      }
      setRoute("my-expenses");
      await render();
      return;
    }
    if (form.id === "step-form") {
      payload.is_mandatory = payload.is_mandatory === "true";
      await api("/api/workflow/steps", { method: "POST", body: JSON.stringify(payload) });
      showToast("Approval step added.");
      await render();
      return;
    }
    if (form.id === "rule-form") {
      const type = String(payload.type || "").toUpperCase();
      if (["SPECIFIC", "HYBRID"].includes(type) && !payload.specific_user_id) {
        throw new Error("Specific approver is required for specific and hybrid rules.");
      }
      if (["PERCENTAGE", "HYBRID"].includes(type) && !payload.threshold_percentage) {
        throw new Error("Threshold percentage is required for percentage and hybrid rules.");
      }
      await api("/api/workflow/rule", { method: "PATCH", body: JSON.stringify(payload) });
      showToast("Approval rule updated.");
      await render();
      return;
    }
    if (form.id === "company-settings-form") {
      await api("/api/company/currency", { method: "PATCH", body: JSON.stringify(payload) });
      const refreshed = await api("/api/bootstrap");
      state.bootstrap = refreshed;
      state.auth = refreshed.auth || state.auth;
      showToast("Company settings updated.");
      await render();
      return;
    }
    if (form.id === "profile-form") {
      const data = await api("/api/profile", { method: "PATCH", body: JSON.stringify(payload) });
      const refreshed = await api("/api/bootstrap");
      state.bootstrap = refreshed;
      state.auth = refreshed.auth || state.auth;
      showToast(data.message || "Profile updated.");
      await render();
    }
  } catch (error) {
    showToast(error.message, "danger");
  }
}

function handleChange(event) {
  if (event.target.id === "country") {
    const currencyField = document.getElementById("signupBaseCurrency");
    if (currencyField) {
      currencyField.value = currencyForCountryName(event.target.value);
    }
    return;
  }

  if (event.target.id === "companyCountry") {
    const baseCurrencyField = document.getElementById("companyBaseCurrency");
    if (baseCurrencyField) {
      baseCurrencyField.value = currencyForCountryName(event.target.value);
    }
    return;
  }

  if (event.target.id === "ruleType") {
    updateRuleFormState();
  }
}

function syncDynamicInputs() {
  updateRuleFormState();
}

function updateRuleFormState() {
  const ruleType = document.getElementById("ruleType");
  const thresholdField = document.getElementById("ruleThreshold");
  const specificApproverField = document.getElementById("specificApprover");
  if (!ruleType || !thresholdField || !specificApproverField) return;
  const type = String(ruleType.value || "").toUpperCase();
  const needsThreshold = ["PERCENTAGE", "HYBRID"].includes(type);
  const needsSpecificApprover = ["SPECIFIC", "HYBRID"].includes(type);
  thresholdField.required = needsThreshold;
  thresholdField.disabled = !needsThreshold;
  specificApproverField.required = needsSpecificApprover;
}

function humanize(value) {
  return String(value).replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatMoney(value, currency) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency || state.auth?.company?.base_currency || "USD",
    maximumFractionDigits: 2
  }).format(Number(value || 0));
}

function formatDateTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

