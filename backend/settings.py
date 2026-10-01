from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional, List
import os

class Settings(BaseSettings):
    gemini_api_key: str = Field(default="", env="GEMINI_API_KEY")
    
    # Range Checkers
    min_price: Optional[float] = Field(default=5000000.0, env="MIN_PRICE")
    max_price: Optional[float] = Field(default=500000000.0, env="MAX_PRICE")
    date_range_days: int = Field(default=26, env="DATE_RANGE_DAYS")
    reject_on_missing_value: bool = Field(default=True, env="REJECT_ON_MISSING_VALUE")
    reject_on_missing_date: bool = Field(default=False, env="REJECT_ON_MISSING_DATE")

    # TenderDetail Keywords
    tenderdetail_keywords: str = Field(default="Cctv, cc, smart City gift city", env="TENDERDETAIL_KEYWORDS")
    ireps_keywords: str = Field(default="CCTV, IT, Telecom", env="IREPS_KEYWORDS")
    ireps_department: str = Field(default="S AND T", env="IREPS_DEPARTMENT")
    ireps_railway_pu: str = Field(default="", env="IREPS_RAILWAY_PU")
    gem_keywords: str = Field(default="CCTV, Hardware, Software", env="GEM_KEYWORDS")

    # nProcure Options
    nprocure_client_name: str = Field(default="Surat Municipal Corporation", env="NPROCURE_CLIENT_NAME")

    # Document Mapping Defaults
    default_company: str = Field(default="Arkonic", env="DEFAULT_COMPANY")

    # Lark Configs
    lark_mode: str = Field(default="noop", env="LARK_MODE")
    lark_app_id: str = Field(default="", env="LARK_APP_ID")
    lark_app_secret: str = Field(default="", env="LARK_APP_SECRET")
    lark_receive_id: str = Field(default="", env="LARK_RECEIVE_ID")
    lark_receive_id_type: str = Field(default="chat_id", env="LARK_RECEIVE_ID_TYPE")
    lark_webhook_url: str = Field(default="", env="LARK_WEBHOOK_URL")
    
    # Scraper Enables
    enable_mock_site: bool = Field(default=True, env="ENABLE_MOCK_SITE")
    enable_ireps: bool = Field(default=False, env="ENABLE_IREPS")
    enable_gem: bool = Field(default=False, env="ENABLE_GEM")
    enable_nprocure: bool = Field(default=True, env="ENABLE_NPROCURE")

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), ".env"),
        env_file_encoding='utf-8',
        extra="ignore"
    )

settings = Settings()
