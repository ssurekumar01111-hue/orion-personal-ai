import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings
from .memory import (
    ContextEngine,
    MemoryStore,
    PersonalModelService,
    PersonalModelStore,
    SessionStore,
    initialize_database,
)
from .providers import ModelRouter, NebiusProvider, HermesProvider
from .agents import AgentOrchestrator
from .tools import ConfirmationStore, create_default_registry
from .tools.audit import log_event
from .tools.planner import ToolPlanner


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

orchestrator = AgentOrchestrator(
    router=router,
    registry=tools,
    context_engine=context_engine,
    planner=planner,
    confirmation_store=confirmation_store,
)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Orion — Your Personal AI Operating Layer",
)


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


@app.post("/api/chat")
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

        return {
            "session_id": session_id,
            "provider": request.provider,
            "model": result.get("model", settings.nebius_model),
            "response": response_text,
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


@app.get("/api/tools")
async def list_tools():
    return {"tools": tools.list_tools()}


@app.post("/api/tools/plan")
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
        result = await tools.execute(tool_name, **(arguments or {}))
        return {"tool": tool_name, "result": result}

    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    except (ValueError, IsADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/agent/run")
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


@app.post("/api/agent/confirm")
async def confirm_action(request: ConfirmRequest):
    pending = confirmation_store.get(request.confirmation_id)
    if pending is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown or expired confirmation ID '{request.confirmation_id}'.",
        )
    if pending.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Confirmation '{request.confirmation_id}' cannot be reused (status: {pending.status}).",
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

    return {
        "status": "executed",
        "confirmation_id": request.confirmation_id,
        "tool": pending.tool,
        "executed": True,
        "result": result,
        "provider": "nebius",
        "model": settings.nebius_model,
    }

