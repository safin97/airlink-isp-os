import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://airlink@/airlink")
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    secret: str = os.getenv("AIRLINK_JWT_SECRET", "")
    encryption_key: str = os.getenv("AIRLINK_ENCRYPTION_KEY", "")
    bootstrap_token: str = os.getenv("AIRLINK_BOOTSTRAP_TOKEN", "")
    secure_cookies: bool = os.getenv("AIRLINK_SECURE_COOKIES", "true") == "true"
    testing: bool = os.getenv("AIRLINK_TESTING", "false") == "true"
    broker_socket: str = os.getenv("AIRLINK_BROKER_SOCKET", "/run/airlink/control.sock")
    access_seconds: int = 900

    def validate(self):
        if len(self.secret) < 48:
            raise RuntimeError("AIRLINK_JWT_SECRET must have at least 48 random characters")
        from cryptography.fernet import Fernet
        Fernet(self.encryption_key.encode())


settings = Settings()
