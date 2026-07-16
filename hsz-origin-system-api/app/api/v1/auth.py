from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
def auth_status() -> None:
    raise HTTPException(status_code=501, detail="认证接口待接入")
