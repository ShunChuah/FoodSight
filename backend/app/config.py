import os

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT") or 5432)
DB_NAME = os.getenv("DB_NAME", "foodsight")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

FRONTEND_URL = os.getenv("FRONTEND_URL") or "http://localhost:5173"
BACKEND_URL = os.getenv("BACKEND_URL") or "http://localhost:8000"
CORS_ORIGINS = (os.getenv("CORS_ORIGINS") or FRONTEND_URL).split(",")

AUTH_SECRET = os.environ["AUTH_SECRET"]
SESSION_LIFETIME_SECONDS = 60 * 60
EMAIL_LINK_LIFETIME_SECONDS = 15 * 60
COOKIE_NAME = "foodsight_session"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

SMTP_HOST = os.getenv("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT = int(os.getenv("SMTP_PORT") or 587)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
MAIL_FROM = os.getenv("MAIL_FROM") or SMTP_USER

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
