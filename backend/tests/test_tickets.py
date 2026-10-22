"""Engineering tests with model stubs, separate from real GLM evaluations."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import subprocess
import sys
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.schemas import ChatRequest, TicketUpdate
from app.chat_service import run_chat, ChatFailure
from app.storage.database import get_repository, Database
from app.storage.repository import Repository, Conflict


def complaint(_state):
    return {'intent':'complaint', 'final_response':'UNCOMMITTED DRAFT',
            'escalation_ticket':{'ticket_id':'FORGED', 'ticket_summary':'演示充电板发热', 'detail':'待核实'},
            'thought_chain':[{'agent':'escalation','output':'FORGED'}, {'agent':'summary','output':'DRAFT'}]}


def create(rid='request-1', source='demo', message='我要投诉充电板发热'):
    with patch('app.chat_service.agent_graph.invoke', side_effect=complaint):
        return run_chat(ChatRequest(message=message, request_id=rid, data_source=source))


def test_create_persistence_and_retry():
    result = create()
    ticket = result['escalation_ticket']
    assert ticket['ticket_id'].startswith('TK-') and ticket['ticket_id'] != 'FORGED'
    assert ticket['is_persisted'] and ticket['status'] == 'open'
    assert ticket['ticket_id'] in result['reply'] and '已保存' in result['reply']
    assert '不能执行退款' in result['reply'] and 'FORGED' not in json.dumps(result)
    with patch('app.chat_service.agent_graph.invoke') as graph:
        assert run_chat(ChatRequest(message='我要投诉充电板发热', request_id='request-1')) == result
    graph.assert_not_called()
    repo = get_repository()
    assert repo.list_tickets()['total'] == 1
    with repo.db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM events WHERE event_type='ticket_created'").fetchone()[0] == 1


def test_lifecycle_history_and_stale_update():
    tid = create()['escalation_ticket']['ticket_id']
    client = TestClient(app)
    url = f'/api/tickets/{tid}/status'
    assert client.patch(url,json={'status':'resolved','note':'  ','version':1}).status_code == 422
    progress = client.patch(url,json={'status':'in_progress','note':'核实订单中','version':1}).json()
    assert progress['version'] == 2 and progress['status'] == 'in_progress'
    assert client.patch(url,json={'status':'resolved','note':'old','version':1}).status_code == 409
    done = client.patch(url,json={'status':'resolved','note':'演示：已核实并给出说明，无实际退款','version':2}).json()
    assert done['status'] == 'resolved' and done['resolved_at'] and done['version'] == 3
    assert len(done['history']) == 3 and done['history'][-1]['note'] == done['processing_note']
    assert client.get('/api/tickets',params={'status':'resolved','search':tid}).json()['items'][0]['status'] == 'resolved'
    assert client.get(f'/api/tickets/{tid}').json() == done
    assert client.patch(url,json={'status':'in_progress','version':3}).status_code == 422
    assert client.patch(url,json={'status':'in_progress','note':'补充信息需复核','version':3}).json()['resolved_at'] is None


def test_search_paging_and_source_isolation():
    create('a'); create('b'); create('c','evaluation')
    client = TestClient(app)
    assert client.get('/api/tickets').json()['total'] == 2
    assert client.get('/api/tickets',params={'data_source':'evaluation'}).json()['total'] == 1
    assert len(client.get('/api/tickets',params={'limit':1,'offset':1,'search':'充电板'}).json()['items']) == 1
    assert client.get('/api/tickets',params={'search':"' OR 1=1 --"}).json()['total'] == 0
    assert client.get('/api/tickets',params={'search':'%'}).json()['total'] == 0
    assert client.get('/api/tickets/unknown').status_code == 404
    assert client.get('/api/tickets',params={'status':'fake'}).status_code == 422


def test_failed_commit_rolls_back_ticket():
    repo = get_repository()
    original = repo._event
    def broken(con, kind, *args, **kwargs):
        if kind == 'chat_finished':
            raise sqlite3.OperationalError('PRIVATE DATABASE PATH')
        return original(con, kind, *args, **kwargs)
    with patch.object(repo, '_event', side_effect=broken):
        with pytest.raises(ChatFailure):
            create()
    assert repo.list_tickets()['total'] == 0
    with repo.db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM events WHERE event_type='ticket_created'").fetchone()[0] == 0


def test_agent_failure_recorded_without_exception_text():
    with patch('app.chat_service.agent_graph.invoke',side_effect=RuntimeError('PRIVATE_UPSTREAM_TOKEN')):
        res = TestClient(app,raise_server_exceptions=False).post('/api/chat',json={'message':'投诉','request_id':'fail'})
    assert res.status_code == 502 and 'PRIVATE' not in res.text
    with get_repository().db.connect() as con:
        row = dict(con.execute('SELECT * FROM chat_turns').fetchone())
        assert row['status'] == 'failed' and row['reason_code'] == 'agent_request_failed'
        assert 'PRIVATE' not in json.dumps(row)


def test_concurrent_claim_and_request_conflict():
    repo = get_repository()
    req = ChatRequest(message='投诉',request_id='same')
    def claim(_):
        try:
            repo.begin_chat(req)
            return 'claimed'
        except Conflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, range(2))) == ['claimed','conflict']
    for change in [{'message':'不同内容'}, {'data_source':'evaluation'}]:
        with pytest.raises(Conflict):
            repo.begin_chat(req.model_copy(update=change))


def test_new_process_reads_committed_status():
    repo = get_repository()
    tid = create()['escalation_ticket']['ticket_id']
    repo.update_ticket(tid, TicketUpdate(status='in_progress',version=1))
    repo.update_ticket(tid, TicketUpdate(status='resolved',note='仅演示处理说明',version=2))
    code = 'import sqlite3,sys,json; c=sqlite3.connect(sys.argv[1]); print(json.dumps(c.execute("SELECT ticket_id,status,processing_note FROM tickets").fetchall()))'
    proc = subprocess.run([sys.executable,'-c',code,str(repo.db.path)],capture_output=True,text=True,check=True)
    assert json.loads(proc.stdout) == [[tid,'resolved','仅演示处理说明']]
    assert Repository(Database(repo.db.path)).ticket(tid)['status'] == 'resolved'


def test_restart_recovers_interrupted_once():
    repo = get_repository()
    repo.begin_chat(ChatRequest(message='投诉',request_id='interrupted'))
    assert repo.recover_interrupted() == 1
    assert repo.recover_interrupted() == 0
    with repo.db.connect() as con:
        assert con.execute('SELECT status FROM chat_turns').fetchone()[0] == 'interrupted'
        assert con.execute("SELECT COUNT(*) FROM events WHERE event_type='chat_finished'").fetchone()[0] == 1


def test_sse_uses_persistence_service():
    with patch('app.chat_service.agent_graph.invoke',side_effect=complaint):
        res = TestClient(app).post('/api/chat/stream',json={'message':'投诉','request_id':'stream'})
    assert '"event": "ticket"' in res.text and '"event": "done"' in res.text
    assert 'UNCOMMITTED DRAFT' not in res.text
    assert get_repository().list_tickets()['total'] == 1


def test_unavailable_db_never_returns_success():
    with patch('app.chat_service.get_repository',side_effect=sqlite3.OperationalError('PRIVATE')):
        res = TestClient(app).post('/api/chat',json={'message':'投诉'})
    assert res.status_code == 502 and 'PRIVATE' not in res.text and '未确认工单保存' in res.text


def test_order_link_and_basic_privacy():
    result = create(message='我要投诉 ord-001，我的邮箱 buyer@example.com，电话13812345678，api_key=FAKE_TEST_CREDENTIAL')
    ticket = get_repository().ticket(result['escalation_ticket']['ticket_id'])
    assert ticket['order_ids'] == ['ORD-001']
    assert ticket['conversation_id'] == result['conversation_id']
    with get_repository().db.connect() as con:
        records = str([tuple(r) for r in con.execute('SELECT * FROM chat_turns')])
    for secret in ['buyer@example.com','13812345678','FAKE_TEST_CREDENTIAL']:
        assert secret not in records + str(ticket)


def test_illegal_transition_and_atomic_status_event():
    repo = get_repository()
    tid = create()['escalation_ticket']['ticket_id']
    assert TestClient(app).patch(f'/api/tickets/{tid}/status',json={'status':'resolved','note':'越级','version':1}).status_code == 422
    with patch.object(repo, '_event',side_effect=sqlite3.OperationalError('TEST')):
        with pytest.raises(sqlite3.OperationalError):
            repo.update_ticket(tid,TicketUpdate(status='in_progress',note='未提交',version=1))
    item = repo.ticket(tid)
    assert item['status'] == 'open' and item['version'] == 1 and len(item['history']) == 1
