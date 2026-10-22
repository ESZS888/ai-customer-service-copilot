"""Read-only, snapshot-consistent metrics for the small local MVP."""
from datetime import date, datetime, time, timedelta, timezone
import statistics
from app.storage.repository import Invalid

LOCAL_ZONE = timezone(timedelta(hours=8))


def filters(source, start_date: date | None, end_date: date | None):
    if start_date and end_date and start_date > end_date:
        raise Invalid('开始日期不能晚于结束日期。')
    clauses, params = ['data_source=?'], [source]
    try:
        for value, op in [(start_date, '>='), (end_date + timedelta(days=1) if end_date else None, '<')]:
            if value:
                stamp = datetime.combine(value, time.min, LOCAL_ZONE).astimezone(timezone.utc).isoformat(timespec='microseconds')
                clauses.append('created_at' + op + '?')
                params.append(stamp)
    except (OverflowError, ValueError):
        raise Invalid('日期超出可支持范围。') from None
    return ' AND '.join(clauses), params


def overview(repo, source, start_date=None, end_date=None):
    where, params = filters(source, start_date, end_date)
    with repo.db.connect() as con:
        totals = con.execute('SELECT COUNT(*) AS requests, COUNT(DISTINCT conversation_id) AS conversations FROM chat_turns WHERE ' + where, params).fetchone()
        counts = {r['status']:r['n'] for r in con.execute('SELECT status,COUNT(*) n FROM chat_turns WHERE ' + where + ' GROUP BY status', params)}
        intents = {r['intent']:r['n'] for r in con.execute("SELECT COALESCE(business_intent,'unknown') intent,COUNT(*) n FROM chat_turns WHERE " + where + ' GROUP BY 1', params)}
        tickets = {r['status']:r['n'] for r in con.execute('SELECT status,COUNT(*) n FROM tickets WHERE ' + where + ' GROUP BY status', params)}
        pending = con.execute("SELECT COUNT(*) FROM tickets WHERE data_source=? AND status IN ('open','in_progress')", (source,)).fetchone()[0]
        times = con.execute('SELECT status,latency_ms FROM chat_turns WHERE ' + where + ' AND latency_ms IS NOT NULL', params).fetchall()
        reasons = [dict(r) for r in con.execute('SELECT reason_code,COUNT(*) count FROM chat_turns WHERE ' + where + " AND status IN ('failed','interrupted') GROUP BY reason_code ORDER BY count DESC,reason_code", params)]
    completed = sum(counts.get(key, 0) for key in ('succeeded','failed','interrupted'))
    failed = counts.get('failed', 0) + counts.get('interrupted', 0)
    latency = {}
    for group, statuses in [('success', {'succeeded'}), ('failure', {'failed','interrupted'})]:
        values = [r['latency_ms'] for r in times if r['status'] in statuses]
        latency[group] = {'samples':len(values), 'median_ms':statistics.median(values) if values else None}
    return {'data_source':source, 'timezone':'Asia/Hong_Kong',
            'range':{'start_date':start_date,'end_date':end_date}, **dict(totals),
            'request_status':{k:counts.get(k,0) for k in ('processing','succeeded','failed','interrupted')},
            'completed_requests':completed, 'failed_requests':failed,
            'failure_rate':failed/completed if completed else None,
            'intents':intents, 'tickets_created':sum(tickets.values()),
            'ticket_status':{k:tickets.get(k,0) for k in ('open','in_progress','resolved')},
            'pending_tickets_all_time':pending, 'latency':latency, 'failure_reasons':reasons}


def requests(repo, source, start_date=None, end_date=None, failures_only=True, limit=20, offset=0):
    where, params = filters(source, start_date, end_date)
    if failures_only:
        where += " AND status IN ('failed','interrupted')"
    with repo.db.connect() as con:
        total = con.execute('SELECT COUNT(*) FROM chat_turns WHERE ' + where, params).fetchone()[0]
        rows = con.execute('SELECT request_id,conversation_id,data_source,message,status,intent,business_intent,reason_code,created_at,finished_at,latency_ms FROM chat_turns WHERE ' + where + ' ORDER BY created_at DESC,request_id DESC LIMIT ? OFFSET ?', params + [limit,offset]).fetchall()
    return {'items':[dict(r) for r in rows], 'total':total, 'limit':limit, 'offset':offset, 'data_source':source}
