"""
应用配置

从环境变量加载配置
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置类"""

    # 应用信息
    APP_NAME: str = "PaperTracker Social"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # 数据库
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/papertracker_social"
    TEST_DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/papertracker_test"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # API密钥
    OPENAI_API_KEY: str = ""

    # 安全
    SECRET_KEY: str = "your-secret-key-here"

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def allowed_origins_list(self) -> list:
        """获取允许的来源列表"""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(',')]


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


# 全局配置实例
settings = get_settings()
