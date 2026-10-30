import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from .config import get_settings
from .memory import (
    ContextEngine,
    MemoryExtractionService,
    MemoryStore,
    PersonalModelService,
    PersonalModelStore,
    SessionStore,
    initialize_database,
    seed_demo_data,
    _is_test_environment,
)
from .providers import ModelRouter, NebiusProvider, HermesProvider
from .rate_limiter import (
    check_auth_attempts,
    check_expensive_rate_limit,
    record_auth_failure,
)
from .agents import AgentOrchestrator
from .agents.learning import PostTaskLearningService
from .tools import ConfirmationStore, create_default_registry
from .tools.skills.learning import SkillLearningService
from .tools.audit import log_event
from .tools.permissions import DEFAULT_TOOL_PERMISSIONS, Permission
from .tools.planner import ToolPlanner
from .tools.workspace import PROJECT_ROOT, _ensure_demo_workspace


settings = get_settings()

initialize_database()

providers = {
    "nebius": NebiusProvider(settings),
    "hermes": HermesProvider(settings),
}

router = ModelRouter(providers)

memory = MemoryStore()
sessions = SessionStore()
personal_store = PersonalModelStore()
personal_service = PersonalModelService(store=personal_store)

context_engine = ContextEngine(
    memory_store=memory,
    session_store=sessions,
    personal_model_service=personal_service,
)

planner = ToolPlanner(router)

tools = create_default_registry(personal_store=personal_store)
confirmation_store = ConfirmationStore()

extraction_service = MemoryExtractionService(memory_store=memory)
skill_learning_service = SkillLearningService(personal_store=personal_store, registry=tools)

learning_service = PostTaskLearningService(
    memory_store=memory,
    personal_store=personal_store,
    extraction_service=extraction_service,
)

orchestrator = AgentOrchestrator(
    router=router,
    registry=tools,
    context_engine=context_engine,
    planner=planner,
    confirmation_store=confirmation_store,
    learning_service=learning_service,
)

bearer_scheme = HTTPBearer(auto_error=False)
PUBLIC_PATHS = {"/health", "/health/", "/", "", "/favicon.svg"}


async def verify_demo_auth(
    request: Request,
    auth: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str | None:
    if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/assets/"):
        return None

    check_auth_attempts(request)

    app_settings = get_settings()
    configured_key = app_settings.orion_demo_key

    if not configured_key or not configured_key.strip():
        record_auth_failure(request)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed: ORION_DEMO_KEY is not configured.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if auth is None or not auth.credentials:
        record_auth_failure(request)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(
        auth.credentials.encode("utf-8"),
        configured_key.strip().encode("utf-8"),
    ):
        record_auth_failure(request)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return auth.credentials


@asynccontextmanager
async def lifespan(app: FastAPI):
    curr_settings = get_settings()
    if curr_settings.environment.lower() in ("production", "prod"):
        if not curr_settings.orion_demo_key or not curr_settings.orion_demo_key.strip():
            raise RuntimeError("ORION_DEMO_KEY must be set in production mode.")
        if len(curr_settings.orion_demo_key.strip()) < 32:
            raise RuntimeError("ORION_DEMO_KEY must be at least 32 characters in production mode.")
        if not curr_settings.nebius_api_key or not curr_settings.nebius_api_key.strip():
            raise RuntimeError("NEBIUS_API_KEY must be set in production mode.")
    # Initialise the dedicated workspace with demo files (idempotent).
    _ensure_demo_workspace()
    # Seed synthetic demo records if database is empty on fresh instances (non-test environment)
    if not _is_test_environment():
        seed_demo_data(force=False)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Orion — Your Personal AI Operating Layer",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    dependencies=[Depends(verify_demo_auth)],
)

# Production frontend bundle path
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
ASSETS_DIR = FRONTEND_DIST / "assets"
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    fav = FRONTEND_DIST / "favicon.svg"
    if fav.exists():
        return FileResponse(fav, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Favicon not found")


@app.get("/openapi.json", include_in_schema=False)
async def get_openapi_endpoint(auth: str | None = Depends(verify_demo_auth)):
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


@app.get("/docs", include_in_schema=False)
async def get_documentation(auth: str | None = Depends(verify_demo_auth)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{app.title} - Swagger UI")


@app.get("/redoc", include_in_schema=False)
async def get_redoc_documentation(auth: str | None = Depends(verify_demo_auth)):
    return get_redoc_html(openapi_url="/openapi.json", title=f"{app.title} - ReDoc")




class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    provider: str = "nebius"
    session_id: str | None = None


class MemoryRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    category: str = Field(default="general", max_length=100)
    importance: int = Field(default=3, ge=1, le=5)


class RecallRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }


@app.get("/")
async def root():
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "message": "Orion core is online.",
    }


