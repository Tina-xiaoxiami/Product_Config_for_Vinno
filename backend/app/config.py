"""
应用配置
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""
    app_name: str = "产品配置管理系统"
    debug: bool = True

    class Config:
        env_file = ".env"


settings = Settings()