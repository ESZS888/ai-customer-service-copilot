"""Shared HTTP/SSE/CLI execution: commit records before acknowledging success."""
import time
from app.agents.graph import agent_graph
from app.storage.database import get_repository
from app.storage.repository import Conflict
from app.storage.privacy import safe_text, safe_value


class ChatFailure(Exception):
    def __init__(self, request_id=None):
        self.request_id = request_id


def run_chat(request):
    request = request.model_copy(update={'message':safe_text(request.message)})
    started = time.perf_counter()
    repo, turn = None, None
    phase = 'storage_unavailable'
    try:
        repo = get_repository()
        turn, cached = repo.begin_chat(request)
        if cached:
            return cached
        phase = 'agent_request_failed'
        result = agent_graph.invoke({'user_message':request.message, 'messages':[],
                                     'thought_chain':[], 'retrieved_docs':[], 'tool_results':[]})
        result = safe_value(result)
        phase = 'storage_commit_failed'
        return repo.finish_chat(turn, result, round((time.perf_counter()-started)*1000))
    except Conflict:
        raise
    except Exception:
        if turn:
            try:
                repo.fail_chat(turn['request_id'], phase, round((time.perf_counter()-started)*1000))
            except Exception:
                pass  # DB may itself be unavailable; never report a successful save.
        raise ChatFailure(turn['request_id'] if turn else request.request_id) from None