@app.get("/api/providers")
async def available_providers():
    return {
        "providers": sorted(providers.keys()),
        "default": "nebius",
    }


@app.post("/api/sessions")
async def create_session(title: str = "New conversation"):
    return sessions.create(title=title)


@app.get("/api/sessions")
async def list_sessions(limit: int = 20):
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=400,
            detail="limit must be between 1 and 100",
        )

    return {
        "sessions": sessions.list_recent(limit=limit),
    }


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    limit: int = 50,
):
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=400,
            detail="limit must be between 1 and 200",
        )

    if not sessions.get(session_id):
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        )

    return {
        "session_id": session_id,
        "messages": sessions.get_messages(
            session_id=session_id,
            limit=limit,
        ),
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    deleted = sessions.delete(session_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        )

    return {
        "deleted": True,
        "session_id": session_id,
    }


@app.post("/api/chat", dependencies=[Depends(check_expensive_rate_limit)])
async def chat(request: ChatRequest):
    try:
        session_id = request.session_id

        if session_id:
            if not sessions.get(session_id):
                raise HTTPException(
                    status_code=404,
                    detail="Session not found",
                )
        else:
            session = sessions.create()
            session_id = session["id"]

        context = context_engine.build_context(
            user_message=request.message,
            session_id=session_id,
            memory_limit=5,
            message_limit=10,
        )

        messages = context_engine.build_messages(
            user_message=request.message,
            context=context,
        )

        sessions.add_message(
            session_id=session_id,
            role="user",
            content=request.message,
        )

        result = await router.chat(
            provider=request.provider,
            messages=messages,
        )

        choice = result["choices"][0]
        assistant_message = choice["message"]
        response_text = assistant_message.get("content") or ""

        sessions.add_message(
            session_id=session_id,
            role="assistant",
            content=response_text,
        )

        # Conversational memory extraction (Feature 1)
        extracted = extraction_service.extract_from_conversation(
            user_message=request.message,
            session_id=session_id,
        )

        return {
            "session_id": session_id,
            "provider": request.provider,
            "model": result.get("model", settings.nebius_model),
            "response": response_text,
            "extracted_memories": extracted,
            "context": {
                "memories_used": len(context["memories"]),
                "memory_ids": [
                    memory["id"]
                    for memory in context["memories"]
                ],
                "messages_used": len(context["messages"]),
            },
        }

    except HTTPException:
        raise

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Model provider request failed: {exc}",
        ) from exc


@app.post("/api/memory")
async def create_memory(request: MemoryRequest):
    return memory.remember(
        content=request.content,
        category=request.category,
        importance=request.importance,
    )


@app.post("/api/memory/recall")
async def recall_memory(request: RecallRequest):
    return {
        "query": request.query,
        "memories": memory.recall(
            query=request.query,
            limit=request.limit,
        ),
    }


@app.get("/api/memory/recent")
async def recent_memories(limit: int = 10):
    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=400,
            detail="limit must be between 1 and 50",
        )

    return {
        "memories": memory.list_recent(limit),
    }


@app.delete("/api/memory/{memory_id}")
async def delete_memory(memory_id: int):
    deleted = memory.delete(memory_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Memory not found",
        )

    return {
        "deleted": True,
        "memory_id": memory_id,
    }

@app.get("/api/personal/snapshot")
async def get_personal_snapshot(
    project_limit: int = 10,
    goal_limit: int = 10,
    task_limit: int = 20,
    decision_limit: int = 10,
    skill_limit: int = 10,
    active_only: bool = True,
):
    if project_limit < 0 or project_limit > 100:
        raise HTTPException(status_code=400, detail="project_limit must be between 0 and 100")
    if goal_limit < 0 or goal_limit > 100:
        raise HTTPException(status_code=400, detail="goal_limit must be between 0 and 100")
    if task_limit < 0 or task_limit > 100:
        raise HTTPException(status_code=400, detail="task_limit must be between 0 and 100")
    if decision_limit < 0 or decision_limit > 100:
        raise HTTPException(status_code=400, detail="decision_limit must be between 0 and 100")
    if skill_limit < 0 or skill_limit > 100:
        raise HTTPException(status_code=400, detail="skill_limit must be between 0 and 100")

    return personal_service.get_personal_snapshot(
        project_limit=project_limit,
        goal_limit=goal_limit,
        task_limit=task_limit,
        decision_limit=decision_limit,
        skill_limit=skill_limit,
        active_only=active_only,
    )


@app.get("/api/skills")
async def get_skills(limit: int = 50):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    return {"skills": personal_store.list_skills(limit=limit)}


