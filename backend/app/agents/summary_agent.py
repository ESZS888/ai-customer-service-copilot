import json
import re
from app.agents.reliability import thought

STATUS = {'shipped':'已发货','processing':'处理中','delivered':'已签收'}


def ticket_reply(message, ticket):
    subject = re.sub(r'[。！？；\n\r]', '，', message)[:120]
    if ticket.get('is_persisted'):
        return (f'诉求（用户原话，尚未核实）：{subject}\n'
                f'工单已保存至本机数据库，编号：{ticket["ticket_id"]}，状态：待处理。'
                '商家可在工单管理页查看和处理；保存不代表已转接人工、已通知商家或问题已解决。'
                '本客服不能执行退款或保证到账。')
    return (f'诉求（用户原话，尚未核实）：{subject}\n'
            f'已生成本次会话的临时工单信息，编号：{ticket["ticket_id"]}。'
            '该信息尚未持久保存，也未真正转接人工或通知商家。'
            '请自行联系原购买渠道的商家人工客服，并提供订单及问题描述；本客服不能执行退款或保证到账。')


def summary_node(state):
    ticket = state.get('escalation_ticket')
    if ticket:
        answer = ticket_reply(state['user_message'], ticket)
    elif state.get('answer'):
        answer = state['answer']
    else:
        lines = []
        for item in state.get('tool_results', []):
            data = json.loads(item['result'])
            if data.get('error') or data.get('found') is False:
                lines.append(data.get('message', '未找到可核实数据。'))
            elif 'order' in data:
                order = data['order']
                lines.append(f'演示订单 {order["order_id"]}：{order["product"]}，金额{order["amount"]:g}元，'
                             f'状态：{STATUS.get(order["status"],order["status"])}，下单日期：{order["date"]}。')
            elif 'shipment' in data:
                ship = data['shipment']
                lines.append(f'演示物流 {ship["order_id"]}：{ship["carrier"]}，运单号{ship["tracking_no"]}，'
                             f'位置：{ship["location"]}，状态：{ship["status"]}，预计{ship["estimated"]}送达。')
            elif 'policy' in data:
                lines.append(data['policy'])
            elif 'product' in data:
                product = data['product']
                lines.append(f'{product["name"]}（{product["product_id"]}）：{product["price"]:g}元，'
                             f'质保{product["warranty"]}，特点：{"、".join(product["features"])}。')
        answer = '\n'.join(lines) or '没有获得足够证据，请补充具体商品或订单编号。'
    if not ticket and re.search(r'(?:已(?:经)?(?:为您|帮您|给您)?(?:转接|转交|接通).{0,3}人工|'
                               r'已(?:经)?(?:为您|帮您|给您)?(?:完成|成功|办理|处理)?退款|'
                               r'退款(?:已经|已|成功).{0,8}(?:到账|完成)|人工客服将.{0,12}(?:联系|跟进))', answer):
        answer = '无法确认该处理结果。本客服不能执行退款或真正转接人工，请联系商家核实。'
    return {'final_response':answer,
            'thought_chain':thought(state, 'summary', answer, '保留完整关键事实；编号和操作边界由程序确定。')}
