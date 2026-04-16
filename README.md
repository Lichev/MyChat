# MyChat

A real-time chat application built with Django, Django Channels, and WebSockets. Supports public chat rooms, user profiles, and a friend system.

---

## Tech Stack

- **Backend:** Python 3.10+, Django 4.2, Django Channels 4.1, Daphne (ASGI)
- **Database:** PostgreSQL
- **Real-time:** WebSockets via Django Channels
- **Channel layer:** Redis (recommended for production) or in-memory (dev only)
- **Media/uploads:** Pillow

---

## Prerequisites

Install the following before starting:

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.10+ | [python.org](https://www.python.org/downloads/) |
| PostgreSQL | 14+ | [postgresql.org](https://www.postgresql.org/download/) |
| Redis | 6+ | Optional — only needed for multi-process/production WebSocket support |
| pip | latest | Comes with Python |

---

## 1. Clone the Repository

```bash
git clone <your-repo-url>
cd MyChat
```

---

## 2. Create and Activate a Virtual Environment

```bash
# Create
python -m venv venv

# Activate — Windows
venv\Scripts\activate

# Activate — Linux/macOS
source venv/bin/activate
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

> If you are **not** using Redis, `channels_redis` is still listed in requirements but won't be used unless you set `REDIS_URL`. It will install without issue.

---

## 4. Set Up Environment Variables

Copy the example file and fill it in:

```bash
cp .env.example .env
```

Then open `.env` and edit every value:

```env
# Django
SECRET_KEY=some-long-random-string-here   # generate with: python -c "from django.core.signing import get_cookie_signer; print(get_cookie_signer().key)"
DEBUG=True                                 # set to False in production
ALLOWED_HOSTS=127.0.0.1 localhost

# PostgreSQL
DB_NAME=mychat
DB_USER=mychat_user
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# Email (you can use Gmail SMTP or leave blank during development)
EMAIL_FROM_USER=noreply@yourdomain.com
EMAIL_HOST=smtp.gmail.com
EMAIL_HOST_USER=your@gmail.com
EMAIL_HOST_PASSWORD=your_app_password
EMAIL_USE_TLS=True
EMAIL_PORT=587

# Redis (leave commented out for in-memory dev mode)
# REDIS_URL=redis://localhost:6379/0

LOG_LEVEL=DEBUG
```

> **Generating a SECRET_KEY** — run this in your terminal:
> ```bash
> python -c "import secrets; print(secrets.token_urlsafe(50))"
> ```

---

## 5. Set Up the PostgreSQL Database

### 5a. Install PostgreSQL

```bash
sudo apt install postgresql postgresql-contrib
```

### 5b. Start PostgreSQL

PostgreSQL does **not** start automatically — you must start it manually each session:

```bash
sudo service postgresql start
```

Verify it is running:

```bash
sudo service postgresql status
```

You should see `Active: active`. If you want it to start automatically every time you open WSL, add this to your `~/.bashrc`:

```bash
sudo service postgresql start > /dev/null 2>&1
```

### 5c. Create the database and user

Connect as the PostgreSQL superuser:

```bash
sudo -u postgres psql
```

Inside psql, run:

```sql
CREATE DATABASE mychat;
CREATE USER mychat_user WITH PASSWORD 'your_password';
ALTER ROLE mychat_user SET client_encoding TO 'utf8';
ALTER ROLE mychat_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE mychat_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE mychat TO mychat_user;
\q
```

### 5d. Grant schema permissions (PostgreSQL 15+)

PostgreSQL 15 and later removed default write access to the `public` schema. You must grant it explicitly, connected to the **mychat** database specifically:

```bash
sudo -u postgres psql -d mychat
```

Inside psql:

```sql
GRANT ALL ON SCHEMA public TO mychat_user;
\q
```

> **Note:** This step is easy to miss. Without it, `python manage.py migrate` will fail with `permission denied for schema public`.

### 5e. Verify the connection

Check PostgreSQL is on the expected port:

```bash
sudo -u postgres psql -c "SHOW port;"
```

Should output `5432` — matching `DB_PORT` in your `.env`.

Make sure the `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT` values in your `.env` match what you just created.

---

## 6. Apply Database Migrations

```bash
python manage.py migrate
```

This creates all tables including the custom user model (`USERS.ChatUser`), chat rooms, messages, and friend relationships.

---

## 7. Create a Superuser

```bash
python manage.py createsuperuser
```

You will be prompted for a username, email, and password. Use these credentials to log in to the Django admin at `/admin/`.

> **Note:** The custom user model requires `first_name`, `last_name`, and `email`. The `createsuperuser` command will prompt for all of them.

---

## 8. Collect Static Files (Production Only)

For development, Django serves static files automatically. For production:

```bash
python manage.py collectstatic
```

---

## 9. Run the Development Server

This project uses **Daphne** (ASGI server) to support WebSockets. Do **not** use `runserver` — it does not support WebSockets properly.

```bash
daphne -b 127.0.0.1 -p 8000 MyChat.asgi:application
```

The app will be available at: **http://127.0.0.1:8000**

> Alternatively, during development Django's `runserver` will also work for basic testing (it has limited ASGI/WebSocket support in Django 4.2):
> ```bash
> python manage.py runserver
> ```

---

## 10. Access the Application

| URL | Description |
|-----|-------------|
| `http://127.0.0.1:8000/` | Home page |
| `http://127.0.0.1:8000/accounts/register/` | Register a new account |
| `http://127.0.0.1:8000/accounts/login/` | Log in |
| `http://127.0.0.1:8000/rooms/` | Public chat rooms |
| `http://127.0.0.1:8000/admin/` | Django admin |

---

## Email Verification

When a user registers, they receive an activation email. During development:

- If you do not want to configure real SMTP, switch the email backend in `.env` or directly in `settings.py` to print emails to the console:

  ```python
  # In MyChat/settings.py (temporary, dev only)
  EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
  ```

  Activation links will be printed to your terminal instead of sent.

---

## Redis (Optional — Production WebSockets)

For production or running multiple Daphne workers, set `REDIS_URL` in your `.env`:

```env
REDIS_URL=redis://localhost:6379/0
```

Start Redis:
```bash
# Linux/macOS
redis-server

# Windows (with WSL or Redis for Windows)
redis-server
```

Without `REDIS_URL`, the app falls back to `InMemoryChannelLayer` which only works with a **single** process.

---

## Project Structure

```
MyChat/
├── MyChat/              # Project config (settings, urls, asgi, wsgi)
├── USERS/               # User auth, profiles, email verification
├── CORE/                # Home page, contact form
├── FRIEND/              # Friend requests and relationships
├── CHAT_ROOMS/          # Public chat rooms, WebSocket consumer
├── templates/           # HTML templates
├── static/              # CSS, JS, images
├── media/               # User-uploaded files (profile pictures, room images)
├── requirements.txt
├── .env.example
└── manage.py
```

---

## Common Issues

### `ImproperlyConfigured: SECRET_KEY environment variable is not set`
You have not created your `.env` file or `SECRET_KEY` is missing. Follow Step 4.

### `django.db.utils.OperationalError: could not connect to server`
PostgreSQL is not running, or `DB_HOST`/`DB_PORT`/credentials in `.env` are wrong. Check Step 5.

### WebSocket connection refused
You are using `runserver` instead of `daphne`. Use the Daphne command from Step 9.

### Activation email not arriving
Set `EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'` in settings for development so tokens print to the terminal.

### `No module named 'channels_redis'`
Run `pip install -r requirements.txt` again inside your activated virtual environment.

---

## Development Workflow

```bash
# After pulling new changes
pip install -r requirements.txt   # in case new packages were added
python manage.py migrate           # in case new migrations were added
daphne -b 127.0.0.1 -p 8000 MyChat.asgi:application
```
