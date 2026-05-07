"""
数据库连接配置

配置SQLAlchemy和数据库会话
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from typing import Generator

# 数据库Base
Base = declarative_base()


class Database:
    """数据库管理类"""

    def __init__(self, database_url: str):
        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,
            echo=False
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )

    def get_db(self) -> Generator:
        """
        获取数据库会话

        Yields:
            数据库会话
        """
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def create_tables(self):
        """创建所有表"""
        Base.metadata.create_all(bind=self.engine)

    def drop_tables(self):
        """删除所有表"""
        Base.metadata.drop_all(bind=self.engine)


# 全局数据库实例（将在main.py中初始化）
db: Database = None


def get_db() -> Generator:
    """获取数据库会话的依赖注入函数"""
    if db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    for session in db.get_db():
        yield session


def init_db(database_url: str):
    """初始化数据库"""
    global db
    db = Database(database_url)
    # 确保表存在
    db.create_tables()
