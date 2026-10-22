"""Engineering tests with explicit stubs; never counted as real model scores."""
import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.agents import router_agent, knowledge_agent, escalation_agent, summary_agent, tool_agent
from app.agents.tool_agent import _execute_tool
from app.knowledge_base.vector_store import get_vector_store
from app.main import app


def state(message):
    return {'user_message':message,'thought_chain':[],'tool_results':[],'retrieved_docs':[]}


@pytest.mark.parametrize('name,args', [
    ('query_order',{}),('query_order',{'order_id':None}),
    ('query_order',{'order_id':'ORD-001','extra':True}),
    ('track_shipment',{'order_id':'SF1234567890'}),
    ('get_product_info',{'product_id':'../P001'}),
    ('check_return_policy',{'category':'any'}),('refund',{'order_id':'ORD-001'})])
def test_invalid_tool_arguments(name,args):
    assert json.loads(_execute_tool(name,args)).get('error')


def test_identifier_normalization():
    assert json.loads(_execute_tool('query_order',{'order_id':' ord-001 '}))['order']['amount'] == 299
    assert json.loads(_execute_tool('get_product_info',{'product_id':'p002'}))['product']['warranty'] == '6个月'


@pytest.mark.parametrize('content', ['', None, '{', '[]', '{"intent":"refund_now"}'])
def test_router_malformed_json_has_limited_fallback(content):
    with patch.object(router_agent,'call_llm',return_value={'content':content}):
        assert router_agent.router_node(state('查询 ORD-001'))['intent'] == 'order_query'


def test_unknown_product_does_not_call_generation():
    with patch.object(knowledge_agent,'call_llm') as llm:
        result = knowledge_agent.knowledge_node(state('P999多少钱'))
    assert '未找到' in result['answer']
    llm.assert_not_called()


def test_product_policy_precedes_product_description():
    result = knowledge_agent.knowledge_node(state('蓝牙耳机怎么退货，配件要求是什么'))
    assert '7天' in result['answer'] and '配件' in result['answer']


def test_number_retrieval_and_zero_overlap():
    assert 'P001' in get_vector_store().query(['P001'])['documents'][0][0]
    assert get_vector_store().query(['zzzzunrelated123'])['documents'] == [[]]


@pytest.mark.parametrize('content', [None, '{', json.dumps({'ticket_summary':'用户投诉',
    'ticket_id':'FORGED','timestamp':'FORGED','urgency':'medium'})])
def test_ticket_authority_and_no_false_promises(content):
    with patch.object(escalation_agent,'call_llm',return_value={'content':content}):
        first = escalation_agent.escalation_node(state('我要投诉'))
        second = escalation_agent.escalation_node(state('我要投诉'))
    ticket = first['escalation_ticket']
    assert ticket['ticket_id'].startswith('TK-') and ticket['ticket_id'] != 'FORGED'
    assert ticket['ticket_id'] != second['escalation_ticket']['ticket_id']
    assert ticket['is_persisted'] is False
    reply = summary_agent.summary_node({**state('我要投诉'),**first})['final_response']
    assert ticket['ticket_id'] in reply and '未真正转接' in reply and '不能执行退款' in reply


def test_no_order_identifier_means_no_tool_model_call():
    with patch.object(tool_agent,'call_llm') as llm:
        result = tool_agent.tool_node(state('我的快递到哪里了'))
    assert result['tool_results'] == [] and '请提供' in result['answer']
    llm.assert_not_called()


def test_model_cannot_query_unprovided_order_identifier():
    malicious={'tool_calls':[{'function':{'name':'query_order','arguments':'{"order_id":"ORD-002"}'}}]}
    with patch.object(tool_agent,'call_llm',return_value=malicious):
        result = tool_agent.tool_node(state('ORD-001 物流和金额'))
    assert {r['args']['order_id'] for r in result['tool_results']} == {'ORD-001'}
    assert {r['name'] for r in result['tool_results']} == {'query_order','track_shipment'}


def test_full_shipment_fields_survive_summary():
    result = _execute_tool('track_shipment',{'order_id':'ORD-001'})
    reply = summary_agent.summary_node({**state('物流'),'tool_results':[{'name':'track_shipment','result':result}]})['final_response']
    for fact in ['顺丰','SF1234567890','上海','运输中']:
        assert fact in reply


def test_knowledge_answer_is_used_without_second_generation():
    answer = '测试证据完整答案，来源X'
    assert summary_agent.summary_node({**state('问题'),'answer':answer})['final_response'] == answer


def test_http_and_sse_failure_hide_internal_details():
    client = TestClient(app,raise_server_exceptions=False)
    with patch('app.main.agent_graph.invoke',side_effect=RuntimeError('PRIVATE_TRANSPORT_DETAIL')):
        response = client.post('/api/chat',json={'message':'测试'})
        stream = client.post('/api/chat/stream',json={'message':'测试'})
    assert response.status_code == 502
    assert 'PRIVATE_TRANSPORT_DETAIL' not in response.text + stream.text
    assert '"event": "error"' in stream.text and '"event": "done"' in stream.text


def test_request_validation_unchanged():
    client = TestClient(app)
    assert client.post('/api/chat',json={'message':''}).status_code == 422
    assert client.post('/api/chat',json={'message':'x'*2001}).status_code == 422