@app.get("/api/skills/{skill_id}/executions")
async def get_skill_executions(skill_id: int, limit: int = 20):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    return {"executions": skill_learning_service.get_execution_history(skill_id=skill_id, limit=limit)}


@app.get("/api/skills/{skill_id}/proposals")
async def get_skill_proposals(skill_id: int, status: str | None = None):
    return {"proposals": skill_learning_service.list_proposals(skill_id=skill_id, status=status)}


@app.post("/api/skills/{skill_id}/proposals/{proposal_id}/approve", dependencies=[Depends(check_expensive_rate_limit)])
async def approve_skill_proposal(skill_id: int, proposal_id: int):
    try:
        res = skill_learning_service.approve_proposal(skill_id=skill_id, proposal_id=proposal_id)
        return res
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.post("/api/skills/{skill_id}/proposals/{proposal_id}/reject", dependencies=[Depends(check_expensive_rate_limit)])
async def reject_skill_proposal(skill_id: int, proposal_id: int):
    try:
        return skill_learning_service.reject_proposal(skill_id=skill_id, proposal_id=proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/skills/{skill_id}/versions")
async def get_skill_versions(skill_id: int):
    return {"versions": skill_learning_service.list_versions(skill_id=skill_id)}


@app.post("/api/skills/{skill_id}/rollback/{version_number}", dependencies=[Depends(check_expensive_rate_limit)])
async def rollback_skill(skill_id: int, version_number: int):
    try:
        return skill_learning_service.rollback_to_version(skill_id=skill_id, version_number=version_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/learning/events")
async def list_learning_events(session_id: str | None = None, limit: int = 20):
    limit = max(1, min(100, limit))
    query = "SELECT * FROM learning_events"
    params = []
    if session_id:
        query += " WHERE session_id = ?"
        params.append(session_id)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)

    from .memory.database import get_connection
    with get_connection() as connection:
        rows = connection.execute(query, tuple(params)).fetchall()

    events = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d["details"])
        except Exception:
            pass
        events.append(d)

    return {"events": events}


@app.get("/api/tools")
async def list_tools():
    return {"tools": tools.list_tools()}


