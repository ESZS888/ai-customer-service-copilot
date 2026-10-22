from datetime import date
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.chat_service import run_chat, ChatFailure
from app.models.schemas import ChatRequest, TicketUpdate
from app.storage.database import get_repository, Database
from app.storage import analytics
from app.storage.repository import Invalid, business_intent
from tests.test_tickets import create


def test_empty_dashboard_has_no_fake_zero_rate():
    result = TestClient(app).get('/api/analytics/overview').json()
    assert result['requests'] == result['conversations'] == result['tickets_created'] == 0
    assert result['failure_rate'] is None
    assert result['latency']['success'] == {'samples':0, 'median_ms':None}


def test_metrics_reconcile_requests_tickets_events_and_retries():
    first = create('one'); create('one'); create('two'); create('eval','evaluation')
    repo = get_repository()
    tid = first['escalation_ticket']['ticket_id']
    repo.update_ticket(tid,TicketUpdate(status='in_progress',version=1))
    repo.update_ticket(tid,TicketUpdate(status='resolved',note='演示处理',version=2))
    with patch('app.chat_service.agent_graph.invoke',side_effect=RuntimeError('FAKE FAILURE')):
        with pytest.raises(ChatFailure):
            run_chat(ChatRequest(message='失败问题：13812345678',request_id='failed'))
    repo.begin_chat(ChatRequest(message='中断',request_id='interrupted'))
    repo.recover_interrupted()
    repo.begin_chat(ChatRequest(message='仍在处理',request_id='processing'))
    # An ordinary successful question shares a conversation with the first complaint.
    with patch('app.chat_service.agent_graph.invoke',return_value={'intent':'product_inquiry','final_response':'商品299元'}):
        run_chat(ChatRequest(message='P001多少钱',request_id='product',conversation_id=first['conversation_id']))
    result = analytics.overview(repo,'demo')
    assert result['requests'] == 6 and result['conversations'] == 5
    assert result['request_status'] == {'succeeded':3,'failed':1,'interrupted':1,'processing':1}
    assert result['failure_rate'] == 2/5 and result['completed_requests'] == 5
    assert result['intents'] == {'complaint':2,'product':1,'unknown':3}
    assert sum(result['intents'].values()) == result['requests']
    assert result['ticket_status'] == {'open':1,'in_progress':0,'resolved':1}
    assert result['pending_tickets_all_time'] == 1 and result['tickets_created'] == 2
    assert result['latency']['success']['samples'] == 3
    assert result['latency']['failure']['samples'] == 1  # Interrupted duration unknown.
    assert analytics.overview(repo,'evaluation')['requests'] == 1
    details = analytics.requests(repo,'demo')
    assert details['total'] == 2 and '13812345678' not in str(details)
    assert analytics.requests(repo,'demo',failures_only=False)['total'] == 6
    with repo.db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM events WHERE data_source='demo' AND event_type='chat_received'").fetchone()[0] == 6
        assert con.execute("SELECT COUNT(*) FROM events WHERE data_source='demo' AND event_type='ticket_status_changed'").fetchone()[0] == 2


def test_hong_kong_day_boundaries_and_pending_all_time():
    create('before'); create('start'); create('end'); create('after')
    repo = get_repository()
    stamps = {'before':'2026-10-19T15:59:59.999999+00:00','start':'2026-10-19T16:00:00.000000+00:00',
              'end':'2026-10-20T15:59:59.999999+00:00','after':'2026-10-20T16:00:00.000000+00:00'}
    with repo.db.connect(write=True) as con:
        for rid,stamp in stamps.items():
            con.execute('UPDATE chat_turns SET created_at=? WHERE request_id=?',(stamp,rid))
            con.execute('UPDATE tickets SET created_at=? WHERE source_request_id=?',(stamp,rid))
    day = date(2026,10,20)
    result = analytics.overview(repo,'demo',day,day)
    assert result['requests'] == result['tickets_created'] == 2
    assert result['pending_tickets_all_time'] == 4
    assert {r['request_id'] for r in analytics.requests(repo,'demo',day,day,False)['items']} == {'start','end'}
    assert analytics.overview(repo,'demo',date(2020,1,1),date(2020,1,1))['requests'] == 0


@pytest.mark.parametrize('intent,message,expected',[
    ('order_query','ORD-001 金额','order'),('order_query','订单金额和物流','logistics'),
    ('product_inquiry','P001','product'),('general','服装退货政策','policy'),('complaint','投诉退款','complaint')])
def test_business_intent_uses_existing_route_without_new_agent(intent,message,expected):
    assert business_intent(message,intent) == expected


def test_invalid_dates_and_pagination():
    client = TestClient(app)
    for path in ['/api/analytics/overview','/api/analytics/requests']:
        assert client.get(path,params={'start_date':'2026-10-21','end_date':'2026-10-20'}).status_code == 422
        assert client.get(path,params={'end_date':'9999-12-31'}).status_code == 422
        assert client.get(path,params={'data_source':'production'}).status_code == 422
    assert client.get('/api/analytics/requests',params={'limit':0}).status_code == 422


def test_additive_migration_preserves_stage_one_ticket():
    tid = create()['escalation_ticket']['ticket_id']
    repo = get_repository()
    with repo.db.connect(write=True) as con:
        con.execute('ALTER TABLE chat_turns DROP COLUMN business_intent')
        con.execute('PRAGMA user_version=1')
    db = Database(repo.db.path)
    with db.connect() as con:
        assert con.execute('SELECT business_intent FROM chat_turns').fetchone()[0] == 'complaint'
        assert con.execute('SELECT ticket_id FROM tickets').fetchone()[0] == tid
