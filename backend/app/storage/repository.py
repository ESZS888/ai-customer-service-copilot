from datetime import datetime, timezone
import json
import re
from uuid import uuid4
from app.agents.reliability import identifiers, ORDER_PATTERN, SHIPMENT_WORDS
from app.storage.privacy import safe_text


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def encode(value):
    return json.dumps(value, ensure_ascii=False)


def business_intent(message, intent):
    if intent == 'order_query':
        return 'logistics' if re.search(SHIPMENT_WORDS, message) else 'order'
    if intent == 'product_inquiry':
        return 'product'
    if intent == 'general' and re.search('退货|退款|政策|质保|售后', message):
        return 'policy'
    return intent or 'unknown'


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


class Invalid(Exception):
    pass


class Repository:
    def __init__(self, db):
        self.db = db

    def _event(self, con, kind, request_id, source, payload, ticket_id=None):
        con.execute('INSERT INTO events(event_type,request_id,ticket_id,data_source,occurred_at,payload_json) VALUES(?,?,?,?,?,?)',
                    (kind, request_id, ticket_id, source, now(), encode(payload)))

    def begin_chat(self, request):
        rid = request.request_id or 'REQ-' + uuid4().hex
        with self.db.connect(write=True) as con:
            existing = con.execute('SELECT * FROM chat_turns WHERE request_id=?', (rid,)).fetchone()
            if existing:
                if (existing['message'] != request.message or existing['data_source'] != request.data_source
                    or (request.conversation_id and existing['conversation_id'] != request.conversation_id)):
                    raise Conflict('同一请求编号不能用于不同内容或数据来源。')
                if existing['status'] == 'succeeded':
                    return dict(existing), json.loads(existing['response_json'])
                if existing['status'] == 'processing':
                    raise Conflict('该请求仍在处理中，请稍后使用相同请求编号重试。')
                raise Conflict('该请求已失败或中断；重新发起请使用新的请求编号。')
            row = dict(request_id=rid, conversation_id=request.conversation_id or 'CONV-' + uuid4().hex,
                       data_source=request.data_source, created_at=now(), message=request.message)
            con.execute('INSERT INTO chat_turns(request_id,conversation_id,data_source,message,status,created_at) VALUES(?,?,?,?,?,?)',
                        (rid, row['conversation_id'], row['data_source'], row['message'], 'processing', row['created_at']))
            self._event(con, 'chat_received', rid, row['data_source'], {})
        return row, None

    def finish_chat(self, turn, result, latency_ms):
        from app.agents.summary_agent import ticket_reply
        rid, source = turn['request_id'], turn['data_source']
        ticket = None
        response = dict(reply=result.get('final_response', ''), intent=result.get('intent', 'general'),
                        thought_chain=result.get('thought_chain', []), escalation_ticket=None,
                        request_id=rid, conversation_id=turn['conversation_id'], data_source=source)
        with self.db.connect(write=True) as con:
            current = con.execute('SELECT status FROM chat_turns WHERE request_id=?', (rid,)).fetchone()
            if not current or current['status'] != 'processing':
                raise Conflict('请求已结束，不能重复保存。')
            if result.get('escalation_ticket'):
                # Draft IDs and model-generated fields cannot determine persistence metadata.
                draft = result['escalation_ticket']
                from app.models.schemas import TicketDraft
                fields = TicketDraft.model_validate(draft).model_dump()
                stamp = now()
                ticket = {**fields, 'ticket_id':'TK-' + uuid4().hex.upper(), 'source_request_id':rid,
                          'data_source':source, 'original_message':turn['message'], 'status':'open',
                          'conversation_id':turn['conversation_id'],
                          'order_ids_json':encode(identifiers(turn['message'], ORDER_PATTERN)),
                          'processing_note':'', 'version':1, 'timestamp':stamp, 'created_at':stamp,
                          'updated_at':stamp, 'resolved_at':None, 'is_persisted':True}
                cols = [k for k in ticket if k not in ('is_persisted', 'timestamp')]
                con.execute(f'INSERT INTO tickets({",".join(cols)}) VALUES({",".join("?" for _ in cols)})',
                            [ticket[k] for k in cols])
                response['escalation_ticket'] = ticket
                response['reply'] = ticket_reply(turn['message'], ticket)
                response['thought_chain'] = [
                    {**t, 'output':('已保存工单 ' + ticket['ticket_id'] if t['agent'] == 'escalation' else response['reply']),
                     'detail':'工单已保存至本机数据库，待商家处理；未真正转接人工或执行退款。'}
                    if t['agent'] in ('escalation', 'summary') else t for t in response['thought_chain']]
                self._event(con, 'ticket_created', rid, source, {'status':'open'}, ticket['ticket_id'])
                ticket['order_ids'] = json.loads(ticket.pop('order_ids_json'))
            for tool in result.get('tool_results', []):
                data = json.loads(tool['result'])
                self._event(con, 'tool_executed', rid, source,
                            {'name':tool['name'], 'outcome':'error' if data.get('error') else 'not_found' if data.get('found') is False else 'success'})
            if not response['reply'].strip():
                raise Invalid('empty_response')
            con.execute("UPDATE chat_turns SET status='succeeded',intent=?,business_intent=?,reason_code=?,finished_at=?,latency_ms=?,response_json=? WHERE request_id=?",
                        (response['intent'], business_intent(turn['message'], response['intent']), 'ticket_saved' if ticket else result.get('reason_code'), now(), latency_ms, encode(response), rid))
            self._event(con, 'chat_finished', rid, source, {'status':'succeeded', 'intent':response['intent']})
        return response

    def fail_chat(self, rid, reason, latency_ms):
        with self.db.connect(write=True) as con:
            row = con.execute('SELECT * FROM chat_turns WHERE request_id=?', (rid,)).fetchone()
            if row and row['status'] == 'processing':
                con.execute("UPDATE chat_turns SET status='failed',reason_code=?,finished_at=?,latency_ms=? WHERE request_id=?",
                            (reason, now(), latency_ms, rid))
                self._event(con, 'chat_finished', rid, row['data_source'], {'status':'failed','reason_code':reason})

    def recover_interrupted(self):
        # Called once on single-worker startup, never during another active request.
        with self.db.connect(write=True) as con:
            rows = con.execute("SELECT * FROM chat_turns WHERE status='processing'").fetchall()
            for row in rows:
                con.execute("UPDATE chat_turns SET status='interrupted',reason_code='service_restarted',finished_at=? WHERE request_id=?", (now(), row['request_id']))
                self._event(con, 'chat_finished', row['request_id'], row['data_source'], {'status':'interrupted','reason_code':'service_restarted'})
            return len(rows)

    @staticmethod
    def _ticket(row):
        ticket = {**dict(row), 'is_persisted':True, 'timestamp':row['created_at']}
        ticket['order_ids'] = json.loads(ticket.pop('order_ids_json'))
        return ticket

    def list_tickets(self, source='demo', status=None, search='', limit=20, offset=0):
        clauses, params = ['data_source=?'], [source]
        if status:
            clauses.append('status=?')
            params.append(status)
        if search.strip():
            # Literal substring; SQL parameters and escaping make %/_ harmless.
            query = '%' + search.strip().replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
            clauses.append("(ticket_id LIKE ? ESCAPE '!' OR ticket_summary LIKE ? ESCAPE '!' OR original_message LIKE ? ESCAPE '!')")
            params += [query] * 3
        where = ' AND '.join(clauses)
        with self.db.connect() as con:
            total = con.execute('SELECT COUNT(*) FROM tickets WHERE ' + where, params).fetchone()[0]
            rows = con.execute('SELECT * FROM tickets WHERE ' + where + ' ORDER BY created_at DESC,ticket_id DESC LIMIT ? OFFSET ?', params + [limit, offset]).fetchall()
        return dict(items=[self._ticket(r) for r in rows], total=total, limit=limit, offset=offset, data_source=source)

    def ticket(self, tid):
        with self.db.connect() as con:
            row = con.execute('SELECT * FROM tickets WHERE ticket_id=?', (tid,)).fetchone()
            if not row:
                raise Missing('工单不存在。')
            events = con.execute('SELECT * FROM events WHERE ticket_id=? ORDER BY id', (tid,)).fetchall()
        return {**self._ticket(row), 'history':[dict(event_type=e['event_type'], occurred_at=e['occurred_at'], **json.loads(e['payload_json'])) for e in events]}

    def update_ticket(self, tid, update):
        update = update.model_copy(update={'note':safe_text(update.note)})
        if update.status == 'resolved' and not update.note:
            raise Invalid('标记已处理必须填写处理说明。')
        with self.db.connect(write=True) as con:
            row = con.execute('SELECT * FROM tickets WHERE ticket_id=?', (tid,)).fetchone()
            if not row:
                raise Missing('工单不存在。')
            if row['version'] != update.version:
                raise Conflict('工单已被其他操作更新，请刷新详情后重试。')
            allowed = {'open':{'open','in_progress'}, 'in_progress':{'in_progress','resolved'}, 'resolved':{'resolved','in_progress'}}
            if update.status not in allowed[row['status']]:
                raise Invalid('请按待处理 → 处理中 → 已处理流转；已处理可填写原因后重新进入处理中。')
            if row['status'] == update.status and not update.note:
                raise Invalid('状态未改变，请填写备注后保存。')
            if row['status'] == 'resolved' and update.status == 'open':
                raise Invalid('已处理工单需先重新进入处理中，并填写原因。')
            if row['status'] == 'resolved' and update.status != 'resolved' and not update.note:
                raise Invalid('重新处理必须填写原因。')
            stamp = now()
            con.execute('UPDATE tickets SET status=?,processing_note=?,updated_at=?,resolved_at=?,version=version+1 WHERE ticket_id=?',
                        (update.status, update.note or row['processing_note'], stamp,
                         stamp if update.status == 'resolved' else None, tid))
            self._event(con, 'ticket_status_changed', row['source_request_id'], row['data_source'],
                        {'from_status':row['status'], 'to_status':update.status, 'note':update.note, 'version':row['version']+1}, tid)
        return self.ticket(tid)