@app.post("/api/tools/plan", dependencies=[Depends(check_expensive_rate_limit)])
async def plan_tool(request: ChatRequest):
    try:
        decision = await planner.plan(
            user_message=request.message,
            available_tools=tools.list_tools(),
            provider=request.provider,
        )

        return {
            "request": request.message,
            "decision": decision,
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/tools/{tool_name}")
async def execute_tool(tool_name: str, arguments: dict | None = None):
    try:
        tool = tools.get(tool_name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown tool '{tool_name}'.")

    permission = DEFAULT_TOOL_PERMISSIONS.get(tool_name, tool.permission)
    if permission == Permission.BLOCKED:
        raise HTTPException(
            status_code=403,
            detail=f"Tool '{tool_name}' is blocked by Orion's security policy.",
        )
    if permission == Permission.CONFIRMATION_REQUIRED:
        raise HTTPException(
            status_code=403,
            detail=f"Tool '{tool_name}' requires confirmation and cannot be executed directly.",
        )

    raw_args = dict(arguments or {})
    if "arguments" in raw_args and isinstance(raw_args["arguments"], dict) and len(raw_args) == 1:
        raw_args = dict(raw_args["arguments"])

    # Disallow client from passing confirmed: true to bypass confirmation workflow
    raw_args.pop("confirmed", None)

    try:
        result = await tools.execute(tool_name, confirmed=False, **raw_args)
        return {"tool": tool_name, "result": result}

    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    except (ValueError, IsADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/agent/run", dependencies=[Depends(check_expensive_rate_limit)])
async def agent_run(request: ChatRequest):
    """
    Full agent loop:
      1. ToolPlanner decides whether a tool is required.
      2. If a tool is needed: validate → permission check → execute → synthesize.
      3. If no tool needed: call Nemotron directly with memory context.
      4. Store user + assistant messages in the session.
      5. Return structured metadata alongside the natural-language response.
    """
    try:
        session_id = request.session_id

        if session_id:
            if not sessions.get(session_id):
                raise HTTPException(
                    status_code=404,
                    detail="Session not found",
                )
        else:
            session = sessions.create()
            session_id = session["id"]

        sessions.add_message(
            session_id=session_id,
            role="user",
            content=request.message,
        )

        result = await orchestrator.run(
            user_message=request.message,
            session_id=session_id,
            provider=request.provider,
        )

        sessions.add_message(
            session_id=session_id,
            role="assistant",
            content=result["response"],
        )

        return {
            "session_id": session_id,
            **result,
        }

    except HTTPException:
        raise

    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Agent run failed: {exc}",
        ) from exc


class ConfirmRequest(BaseModel):
    confirmation_id: str = Field(min_length=1)
    approved: bool
    session_id: str | None = None


@app.post("/api/agent/confirm")
async def confirm_action(request: ConfirmRequest):
    pending = confirmation_store.get(request.confirmation_id)
    if pending is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown or expired confirmation ID '{request.confirmation_id}'.",
        )
    if pending.is_expired() or pending.status == "expired":
        raise HTTPException(
            status_code=400,
            detail=f"Confirmation '{request.confirmation_id}' has expired.",
        )
    if pending.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Confirmation '{request.confirmation_id}' cannot be reused (status: {pending.status}).",
        )

    # Validate session context binding if bound
    if pending.session_id is not None:
        if request.session_id != pending.session_id:
            raise HTTPException(
                status_code=403,
                detail=f"Confirmation '{request.confirmation_id}' is bound to session '{pending.session_id}' and requires a matching session context.",
            )

    if not request.approved:
        confirmation_store.mark_rejected(request.confirmation_id)
        log_event(
            event="confirmation_rejected",
            tool=pending.tool,
            arguments=pending.arguments,
            status="rejected",
            result={"confirmation_id": request.confirmation_id},
        )
        if pending.session_id and sessions.get(pending.session_id):
            sessions.add_message(
                session_id=pending.session_id,
                role="assistant",
                content=f"Action for tool '{pending.tool}' was rejected by user.",
            )
        return {
            "status": "rejected",
            "confirmation_id": request.confirmation_id,
            "tool": pending.tool,
            "executed": False,
            "message": f"Action for tool '{pending.tool}' was rejected by user.",
        }

    # Validate tool existence and permission on server before executing
    try:
        target_tool = tools.get(pending.tool)
    except ValueError:
        pending.status = "error"
        raise HTTPException(
            status_code=404,
            detail=f"Unknown tool '{pending.tool}' in pending confirmation.",
        )

    perm = DEFAULT_TOOL_PERMISSIONS.get(pending.tool, target_tool.permission)
    if perm == Permission.BLOCKED:
        pending.status = "error"
        raise HTTPException(
            status_code=403,
            detail=f"Tool '{pending.tool}' is blocked by Orion's security policy.",
        )

    # Approved: execute the exact previously stored operation
    confirmation_store.mark_approved(request.confirmation_id)
    log_event(
        event="confirmation_approved",
        tool=pending.tool,
        arguments=pending.arguments,
        status="approved",
        result={"confirmation_id": request.confirmation_id},
    )

    try:
        result = await tools.execute(pending.tool, confirmed=True, **pending.arguments)
    except Exception as exc:
        pending.status = "error"
        raise HTTPException(
            status_code=502 if not isinstance(exc, (ValueError, PermissionError)) else 400,
            detail=f"Execution of confirmed tool '{pending.tool}' failed: {exc}",
        ) from exc

    if pending.session_id and sessions.get(pending.session_id):
        sessions.add_message(
            session_id=pending.session_id,
            role="assistant",
            content=f"Executed confirmed tool '{pending.tool}': {json.dumps(result, ensure_ascii=False)}",
        )

    # Post-task learning for confirmed action (Feature 3)
    learning_outcome = None
    try:
        learning_outcome = learning_service.learn_from_turn(
            user_objective=f"Execute confirmed action: {pending.tool}",
            steps=[{"step": 1, "action": "tool", "tool": pending.tool, "status": "executed"}],
            observations=[{"step": 1, "tool": pending.tool, "result": result}],
            final_answer=f"Confirmed tool '{pending.tool}' executed successfully.",
            session_id=pending.session_id,
            confirmation_required=False,
            confirmed_result={"tool": pending.tool, "result": result},
        )
    except Exception:
        pass

    resp_payload = {
        "status": "executed",
        "confirmation_id": request.confirmation_id,
        "tool": pending.tool,
        "executed": True,
        "result": result,
        "provider": "nebius",
        "model": settings.nebius_model,
    }
    if learning_outcome:
        resp_payload["learning"] = learning_outcome

    return resp_payload


@app.post("/api/demo/reseed", dependencies=[Depends(check_expensive_rate_limit)])
async def reseed_demo(auth: str | None = Depends(verify_demo_auth)):
    counts = seed_demo_data(force=True)
    _ensure_demo_workspace()
    return {
        "status": "reseeded",
        "message": "Demo data and workspace reseeded successfully.",
        "counts": counts,
    }


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
        raise HTTPException(status_code=404, detail="Endpoint not found")
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Not found")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=port)

