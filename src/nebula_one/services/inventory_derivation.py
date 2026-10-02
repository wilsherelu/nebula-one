"""Evaluate a pinned linear input-to-emission recipe before sending the LCI to LCA.

This prepares declared inventory quantities; allocation and matrix solving remain
with the engine. Coefficients and exchange identities belong to the versioned
template, never to this evaluator.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

from ..errors import DomainError
from ..hashing import canonical_json_sha256


def derive_inventory(graph, recipe, *, validate_only=False):
    if not recipe:
        return deepcopy(graph), {}
    content = recipe.get('content') or {}
    def reject(code, message, **details):
        raise DomainError(code=code, message=message, status_code=422, details=details)
    if (recipe.get('content_sha256') != canonical_json_sha256(content)
            or content.get('schema_version') != 'nebula_one.linear-inventory-derivation.v1'):
        reject('INVENTORY_DERIVATION_INVALID', '清单推导规则的版本或内容哈希无效。')
    result = deepcopy(graph)
    ports = {f"{n['id']}::{p['id']}": p for n in result.get('nodes', [])
             for group in ('inputs', 'outputs', 'emissions') for p in n.get(group, [])}
    values, seen = {}, set()
    try:
        places = int(content['decimal_places'])
        if not 0 <= places <= 12:
            raise ValueError('decimal_places')
        quantum = Decimal(1).scaleb(-places)
        for rule in content['outputs']:
            key = rule['exchange_id']
            port = ports.get(key)
            if (key in seen or port is None or port.get('unit') != rule['unit']
                    or port.get('flowUuid') != rule['flow_uuid']
                    or port.get('flowVersion') != rule['flow_version']):
                reject('INVENTORY_DERIVATION_PORT_MISMATCH', '模型结构或单位不再符合清单推导规则。', exchange_id=key)
            seen.add(key)
            total = Decimal(0)
            for term in rule['terms']:
                source = ports.get(term['exchange_id'])
                if (source is None or source.get('unit') != term['unit']
                        or source.get('flowUuid') != term['flow_uuid']
                        or source.get('flowVersion') != term['flow_version']):
                    reject('INVENTORY_DERIVATION_PORT_MISMATCH', '推导所需的投入或残碳端口缺失。', exchange_id=term['exchange_id'])
                amount, coefficient = Decimal(str(source['amount'])), Decimal(term['coefficient'])
                if not amount.is_finite() or amount < 0 or not coefficient.is_finite():
                    raise ValueError('nonfinite quantity')
                total += amount * coefficient
            total = total.quantize(quantum, rounding=ROUND_HALF_EVEN)
            if total < 0:
                reject('INVENTORY_DERIVATION_NEGATIVE', '当前投入与产品碳量不能形成非负排放，请检查碳账。', exchange_id=key)
            if validate_only and abs(Decimal(str(port['amount'])) - total) > quantum / 2:
                reject('INVENTORY_DERIVATION_STALE', '投入已改变，CO₂ 排放仍是旧推导值；请保存清单重新推导后再计算。', exchange_id=key, expected=str(total), observed=port['amount'])
            port['amount'] = float(total)
            values[key] = str(total)
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        reject('INVENTORY_DERIVATION_INVALID', '清单推导缺少有效的数量、系数或精度声明。', reason=str(error))
    return result, values


def recipe_of(context):
    context = context or {}
    return (context.get('inventory_derivation')
            or (context.get('seed_template') or {}).get('inventory_derivation')
            or (context.get('modeling_template_binding') or {}).get('inventory_derivation'))
