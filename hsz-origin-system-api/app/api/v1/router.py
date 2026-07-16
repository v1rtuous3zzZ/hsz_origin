from fastapi import APIRouter, Depends

from app.api.v1 import auth, etl, reports, system
from app.core.security import require_access_token

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(etl.router, dependencies=[Depends(require_access_token)])
api_router.include_router(reports.router, dependencies=[Depends(require_access_token)])
api_router.include_router(system.router, dependencies=[Depends(require_access_token)])
