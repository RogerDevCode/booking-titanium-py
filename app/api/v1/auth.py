from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    role: str
    provider_id: Optional[int] = None

@router.post("/auth/login")
async def login(req: LoginRequest, request: Request):
    container = request.app.state.container
    user = await container.auth_service.authenticate_web_user(req.email, req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    token = container.auth_service.generate_jwt(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        provider_id=user["provider_id"]
    )
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "role": user["role"],
            "provider_id": user["provider_id"]
        }
    }

@router.post("/auth/register")
async def register(req: RegisterRequest, request: Request):
    container = request.app.state.container
    if req.role not in ["admin", "provider"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role"
        )
    
    try:
        user = await container.auth_service.register_web_user(
            email=req.email,
            password=req.password,
            role=req.role,
            provider_id=req.provider_id
        )
        return {"status": "success", "user": user}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Registration failed: {e}"
        )
