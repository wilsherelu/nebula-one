from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any


COLORS = ("#2563eb", "#0f9f6e", "#f59e0b", "#8b5cf6", "#ec4899")


def render_organization_ghg_inventory_v1_svg(result: dict[str, Any]) -> str:
    scopes = result["scopes"]
    unit = str(result["total"]["unit"])
    maximum = max((float(item["total"]["value"]) for item in scopes), default=0.0)
    denominator = maximum if maximum > 0 else 1.0
    rows = []
    for row_index, scope in enumerate(scopes):
        y = 230 + row_index * 130
        scope_value = float(scope["total"]["value"])
        scope_width = 760.0 * scope_value / denominator
        segments = []
        offset = 0.0
        for category_index, category in enumerate(scope["categories"]):
            category_value = float(category["total"]["value"])
            width = (
                scope_width * category_value / scope_value if scope_value > 0 else 0.0
            )
            segments.append(
                f'<rect x="300" y="{y}" width="{width:.2f}" height="42" '
                f'transform="translate({offset:.2f} 0)" '
                f'fill="{COLORS[category_index % len(COLORS)]}"/>'
            )
            offset += width
        category_names = ", ".join(
            str(category["category"]) for category in scope["categories"]
        )
        rows.append(
            f'''<text x="72" y="{y + 29}" fill="#16324f" font-family="Arial, sans-serif" font-size="21" font-weight="700">{escape(_scope_label(scope['scope']))}</text>
  <rect x="300" y="{y}" width="760" height="42" rx="6" fill="#e8edf3"/>
  {''.join(segments)}
  <text x="1080" y="{y + 28}" fill="#16324f" font-family="Arial, sans-serif" font-size="17" text-anchor="end">{escape(_display_number(scope_value))}</text>
  <text x="300" y="{y + 67}" fill="#64748b" font-family="Arial, sans-serif" font-size="14">{escape(category_names)}</text>'''
        )
    total = _display_number(result["total"]["value"])
    audit_status = str(result["audit"]["status"])
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="680" viewBox="0 0 1200 680" role="img" aria-labelledby="title desc">
  <title id="title">Organization GHG inventory</title>
  <desc id="desc">Scope 1, Scope 2 and Scope 3 totals with method-classified category composition.</desc>
  <rect width="1200" height="680" fill="#f6f8fb"/>
  <text x="64" y="66" fill="#16324f" font-family="Arial, sans-serif" font-size="30" font-weight="700">Organization GHG inventory</text>
  <text x="64" y="104" fill="#5a7188" font-family="Arial, sans-serif" font-size="17">Exact bound snapshots · common LCIA method, unit and database release</text>
  <rect x="64" y="132" width="1072" height="70" rx="12" fill="#ffffff" stroke="#d8e1ea"/>
  <text x="88" y="174" fill="#16324f" font-family="Arial, sans-serif" font-size="24" font-weight="700">Total {escape(total)} {escape(unit)}</text>
  <text x="1110" y="174" fill="#0f766e" font-family="Arial, sans-serif" font-size="16" text-anchor="end">Audit: {escape(audit_status)}</text>
  {''.join(rows)}
  <text x="64" y="646" fill="#64748b" font-family="Arial, sans-serif" font-size="14">Source bindings: {result['audit']['source_binding_count']} · Content hash: {escape(str(result['content_sha256']))}</text>
</svg>'''


def _scope_label(scope: str) -> str:
    return scope.replace("scope_", "Scope ")


def _display_number(value: Any) -> str:
    try:
        return f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError):
        return str(value)
