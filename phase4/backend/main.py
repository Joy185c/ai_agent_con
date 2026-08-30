"""
Phase 3 — Auth, Persistence & Hybrid BYOK

New in this phase:
  - Real user accounts (signup/login, JWT sessions)
  - Conversations & messages persisted per user
  - Hybrid key model:
      * By default, chat draws from the shared admin-managed pool (Phase 2),
        capped by a per-user daily fair-use quota (DEFAULT_DAILY_QUOTA)
      * Once that quota is hit, instead of an error, /chat emits a
        `quota_exceeded` SSE event with guided provider links. The frontend
        shows an inline card right there in the chat.
      * The user pastes their own free key via POST /user/keys — validated
        immediately. From then on, that user's requests use their own
        key(s) instead of the shared pool (and aren't subject to the daily
        cap), so they can resume the exact same conversation within seconds.
"""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

import auth
import db
import extraction
import key_pool
import providers
import rag

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
CHECK_INTERVAL_HOURS = int(os.environ.get("KEY_CHECK_INTERVAL_HOURS", "3"))
DEFAULT_DAILY_QUOTA = int(os.environ.get("DEFAULT_DAILY_QUOTA", "20"))

app = FastAPI(title="Personal AI Agent — Phase 3")

os.makedirs("uploads/about", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Serve the frontend folder as static assets
# ---------------------------------------------------------------------------
_FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")
_FRONTEND = os.path.normpath(_FRONTEND)

if os.path.isdir(_FRONTEND):
    app.mount("/static", StaticFiles(directory=_FRONTEND), name="static")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index():
    path = os.path.join(_FRONTEND, "index.html")
    if os.path.exists(path):
        return HTMLResponse(open(path, encoding="utf-8").read())
    return HTMLResponse("<h3>Frontend not found</h3>", status_code=404)


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def serve_admin():
    path = os.path.join(_FRONTEND, "admin.html")
    if os.path.exists(path):
        return HTMLResponse(open(path, encoding="utf-8").read())
    return HTMLResponse("<h3>admin.html not found</h3>", status_code=404)

scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup():
    db.init_db()
    scheduler.add_job(key_pool.test_all_keys, "interval", hours=CHECK_INTERVAL_HOURS)
    scheduler.start()


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown(wait=False)


@app.get("/health")
async def health():
    keys = db.list_keys()
    return {
        "status": "ok",
        "pool_size": len(keys),
        "active_keys": len([k for k in keys if k["status"] == "active"]),
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user_id: int
    email: str


@app.post("/auth/signup", response_model=AuthResponse)
async def signup(req: SignupRequest):
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if db.get_user_by_email(req.email):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user_id = db.create_user(req.email, auth.hash_password(req.password))
    return AuthResponse(token=auth.create_token(user_id), user_id=user_id, email=req.email)


@app.post("/auth/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    user = db.get_user_by_email(req.email)
    if not user or not auth.verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return AuthResponse(token=auth.create_token(user["id"]), user_id=user["id"], email=user["email"])


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

@app.get("/conversations")
async def get_conversations(user_id: int = Depends(auth.get_current_user_id)):
    return db.list_conversations(user_id)

class RenameConversationRequest(BaseModel):
    title: str


@app.get("/conversations/search")
async def search_conversations(
    q: str,
    user_id: int = Depends(auth.get_current_user_id),
):
    if not q or not q.strip():
        return []
    return db.search_conversations(user_id, q.strip())


@app.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: int,
    req: RenameConversationRequest,
    user_id: int = Depends(auth.get_current_user_id),
):
    title = req.title.strip()[:100]  # max 100 chars, strip whitespace
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    if not db.get_conversation(conversation_id, user_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.rename_conversation(conversation_id, user_id, title)
    return {"ok": True, "title": title}



@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: int, user_id: int = Depends(auth.get_current_user_id)):
    conv = db.get_conversation(conversation_id, user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {**conv, "messages": db.get_messages(conversation_id)}


@app.delete("/conversations/{conversation_id}")
async def remove_conversation(conversation_id: int, user_id: int = Depends(auth.get_current_user_id)):
    if not db.get_conversation(conversation_id, user_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete_conversation(conversation_id, user_id)
    return {"ok": True}


def _make_vision_fallback(user_id: int):
    """Builds the vision_fallback_fn extraction.py expects: an async
    callable(image_bytes) -> str. Prefers the user's own Gemini key (BYOK),
    falls back to a shared-pool Gemini key if the user hasn't added one."""

    async def _fallback(image_bytes: bytes) -> str:
        user_candidates = [c for c in db.active_user_keys_as_candidates(user_id, "vision") if c["provider"] == "gemini"]
        if not user_candidates:
            user_candidates = [c for c in db.active_user_keys_as_candidates(user_id, "text") if c["provider"] == "gemini"]
        if user_candidates:
            return await providers.gemini_vision_extract(user_candidates[0]["api_key"], image_bytes)

        shared_candidates = [c for c in db.active_keys("vision") if c["provider"] == "gemini"]
        if not shared_candidates:
            shared_candidates = [c for c in db.active_keys("text") if c["provider"] == "gemini"]
        if shared_candidates:
            return await providers.gemini_vision_extract(shared_candidates[0]["api_key"], image_bytes)

        return ""  # no Gemini key anywhere in reach — extraction.py handles this gracefully

    return _fallback


@app.post("/extract")
async def extract_file(file: UploadFile = File(...), user_id: int = Depends(auth.get_current_user_id)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    try:
        result = await extraction.extract_text(file.filename, data, vision_fallback_fn=_make_vision_fallback(user_id))
    except Exception as exc:  # noqa: BLE001 — surface any extraction failure as a clean 400
        raise HTTPException(status_code=400, detail=f"Could not process this file: {exc}")
    return {"filename": file.filename, **result}


class IngestDocumentRequest(BaseModel):
    filename: str
    text: str
    conversation_id: Optional[int] = None
    extraction_method: str = "manual"


@app.post("/documents")
async def confirm_document(req: IngestDocumentRequest, user_id: int = Depends(auth.get_current_user_id)):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")

    if req.conversation_id is None:
        conversation_id = db.create_conversation(user_id, req.filename[:40] or "Document chat")
    else:
        conv = db.get_conversation(req.conversation_id, user_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation_id = req.conversation_id

    doc_id = str(uuid.uuid4())
    chunk_count = rag.ingest_document(doc_id, user_id, conversation_id, req.text)
    db.add_document(doc_id, user_id, conversation_id, req.filename, req.extraction_method, chunk_count)
    return {"document_id": doc_id, "conversation_id": conversation_id, "chunk_count": chunk_count}


@app.get("/documents")
async def get_documents(conversation_id: int, user_id: int = Depends(auth.get_current_user_id)):
    return db.list_documents(conversation_id, user_id)


@app.delete("/documents/{doc_id}")
async def remove_document(doc_id: str, user_id: int = Depends(auth.get_current_user_id)):
    if not db.get_document(doc_id, user_id):
        raise HTTPException(status_code=404, detail="Document not found")
    rag.delete_document(doc_id)
    db.delete_document_row(doc_id, user_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Chat — now authenticated, persisted, quota/BYOK-aware, and RAG-aware
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None
    category: Literal["text", "vision"] = "text"
    document_id: Optional[str] = None


def _seconds_until_next_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds())


def _quota_bucket(user_id: int) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"user_quota:{user_id}:{day}"


async def stream_chat_response(user_id: int, conversation_id: int, user_message: str,
                                category: str, document_id: Optional[str] = None):
    # Banned users get a hard stop before any pool access.
    if db.is_user_banned(user_id):
        yield f"data: {json.dumps({'error': 'Your account has been suspended. Please contact support.'})}\n\n"
        return

    history = db.get_messages(conversation_id)
    plain_messages = [{"role": m["role"], "content": m["content"]} for m in history]

    effective_message = user_message
    if document_id:
        chunks = rag.retrieve_relevant_chunks(user_message, document_id, top_k=4)
        if chunks:
            context_block = "\n\n---\n\n".join(chunks)
            effective_message = (
                "Use the following context from the uploaded document to answer the question. "
                "If the answer isn't in the context, say so rather than guessing.\n\n"
                f"Context:\n{context_block}\n\nQuestion: {user_message}"
            )
    plain_messages.append({"role": "user", "content": effective_message})

    user_keys = db.active_user_keys_as_candidates(user_id, category)
    using_own_key = bool(user_keys)

    if not using_own_key:
        bucket = _quota_bucket(user_id)
        used = await key_pool.usage_store.get(bucket)
        effective_quota = db.get_effective_quota(user_id, DEFAULT_DAILY_QUOTA)
        if used >= effective_quota:
            try:
                db.increment_request_stat(None, category, "quota_exceeded")
            except Exception:
                pass
            quota_event = {
                "quota_exceeded": True,
                "message": "আজকের free limit শেষ। কাজ চালিয়ে যেতে নিজের key যোগ করুন।",
                "providers": [{"provider": p, "url": url} for p, url in providers.KEY_CREATION_LINKS.items()],
            }
            yield f"data: {json.dumps(quota_event)}\n\n"
            return

    full_text = ""
    try:
        candidates = user_keys if using_own_key else None
        async for chunk in key_pool.call_llm_with_fallback(plain_messages, category=category, candidates=candidates):
            full_text += chunk
            yield f"data: {json.dumps({'token': chunk})}\n\n"
    except key_pool.NoAvailableKeyError as exc:
        try:
            db.increment_request_stat(None, category, "error")
        except Exception:
            pass
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        return

    if not using_own_key:
        await key_pool.usage_store.incr_with_ttl(_quota_bucket(user_id), _seconds_until_next_utc_midnight())

    db.add_message(conversation_id, "user", user_message)
    db.add_message(conversation_id, "assistant", full_text)


@app.post("/chat")
async def chat(req: ChatRequest, user_id: int = Depends(auth.get_current_user_id)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    # Maintenance mode — only checked for shared-pool users (own-key users are unaffected).
    if db.get_setting("maintenance_mode", "0") == "1":
        if not db.active_user_keys_as_candidates(user_id, req.category):
            raise HTTPException(status_code=503,
                                detail="The service is currently in maintenance. Please try again later.")

    is_new_conversation = req.conversation_id is None
    if is_new_conversation:
        title = req.message.strip()[:40] or "New chat"
        conversation_id = db.create_conversation(user_id, title)
    else:
        conv = db.get_conversation(req.conversation_id, user_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation_id = req.conversation_id

    async def event_stream():
        if is_new_conversation:
            yield f"data: {json.dumps({'conversation_id': conversation_id})}\n\n"
        async for event in stream_chat_response(user_id, conversation_id, req.message, req.category, req.document_id):
            yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ---------------------------------------------------------------------------
# BYOK — a user's own keys
# ---------------------------------------------------------------------------

class AddUserKeyRequest(BaseModel):
    provider: Literal["groq", "openrouter", "gemini"]
    api_key: str
    category: Literal["text", "vision"] = "text"


@app.get("/user/keys")
async def list_my_keys(user_id: int = Depends(auth.get_current_user_id)):
    return db.list_user_keys(user_id)


@app.post("/user/keys")
async def add_my_key(req: AddUserKeyRequest, user_id: int = Depends(auth.get_current_user_id)):
    model = providers.DEFAULT_MODELS[req.provider]
    _, test_validity = providers.get_adapter(req.provider)
    result = await test_validity(req.api_key, model)
    if result != "valid":
        raise HTTPException(
            status_code=400,
            detail=f"This key didn't validate ({result}). Double check it and try again.",
        )
    key_id = db.add_user_key(user_id, req.provider, model, req.api_key, req.category)
    return {"id": key_id, "status": "valid"}


@app.delete("/user/keys/{key_id}")
async def remove_my_key(key_id: int, user_id: int = Depends(auth.get_current_user_id)):
    db.delete_user_key(key_id, user_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin-lite: shared pool management (unchanged from Phase 2)
# ---------------------------------------------------------------------------

def require_admin(x_admin_token: Optional[str] = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN not configured on server")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token header")


class AdminAddKeyRequest(BaseModel):
    provider: Literal["groq", "openrouter", "gemini"]
    model: str
    api_key: str
    rpm_limit: int
    rpd_limit: int
    category: Literal["text", "vision"] = "text"
    priority: int = 0


class AdminUpdateKeyRequest(BaseModel):
    status: Optional[Literal["active", "paused"]] = None
    priority: Optional[int] = None


@app.get("/admin/keys")
async def admin_list_keys(x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    return db.list_keys()


@app.post("/admin/keys")
async def admin_add_key(req: AdminAddKeyRequest, x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    key_id = db.add_key(
        provider=req.provider, model=req.model, api_key=req.api_key,
        rpm_limit=req.rpm_limit, rpd_limit=req.rpd_limit,
        category=req.category, priority=req.priority,
    )
    db.add_audit_log("add_key", target_type="api_key", target_id=str(key_id),
                     details=f"provider={req.provider} model={req.model} cat={req.category} rpm={req.rpm_limit} rpd={req.rpd_limit}")
    return {"id": key_id}


@app.patch("/admin/keys/{key_id}")
async def admin_update_key(key_id: int, req: AdminUpdateKeyRequest,
                            x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    changes = []
    if req.status is not None:
        db.update_status(key_id, req.status)
        changes.append(f"status={req.status}")
    if req.priority is not None:
        db.update_priority(key_id, req.priority)
        changes.append(f"priority={req.priority}")
    if changes:
        db.add_audit_log("update_key", target_type="api_key", target_id=str(key_id),
                         details="; ".join(changes))
    return {"ok": True}


@app.post("/admin/keys/{key_id}/test")
async def admin_test_key(key_id: int, x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    result = await key_pool.test_key_validity(key_id)
    db.add_audit_log("test_key", target_type="api_key", target_id=str(key_id), details=f"result={result}")
    return {"id": key_id, "result": result}


@app.post("/admin/keys/test-all")
async def admin_test_all_keys(x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    results = await key_pool.test_all_keys()
    db.add_audit_log("test_all_keys", details=f"tested={len(results)}")
    return results


# ---------------------------------------------------------------------------
# User Account Management
# ---------------------------------------------------------------------------

class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.put("/user/password")
async def update_user_password(
    req: UpdatePasswordRequest, 
    user_id: int = Depends(auth.get_current_user_id)
):
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if not auth.verify_password(req.current_password, user["password_hash"]):
        raise HTTPException(status_code=403, detail="Incorrect current password")
        
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
        
    new_hash = auth.hash_password(req.new_password)
    db.update_password(user_id, new_hash)
    db.add_audit_log("update_password", target_type="user", target_id=str(user_id))
    return {"ok": True}


@app.delete("/user")
async def delete_user_account(user_id: int = Depends(auth.get_current_user_id)):
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    db.delete_user_data(user_id)
    db.add_audit_log("delete_account", target_type="user", target_id=str(user_id))
    return {"ok": True}


@app.delete("/conversations")
async def clear_all_conversations(user_id: int = Depends(auth.get_current_user_id)):
    db.delete_all_conversations(user_id)
    db.add_audit_log("clear_conversations", target_type="user", target_id=str(user_id))
    return {"ok": True}



# ---------------------------------------------------------------------------
# Admin — new endpoints: delete, live usage, users, analytics, audit, settings
# ---------------------------------------------------------------------------

class AdminUpdateUserRequest(BaseModel):
    daily_quota: Optional[int] = None   # -1 = reset to default; 0 = block; N = custom cap
    is_banned: Optional[bool] = None
    ban_reason: Optional[str] = None
    notes: Optional[str] = None


class AdminSettingsPatchRequest(BaseModel):
    maintenance_mode: Optional[bool] = None
    default_daily_quota: Optional[int] = None


@app.delete("/admin/keys/{key_id}")
async def admin_delete_key(key_id: int, x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    if not db.get_key(key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    db.delete_key_from_db(key_id)
    db.add_audit_log("delete_key", target_type="api_key", target_id=str(key_id),
                     details="permanently deleted")
    return {"ok": True}


@app.get("/admin/keys/usage")
async def admin_keys_usage(x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    return await key_pool.get_pool_usage_snapshot()


@app.get("/admin/users")
async def admin_list_users(x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    return db.list_users_admin()


@app.patch("/admin/users/{user_id}")
async def admin_update_user(user_id: int, req: AdminUpdateUserRequest,
                             x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    if not db.get_user_by_id(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    db.upsert_user_override(
        user_id,
        daily_quota=req.daily_quota,
        is_banned=req.is_banned,
        ban_reason=req.ban_reason,
        notes=req.notes,
    )
    if req.is_banned is True:
        action = "ban_user"
    elif req.is_banned is False:
        action = "unban_user"
    else:
        action = "update_user"
    db.add_audit_log(
        action, target_type="user", target_id=str(user_id),
        details=f"quota={req.daily_quota} banned={req.is_banned} reason={req.ban_reason}",
    )
    return {"ok": True}


@app.get("/admin/analytics")
async def admin_analytics(days: int = 7, x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    return db.get_analytics(days=max(1, min(days, 90)))


@app.get("/admin/audit-log")
async def admin_audit_log(limit: int = 100, x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    return db.list_audit_logs(limit=min(limit, 500))


@app.get("/admin/settings")
async def admin_get_settings(x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    raw = db.get_all_settings()
    return {
        "maintenance_mode": raw.get("maintenance_mode", "0") == "1",
        "default_daily_quota": int(raw.get("default_daily_quota", str(DEFAULT_DAILY_QUOTA))),
    }


@app.patch("/admin/settings")
async def admin_patch_settings(req: AdminSettingsPatchRequest,
                                x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    changes = []
    if req.maintenance_mode is not None:
        db.set_setting("maintenance_mode", "1" if req.maintenance_mode else "0")
        changes.append(f"maintenance_mode={'on' if req.maintenance_mode else 'off'}")
    if req.default_daily_quota is not None:
        if req.default_daily_quota < 0:
            raise HTTPException(status_code=400, detail="default_daily_quota must be >= 0")
        db.set_setting("default_daily_quota", str(req.default_daily_quota))
        changes.append(f"default_daily_quota={req.default_daily_quota}")
    if changes:
        db.add_audit_log("update_settings", details="; ".join(changes))
    return {"ok": True}


# ---------------------------------------------------------------------------
# About Page CMS
# ---------------------------------------------------------------------------

class AboutSectionCreate(BaseModel):
    section_type: str
    title: Optional[str] = ""
    subtitle: Optional[str] = ""
    content: Optional[str] = ""
    metadata: Optional[str] = None
    is_enabled: Optional[int] = 1

class AboutSectionUpdate(BaseModel):
    section_type: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[str] = None
    display_order: Optional[int] = None
    is_enabled: Optional[int] = None

@app.get("/about")
async def get_public_about():
    """Public endpoint to fetch active about sections."""
    return db.list_about_sections(public_only=True)

@app.get("/admin/about")
async def admin_get_about(x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    return db.list_about_sections(public_only=False)

@app.post("/admin/about")
async def admin_create_about(req: AboutSectionCreate, x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    section_id = db.create_about_section(req.dict(exclude_unset=True))
    return {"id": section_id}

@app.patch("/admin/about/{section_id}")
async def admin_update_about(section_id: int, req: AboutSectionUpdate, x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    db.update_about_section(section_id, req.dict(exclude_unset=True))
    return {"ok": True}

@app.delete("/admin/about/{section_id}")
async def admin_delete_about(section_id: int, x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    db.delete_about_section(section_id)
    return {"ok": True}

@app.post("/admin/about/{section_id}/image")
async def admin_upload_about_image(section_id: int, file: UploadFile = File(...), x_admin_token: Optional[str] = Header(default=None)):
    require_admin(x_admin_token)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    
    # Save the file to uploads/about
    ext = file.filename.split('.')[-1].lower()
    if ext not in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
        raise HTTPException(status_code=400, detail="Unsupported file format")
        
    safe_name = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join("uploads", "about", safe_name)
    
    with open(file_path, "wb") as f:
        f.write(await file.read())
        
    image_url = f"/uploads/about/{safe_name}"
    
    # Update the section with the new image URL
    db.update_about_section(section_id, {"image_url": image_url})
    
    return {"image_url": image_url}
