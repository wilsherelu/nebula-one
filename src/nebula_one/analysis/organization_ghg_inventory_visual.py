from __future__ import annotations

from html import escape
from decimal import Decimal, InvalidOperation
from typing import Any


def _display_number(value: Any) -> str:
    try:
        return f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError):
        return str(value)


def render_organization_ghg_inventory_svg(result: dict[str, Any]) -> str:
    scopes = {item["scope"]: item for item in result["scopes"]}
    scope_1 = scopes["scope_1"]
    scope_2 = scopes["scope_2"]
    scope_3 = scopes["scope_3"]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="620" viewBox="0 0 1200 620" role="img" aria-labelledby="title desc">
  <title id="title">Organization GHG inventory trial</title>
  <desc id="desc">Partial Scope 1, Scope 2 reference, and uncalculated Scope 3 shown without combining unlike result semantics.</desc>
  <rect width="1200" height="620" fill="#f6f8fb"/>
  <text x="64" y="68" fill="#16324f" font-family="Arial, sans-serif" font-size="30" font-weight="700">Organization GHG inventory trial</text>
  <text x="64" y="103" fill="#5a7188" font-family="Arial, sans-serif" font-size="17">Partial evidence view · no inferred categories · no combined total</text>
  <rect x="64" y="145" width="1072" height="122" rx="14" fill="#ffffff" stroke="#d8e1ea"/>
  <rect x="64" y="145" width="12" height="122" rx="6" fill="#2563eb"/>
  <text x="100" y="184" fill="#16324f" font-family="Arial, sans-serif" font-size="18" font-weight="700">Scope 1 · quantified partial</text>
  <text x="100" y="226" fill="#16324f" font-family="Arial, sans-serif" font-size="28" font-weight="700">{escape(_display_number(scope_1['value']))} {escape(str(scope_1['unit']))}</text>
  <text x="690" y="216" fill="#5a7188" font-family="Arial, sans-serif" font-size="16">Exact direct EF 3.1 contribution</text>
  <rect x="64" y="287" width="1072" height="122" rx="14" fill="#ffffff" stroke="#d8e1ea"/>
  <rect x="64" y="287" width="12" height="122" rx="6" fill="#0f9f6e"/>
  <text x="100" y="326" fill="#16324f" font-family="Arial, sans-serif" font-size="18" font-weight="700">Scope 2 · location-based reference only</text>
  <text x="100" y="368" fill="#16324f" font-family="Arial, sans-serif" font-size="28" font-weight="700">{escape(_display_number(scope_2['value']))} {escape(str(scope_2['unit']))}</text>
  <text x="690" y="358" fill="#5a7188" font-family="Arial, sans-serif" font-size="16">Purchased electricity CO₂ reference</text>
  <rect x="64" y="429" width="1072" height="122" rx="14" fill="#ffffff" stroke="#d8e1ea"/>
  <rect x="64" y="429" width="12" height="122" rx="6" fill="#94a3b8"/>
  <text x="100" y="468" fill="#16324f" font-family="Arial, sans-serif" font-size="18" font-weight="700">Scope 3 · not calculated</text>
  <text x="100" y="510" fill="#5a7188" font-family="Arial, sans-serif" font-size="17">{escape(str(scope_3['reason']))}</text>
  <text x="64" y="592" fill="#7b8794" font-family="Arial, sans-serif" font-size="14">Different units and accounting semantics remain separate; this chart is not an assurance or disclosure statement.</text>
</svg>'''
