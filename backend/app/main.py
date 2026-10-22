import asyncio
from contextlib import asynccontextmanager
import json
import sqlite3
from datetime import date
from typing import Literal
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from app.config import settings
from app.models.schemas import ChatRequest, TicketUpdate
from app.agents.graph import agent_graph  # Compatibility for graph failure tests.
from app.chat_service import run_chat, ChatFailure
from app.storage.database import get_repository
from app.storage.repository import Conflict, Missing, Invalid
from app.storage import analytics

FAILURE = '客服请求未完成，请稍后重试或联系商家。本次未确认工单保存，未执行退款或人工转接。'


@asynccontextmanager
async def lifespan(_app):
    get_repository().recover_interrupted()
    yield


app = FastAPI(title='AI Customer Service Copilot · 本机演示', version='2.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True,
                   allow_methods=['*'], allow_headers=['*'])


@app.exception_handler(Conflict)
async def conflict_handler(_request: Request, exc: Conflict):
    return JSONResponse(status_code=409, content={'detail':str(exc)})


@app.exception_handler(Missing)
async def missing_handler(_request: Request, exc: Missing):
    return JSONResponse(status_code=404, content={'detail':str(exc)})


@app.exception_handler(Invalid)
async def invalid_handler(_request: Request, exc: Invalid):
    return JSONResponse(status_code=422, content={'detail':str(exc)})


@app.exception_handler(sqlite3.Error)
async def database_handler(_request: Request, _exc: sqlite3.Error):
    return JSONResponse(status_code=503, content={'detail':'本机数据存储暂时不可用，请稍后重试。'})


@app.get('/api/health')
async def health():
    return {'status':'ok'}


@app.post('/api/chat')
async def chat(req: ChatRequest):
    try:
        return await asyncio.to_thread(run_chat, req)
    except ChatFailure as exc:
        raise HTTPException(status_code=502, detail=FAILURE,
                            headers={'X-Request-ID':exc.request_id} if exc.request_id else None) from None


@app.post('/api/chat/stream')
async def chat_stream(req: ChatRequest):
    async def event_stream():
        def event(kind, data):
            return 'data: ' + json.dumps({'event':kind,'data':data}, ensure_ascii=False) + '\n\n'
        yield event('thought', {'agent':'router', 'status':'running', 'detail':'正在分析您的意图...'})
        try:
            result = await asyncio.to_thread(run_chat, req)
        except (ChatFailure, Conflict) as exc:
            yield event('error', {'message':str(exc) if isinstance(exc, Conflict) else FAILURE,
                                  'request_id':req.request_id})
            yield event('done', {})
            return
        for thought in result['thought_chain']:
            yield event('thought', thought)
        yield event('message', {'content':result['reply']})
        if result['escalation_ticket']:
            yield event('ticket', result['escalation_ticket'])
        yield event('done', {k:result[k] for k in ('request_id','conversation_id','data_source')})
    return StreamingResponse(event_stream(), media_type='text/event-stream',
                             headers={'Cache-Control':'no-cache','Connection':'keep-alive'})


@app.get('/api/tickets')
def tickets(data_source: Literal['demo','evaluation']='demo',
            status: Literal['open','in_progress','resolved'] | None=None,
            search: str=Query(default='', max_length=100),
            limit: int=Query(default=20, ge=1, le=100), offset: int=Query(default=0, ge=0)):
    return get_repository().list_tickets(data_source, status, search, limit, offset)


@app.get('/api/tickets/{ticket_id}')
def ticket(ticket_id: str):
    return get_repository().ticket(ticket_id)


@app.patch('/api/tickets/{ticket_id}/status')
def update_ticket(ticket_id: str, update: TicketUpdate):
    return get_repository().update_ticket(ticket_id, update)


@app.get('/api/analytics/overview')
def analytics_overview(data_source: Literal['demo','evaluation']='demo',
                       start_date: date | None=None, end_date: date | None=None):
    return analytics.overview(get_repository(), data_source, start_date, end_date)


@app.get('/api/analytics/requests')
def analytics_requests(data_source: Literal['demo','evaluation']='demo',
                       start_date: date | None=None, end_date: date | None=None,
                       failures_only: bool=True, limit: int=Query(default=20, ge=1, le=100),
                       offset: int=Query(default=0, ge=0)):
    return analytics.requests(get_repository(), data_source, start_date, end_date, failures_only, limit, offset)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host=settings.host, port=settings.port, reload=True)
