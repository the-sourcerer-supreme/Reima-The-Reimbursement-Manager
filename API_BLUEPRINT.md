# Reima API Blueprint

This prototype is static, but the backend shape is already mapped for the real implementation path.

## Suggested Stack

- Frontend: React or HTML/CSS/JS
- Backend: FastAPI or Flask
- Database: PostgreSQL
- ORM: SQLAlchemy
- Auth: custom email/password with JWT or secure session cookies

## Core Routes

### Auth

- `POST /auth/signup`
- `POST /auth/login`
- `POST /auth/logout`

### Users

- `POST /users`
- `GET /users`
- `PATCH /users/:id`
- `PATCH /users/:id/status`

### Expenses

- `POST /expenses`
- `GET /expenses/my`
- `GET /expenses`
- `GET /expenses/:id`
- `PATCH /expenses/:id`
- `DELETE /expenses/:id`

### Approvals

- `GET /approvals/pending`
- `GET /approvals/history`
- `POST /approvals/:id/approve`
- `POST /approvals/:id/reject`

### Workflow

- `GET /workflow`
- `POST /workflow/steps`
- `PATCH /workflow/steps/:id`
- `DELETE /workflow/steps/:id`
- `PATCH /workflow/rules`

### Currency + Reports

- `GET /currency/rates`
- `PATCH /currency/settings`
- `GET /reports/monthly`
- `GET /reports/category`
- `GET /reports/employee`
- `GET /reports/reimbursements`

### Audit + Notifications

- `GET /audit-logs`
- `GET /notifications`
- `PATCH /notifications/:id/read`

## Development Order

1. Database schema and migrations
2. Authentication and sessions
3. RBAC and route guards
4. Submit expense flow
5. Expense list and details
6. Approval engine and state transitions
7. Admin user management
8. Approval flow setup
9. Approval rule logic
10. Dashboard analytics
11. Reports export
12. OCR integration
13. Audit logs
14. UI polish
