from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from typing import Optional
from app.middleware.auth import get_current_user, require_role

router = APIRouter()

# --- Pydantic Schemas ---
class SpecialtyCreate(BaseModel):
    name: str
    description: Optional[str] = None

class SpecialtyUpdate(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True

class ProviderCreate(BaseModel):
    name: str
    specialty_id: int
    bio: Optional[str] = None
    slot_duration_minutes: int = 30
    buffer_time_minutes: int = 0
    notice_period_hours: int = 4

class ProviderUpdate(BaseModel):
    name: str
    specialty_id: int
    bio: Optional[str] = None
    slot_duration_minutes: int = 30
    buffer_time_minutes: int = 0
    notice_period_hours: int = 4
    is_active: bool = True

class KBCreate(BaseModel):
    provider_id: Optional[int] = None
    title: str
    category: str
    content: str

class KBUpdate(BaseModel):
    title: str
    category: str
    content: str
    is_active: bool = True

# --- SPECIALTIES ENDPOINTS ---
@router.get("/admin/specialties")
async def list_specialties(request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.state.container.db_client
    rows = await db.fetch("SELECT id, name, description, is_active FROM specialties ORDER BY id DESC")
    return [dict(r) for r in rows]

@router.post("/admin/specialties", dependencies=[Depends(require_role(["admin"]))])
async def create_specialty(req: SpecialtyCreate, request: Request):
    db = request.app.state.container.db_client
    try:
        row = await db.fetchrow(
            "INSERT INTO specialties (name, description) VALUES ($1, $2) RETURNING id, name, description, is_active",
            req.name, req.description
        )
        return dict(row)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/admin/specialties/{id}", dependencies=[Depends(require_role(["admin"]))])
async def update_specialty(id: int, req: SpecialtyUpdate, request: Request):
    db = request.app.state.container.db_client
    row = await db.fetchrow(
        "UPDATE specialties SET name = $1, description = $2, is_active = $3, updated_at = NOW() WHERE id = $4 RETURNING id, name, description, is_active",
        req.name, req.description, req.is_active, id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Specialty not found")
    return dict(row)

# --- PROVIDERS ENDPOINTS ---
@router.get("/admin/providers")
async def list_providers(request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.state.container.db_client
    
    # If the user is a provider, enforce RLS and limit details
    prov_id = current_user.get("provider_id")
    if current_user["role"] == "provider" and prov_id:
        rows = await db.fetch("SELECT id, name, specialty_id, bio, is_active FROM providers WHERE id = $1", prov_id)
    else:
        rows = await db.fetch("SELECT id, name, specialty_id, bio, is_active FROM providers ORDER BY id DESC")
    return [dict(r) for r in rows]

@router.post("/admin/providers", dependencies=[Depends(require_role(["admin"]))])
async def create_provider(req: ProviderCreate, request: Request):
    db = request.app.state.container.db_client
    try:
        row = await db.fetchrow(
            """INSERT INTO providers (name, specialty_id, bio, slot_duration_minutes, buffer_time_minutes, notice_period_hours)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING id, name, specialty_id, bio, is_active""",
            req.name, req.specialty_id, req.bio, req.slot_duration_minutes, req.buffer_time_minutes, req.notice_period_hours
        )
        return dict(row)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/admin/providers/{id}")
async def update_provider(id: int, req: ProviderUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.state.container.db_client
    
    # Authorize: admin or the provider themselves
    if current_user["role"] == "provider" and current_user.get("provider_id") != id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    row = await db.fetchrow(
        """UPDATE providers 
           SET name = $1, specialty_id = $2, bio = $3, slot_duration_minutes = $4, buffer_time_minutes = $5, notice_period_hours = $6, is_active = $7, updated_at = NOW()
           WHERE id = $8
           RETURNING id, name, specialty_id, bio, is_active""",
        req.name, req.specialty_id, req.bio, req.slot_duration_minutes, req.buffer_time_minutes, req.notice_period_hours, req.is_active, id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    return dict(row)

# --- PATIENTS (USERS) SEARCH ENDPOINTS ---
@router.get("/admin/patients")
async def search_patients(request: Request, query: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    db = request.app.state.container.db_client
    
    # Query builder
    if query:
        # Search by RUT, phone or Name (using unaccent GIN index)
        # Search format
        q = f"%{query}%"
        sql = """
            SELECT id, username, first_name, last_name, phone, email, address, rut, is_active, is_blocked, blocked_until, noshow_count
            FROM users
            WHERE rut ILIKE $1 OR phone ILIKE $1 OR first_name ILIKE $1 OR last_name ILIKE $1
            ORDER BY first_name ASC
            LIMIT 50
        """
        rows = await db.fetch(sql, q)
    else:
        sql = """
            SELECT id, username, first_name, last_name, phone, email, address, rut, is_active, is_blocked, blocked_until, noshow_count
            FROM users
            ORDER BY first_name ASC
            LIMIT 50
        """
        rows = await db.fetch(sql)

    return [dict(r) for r in rows]

# --- KNOWLEDGE BASE ENDPOINTS ---
@router.get("/admin/kb")
async def list_kb(request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.state.container.db_client
    
    # Enforce RLS filtering for providers via RLS logic or explicit SQL
    prov_id = current_user.get("provider_id")
    if current_user["role"] == "provider" and prov_id:
        rows = await db.fetch("SELECT id, provider_id, title, category, content, is_active FROM knowledge_base WHERE provider_id = $1 ORDER BY id DESC", prov_id)
    else:
        rows = await db.fetch("SELECT id, provider_id, title, category, content, is_active FROM knowledge_base ORDER BY id DESC")
    return [dict(r) for r in rows]

@router.post("/admin/kb")
async def create_kb(req: KBCreate, request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.state.container.db_client
    
    # Enforce provider constraint
    target_prov_id = req.provider_id
    if current_user["role"] == "provider":
        target_prov_id = current_user.get("provider_id")

    try:
        row = await db.fetchrow(
            "INSERT INTO knowledge_base (provider_id, title, category, content) VALUES ($1, $2, $3, $4) RETURNING id, provider_id, title, category, content, is_active",
            target_prov_id, req.title, req.category, req.content
        )
        return dict(row)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/admin/kb/{id}")
async def update_kb(id: int, req: KBUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    db = request.app.state.container.db_client
    
    # If provider, check ownership
    if current_user["role"] == "provider":
        prov_id = current_user.get("provider_id")
        owner_check = await db.fetchrow("SELECT provider_id FROM knowledge_base WHERE id = $1", id)
        if not owner_check or owner_check["provider_id"] != prov_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    row = await db.fetchrow(
        "UPDATE knowledge_base SET title = $1, category = $2, content = $3, is_active = $4, updated_at = NOW() WHERE id = $5 RETURNING id, provider_id, title, category, content, is_active",
        req.title, req.category, req.content, req.is_active, id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Knowledge base entry not found")
    return dict(row)
