"""Shared evidence/validation helpers, not an additional Agent."""
import json
import re

ORDER_PATTERN = r'(?<![a-z0-9])ORD-\d+(?![a-z0-9])'
PRODUCT_PATTERN = r'(?<![a-z0-9])P\d+(?![a-z0-9])'
SHIPMENT_WORDS = r'物流|快递|运单|包裹|到哪|哪里|揽收|预计送达'
CATALOG_WORDS = r'(?:有什么|有哪些|卖什么).{0,5}(?:产品|商品)|(?:产品|商品).{0,5}(?:列表|清单|目录|有哪些|有什么)|(?:列出|看看).{0,8}(?:产品|商品)'
UNSUPPORTED_CLAIM = (r'已(?:经)?(?:为您|帮您|给您)?(?:转接|转交|接通).{0,3}人工|'
                     r'已(?:经)?(?:为您|帮您|给您)?(?:完成|成功|办理|处理)?退款|'
                     r'退款(?:已经|已|成功).{0,8}(?:到账|完成)|人工客服将.{0,12}(?:联系|跟进)')


def identifiers(message, pattern):
    return list(dict.fromkeys(m.upper() for m in re.findall(pattern, message, re.I)))


def json_object(content):
    if not isinstance(content, str):
        raise ValueError('empty model response')
    value = content.strip()
    if value.startswith('```'):
        value = re.sub(r'^```(?:json)?\s*|\s*```$', '', value, flags=re.I)
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError('model response is not an object')
    return result


def refund_progress(message):
    return bool(re.search(r'退款.{0,12}(?:进度|状态|到账|今天|一定)|(?:何时|什么时候).{0,5}到账', message))


def refund_request(message):
    return bool(re.search(r'(?:我要|申请|帮我|直接|绕过|要求).{0,15}(?:退货|退款)|(?:退货|退款).{0,10}(?:申请|人工处理)', message))


def product_matches(message, provider):
    ids = identifiers(message, PRODUCT_PATTERN)
    if ids:
        return [p for pid in ids if (p := provider.get_product(pid))], ids
    compact = re.sub(r'\s+', '', message).casefold()
    matches = []
    for product in provider.list_products():
        name = re.sub(r'\s+', '', product.name).casefold()
        aliases = [name] + re.findall(r'[a-z]+\d+', name)
        chinese = ''.join(re.findall(r'[一-鿿]+', name))
        aliases += [chinese, chinese[-2:], re.sub(r'^(?:智能|无线)', '', chinese)]
        if any(len(alias) >= 2 and alias in compact for alias in aliases):
            matches.append(product)
    return matches, []


def product_answer(products):
    lines = []
    for product in products:
        lines.append(f'{product.name}（{product.product_id}）：{product.price:g}元；'
                     f'特点：{"、".join(product.features)}；质保：{product.warranty}。')
    return '以下为演示商品资料：\n' + '\n'.join(lines) + '\n来源：商品目录记录。'


def thought(state, agent, answer, detail):
    return state.get('thought_chain', []) + [{'agent': agent, 'status': 'completed',
            'input': state['user_message'], 'output': answer, 'detail': detail}]


def knowledge_answer(state, answer, sources=None, reason='grounded_answer'):
    return {'answer': answer, 'sources': sources or [], 'reason_code': reason,
            'retrieved_docs': sources or [],
            'thought_chain': thought(state, 'knowledge', answer, '基于可核实记录回答；无证据时不补造事实。')}
