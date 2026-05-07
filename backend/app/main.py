"""
FastAPI主应用

PaperTracker Social后端服务入口
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.database import init_db

# 创建API实例
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="学术论文写作自动化Web应用后端服务",
    debug=settings.DEBUG
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 导入路由
from app.api.v1 import journals, tasks, websocket, topic_selection

# 注册路由
app.include_router(journals.router)
app.include_router(tasks.router)
app.include_router(websocket.router)
app.include_router(topic_selection.router)


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    print(f"[START] {settings.APP_NAME} v{settings.APP_VERSION} starting...")
    print(f"[DEBUG] Debug mode: {settings.DEBUG}")
    print(f"[CORS] Allowed origins: {settings.allowed_origins_list}")

    # 初始化数据库连接
    init_db(settings.DATABASE_URL)


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    print(f"[STOP] {settings.APP_NAME} shutting down...")


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": settings.APP_NAME
    }
