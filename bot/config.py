import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "").rstrip("/")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_JWT_KID = os.getenv("SUPABASE_JWT_KID", "")
SUPABASE_PROJECT_REF = os.getenv("SUPABASE_PROJECT_REF", "")

if not SUPABASE_PROJECT_REF and SUPABASE_URL:
    host = SUPABASE_URL.split("//", 1)[-1].split("/", 1)[0]
    SUPABASE_PROJECT_REF = host.split(".", 1)[0]


def is_webhook_mode() -> bool:
    return bool(WEBHOOK_BASE_URL)


def has_jwt_secret() -> bool:
    return bool(SUPABASE_JWT_SECRET)
