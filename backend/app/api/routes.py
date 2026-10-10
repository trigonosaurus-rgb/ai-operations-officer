from collections.abc import AsyncIterable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse

from app.agent.events import AgentEvent, ErrorEvent
from app.agent.examples import EXAMPLES
from app.agent.service import TurnResult
from app.agent.tools.documents import load_manifest
from app.api.deps import AgentDep, DbDep, DocumentsDep, SessionsDep, SettingsDep, rate_limit
from app.api.schemas import (
    ChatRequest,
    DataOverview,
    DocumentInfo,
    ExampleGroup,
    HealthResponse,
    TableInfo,
    TablePreview,
)
from app.data.seed import seeded_on
from app.domain.facts import get_facts

router = APIRouter(prefix="/api")

# Whitelist for the data browser: table names can't be bound as SQL parameters,
# so only names from this set ever reach an f-string.
BROWSABLE_TABLES = (
    "warehouses", "carriers", "customers", "rate_cards", "dock_slots", "shipments", "inventory",
)  # fmt: skip


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health(request: Request, settings: SettingsDep, documents: DocumentsDep):
    as_of = seeded_on(settings.db_path)
    return HealthResponse(
        status="ok" if request.app.state.agent is not None else "degraded",
        model=settings.llm_model,
        data_as_of=as_of.isoformat() if as_of else None,
        documents=len(load_manifest(settings.manifest_path)),
        document_chunks=len(documents.nodes),
        active_sessions=len(request.app.state.sessions),
    )


@router.post(
    "/chat",
    response_class=EventSourceResponse,
    dependencies=[Depends(rate_limit)],
    tags=["agent"],
    summary="Ask the agent (Server-Sent Events stream)",
)
async def chat(
    body: ChatRequest, agent: AgentDep, sessions: SessionsDep
) -> AsyncIterable[AgentEvent]:
    """Streams `tool_call`, `tool_result`, `token`, then `done` (or `error`) events.

    Each SSE message's `data` is one JSON `AgentEvent`; dispatch on its `type` field.
    The return annotation puts the event schemas into OpenAPI (→ TypeScript types).
    """
    lock = sessions.lock(body.session_id)
    if lock.locked():
        yield ErrorEvent(code="busy", message="This chat is still answering.")
        return

    async with lock:  # one turn at a time per session: no interleaved history writes
        await agent.ensure_fresh_data()
        history = await sessions.load(body.session_id)
        result = TurnResult()
        async for event in agent.stream(history, body.message, result):
            yield event
        if result.ok:
            await sessions.save(body.session_id, result.history)


@router.delete("/sessions/{session_id}", status_code=204, tags=["agent"])
async def delete_session(session_id: str, sessions: SessionsDep) -> None:
    await sessions.delete(session_id)


@router.get("/examples", response_model=list[ExampleGroup], tags=["agent"])
async def examples():
    return EXAMPLES


@router.get("/documents", response_model=list[DocumentInfo], tags=["data"])
async def list_documents(settings: SettingsDep):
    return [
        DocumentInfo(**{k: doc[k] for k in DocumentInfo.model_fields if k != "url"},
                     url=f"/api/documents/{slug}.pdf")
        for slug, doc in load_manifest(settings.manifest_path).items()
    ]  # fmt: skip


@router.get("/documents/{slug}.pdf", response_class=FileResponse, tags=["data"])
async def get_document(slug: str, settings: SettingsDep):
    # Validate against the manifest instead of joining user input into a path:
    # this is what prevents path traversal like "../../.env".
    if slug not in load_manifest(settings.manifest_path):
        raise HTTPException(404, detail="Unknown document")
    return FileResponse(
        settings.docs_dir / f"{slug}.pdf",
        media_type="application/pdf",
        content_disposition_type="inline",
        filename=f"{slug}.pdf",
    )


@router.get("/data/overview", response_model=DataOverview, tags=["data"])
async def data_overview(settings: SettingsDep, db: DbDep):
    tables = []
    for name in BROWSABLE_TABLES:
        result = db.run(f"SELECT * FROM {name} LIMIT 0")
        tables.append(
            TableInfo(
                name=name,
                row_count=db.scalar(f"SELECT COUNT(*) FROM {name}"),
                columns=result.columns,
            )
        )
    as_of = seeded_on(settings.db_path)
    return DataOverview(
        company=get_facts()["company"]["name"],
        data_as_of=as_of.isoformat() if as_of else None,
        tables=tables,
    )


@router.get("/data/tables/{name}", response_model=TablePreview, tags=["data"])
async def table_preview(
    name: str,
    db: DbDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    if name not in BROWSABLE_TABLES:
        raise HTTPException(404, detail="Unknown table")
    result = db.run(f"SELECT * FROM {name} LIMIT {limit} OFFSET {offset}", row_limit=limit)
    if result.error:
        raise HTTPException(500, detail=result.error)
    return TablePreview(
        name=name,
        columns=result.columns,
        rows=result.rows,
        row_count=db.scalar(f"SELECT COUNT(*) FROM {name}"),
    )
