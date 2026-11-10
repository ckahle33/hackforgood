from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    site_name: str = "Hack for Good"
    site_url: str = ""  # e.g. https://example.org, used for canonical links and the sitemap
    secret_key: str = "dev-only-change-me"
    database_url: str = "sqlite:///./dev.db"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    admin_emails: str = ""
    resend_api_key: str = ""
    mail_from: str = "Hack for Good <jobs@hackforgood.dev>"
    mail_address: str = ""  # physical mailing address; required in commercial email (CAN-SPAM)
    mail_daily_limit: int = 100  # Resend free tier
    cron_secret: str = ""
    https_only: bool = False

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    @property
    def admins(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
