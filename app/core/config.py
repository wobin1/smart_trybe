from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/smart_trybe_compliance"
    upload_dir: str = "./uploads"

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    jwt_secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    admin_emails: str = ""
    public_api_base_url: str = "http://localhost:8000"

    google_client_id: str = ""

    # Paystack (set PAYMENT_DEV_MODE=true to allow manual POST /cart/.../pay without Paystack)
    paystack_secret_key: str = ""
    paystack_public_key: str = ""
    payment_dev_mode: bool = True
    paystack_callback_url: str = ""

    # Zoho Flow — outbound webhooks for email/SMS automations (one URL per event, or leave blank to skip)
    zoho_flow_webhook_payment: str = ""
    zoho_flow_webhook_workflow_submitted: str = ""
    zoho_flow_webhook_agent_assigned: str = ""
    zoho_flow_webhook_workflow_completed: str = ""
    zoho_flow_webhook_secret: str = ""

    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def cloudinary_configured(self) -> bool:
        return bool(
            self.cloudinary_cloud_name
            and self.cloudinary_api_key
            and self.cloudinary_api_secret
        )


settings = Settings()
