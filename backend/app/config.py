from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    solar_api_key: str = ""
    solar_base_url: str = "https://api.upstage.ai/v1/solar"
    solar_model: str = "solar-pro"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
