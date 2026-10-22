import json
from app.agents.llm_client import call_llm
from app.data.config import get_data_provider
from dataclasses import asdict
import re
from pydantic import ValidationError
from app.models.schemas import OrderArguments, ProductArguments, PolicyArguments
from app.agents.reliability import (identifiers, ORDER_PATTERN, PRODUCT_PATTERN,
                                    SHIPMENT_WORDS, json_object, thought)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_order",
            "description": "查询订单状态",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单编号"}
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "track_shipment",
            "description": "查询物流信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单编号"}
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_return_policy",
            "description": "查询退换货政策",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "商品类别（electronics/clothing/books）",
                    }
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_info",
            "description": "获取产品详细信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "产品编号"}
                },
                "required": ["product_id"],
            },
        },
    },
]


def _execute_tool(name: str, args: dict) -> str:
    """通过 Data Provider 执行工具调用"""
    schemas = {'query_order':OrderArguments, 'track_shipment':OrderArguments,
               'get_product_info':ProductArguments, 'check_return_policy':PolicyArguments}
    if name not in schemas:
        return json.dumps({'error':'unknown_tool','message':'不支持该工具。'}, ensure_ascii=False)
    try:
        args = schemas[name].model_validate(args).model_dump()
    except (ValidationError, TypeError):
        return json.dumps({'error':'invalid_arguments','message':'参数无效，请提供有效的订单编号、商品编号或类别。'}, ensure_ascii=False)
    provider = get_data_provider()

    if name == "query_order":
        order = provider.get_order(args.get("order_id", ""))
        if order:
            return json.dumps({"found": True, "order": asdict(order)}, ensure_ascii=False)
        return json.dumps({"found": False, "message": f"未找到订单 {args.get('order_id', '')}"})

    if name == "track_shipment":
        ship = provider.get_shipment(args.get("order_id", ""))
        if ship:
            return json.dumps({"found": True, "shipment": asdict(ship)}, ensure_ascii=False)
        return json.dumps({"found": False, "message": f"未找到订单 {args.get('order_id', '')} 的物流信息"})

    if name == "check_return_policy":
        cat = args.get("category", "electronics")
        policy = provider.get_return_policy(cat)
        if policy:
            return json.dumps({"category": cat, "policy": policy.policy}, ensure_ascii=False)
        return json.dumps({"category": cat, "policy": "暂未找到该类别的退换货政策"})

    if name == "get_product_info":
        pid = args.get("product_id", "")
        product = provider.get_product(pid)
        if product:
            return json.dumps({"found": True, "product": asdict(product)}, ensure_ascii=False)
        return json.dumps({"found": False, "message": f"未找到产品 {pid}"})

    return json.dumps({"error": f"未知工具: {name}"})


def tool_node(state):
    user_msg = state['user_message']
    order_ids = identifiers(user_msg, ORDER_PATTERN)
    product_ids = identifiers(user_msg, PRODUCT_PATTERN)
    if not order_ids:
        answer = '请提供有效的订单编号，例如 ORD-001；当前无法仅凭上下文或快递单号确定订单。'
        return {'answer':answer, 'reason_code':'missing_order_id', 'tool_results':[],
                'thought_chain':thought(state, 'tool', answer, '缺少必要参数，没有执行查询。')}
    msg = call_llm(messages=[{'role':'system','content':
        '根据用户问题选择只读工具。编号必须来自用户，不能猜测。查不到时不能编造。'},
        {'role':'user','content':user_msg}], tools=TOOLS, tool_choice='auto', temperature=0.1)
    results, seen = [], set()

    def execute(name, args):
        key = (name, json.dumps(args, sort_keys=True))
        if key in seen:
            return
        seen.add(key)
        results.append({'name':name,'args':args,'result':_execute_tool(name,args)})

    for call in (msg.get('tool_calls') or [])[:8]:
        try:
            name = call['function']['name']
            args = json_object(call['function']['arguments'])
            if name in ('query_order','track_shipment'):
                args = OrderArguments.model_validate(args).model_dump()
                if args['order_id'] not in order_ids:
                    continue
            elif name == 'get_product_info':
                args = ProductArguments.model_validate(args).model_dump()
                if args['product_id'] not in product_ids:
                    continue
            elif name == 'check_return_policy':
                # Policy questions belong to Knowledge; do not accept inferred
                # policy categories in this order-only branch.
                continue
            else:
                continue
            execute(name,args)
        except (KeyError, TypeError, ValueError, ValidationError):
            continue
    # A read-only fallback, using only identifiers explicitly provided by the
    # user, handles missing/truncated tool_calls without inventing arguments.
    shipment = bool(re.search(SHIPMENT_WORDS,user_msg))
    required = ['track_shipment'] if shipment else ['query_order']
    if shipment and re.search(r'金额|订单状态|订单详情|同时',user_msg):
        required.append('query_order')
    for order_id in order_ids[:3]:
        for name in required:
            execute(name,{'order_id':order_id})
    detail = '\n'.join(f'{r["name"]}：{r["result"]}' for r in results)
    return {'tool_results':results, 'reason_code':'read_only_lookup',
            'thought_chain':thought(state, 'tool', f'完成{len(results)}个只读查询', detail)}
