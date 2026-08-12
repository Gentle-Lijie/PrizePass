from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import get_settings
from .errors import install_error_handlers


settings = get_settings()
app = FastAPI(title="PrizePass", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.public_base_url],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Content-Type", "X-Admin-Password", "X-Redemption-Code"],
)
app.include_router(router)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir, check_dir=False), name="uploads")
install_error_handlers(app)
