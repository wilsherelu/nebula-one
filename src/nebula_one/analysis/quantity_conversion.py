from __future__ import annotations

from html import escape

from ..casepacks.quantity_conversions import QuantityConversionReceipt


def render_quantity_conversion_svg(receipt: QuantityConversionReceipt) -> str:
    source = receipt.source_quantity
    record = receipt.property_record
    result = receipt.result
    title = "Mass-to-energy conversion trace"
    description = (
        f"{source.amount} {source.unit} multiplied by {record.value} "
        f"{record.unit.symbol} equals {result.amount} {result.unit.symbol}."
    )
    boxes = [
        (48, 110, 250, "Solved exchange", f"{source.amount} {source.unit}", "#e8f3ff", "#2878d0"),
        (340, 110, 250, "Physical property", f"{record.value} {record.unit.symbol}", "#edf8f3", "#2f9b72"),
        (632, 110, 250, "Formula v1.0.0", "mass × heating value", "#f5efff", "#7857c6"),
        (924, 110, 228, "Converted quantity", f"{result.amount} {result.unit.symbol}", "#fff5e8", "#cf7a24"),
    ]
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 1200 330" preserveAspectRatio="xMinYMin meet" role="img" aria-labelledby="conversion-title conversion-desc">',
        f'<title id="conversion-title">{escape(title)}</title>',
        f'<desc id="conversion-desc">{escape(description)}</desc>',
        '<rect width="1200" height="330" fill="#f7fafc"/>',
        '<text x="48" y="48" font-family="Inter,Segoe UI,sans-serif" font-size="24" font-weight="700" fill="#15324b">Mass-to-energy conversion</text>',
        '<text x="48" y="78" font-family="Inter,Segoe UI,sans-serif" font-size="14" fill="#58738c">Frozen solved exchange + versioned physical-property evidence</text>',
    ]
    for index, (x, y, width, label, value, fill, accent) in enumerate(boxes):
        lines.extend(
            [
                f'<rect x="{x}" y="{y}" width="{width}" height="116" rx="14" fill="{fill}" stroke="{accent}" stroke-width="2"/>',
                f'<text x="{x + 20}" y="{y + 36}" font-family="Inter,Segoe UI,sans-serif" font-size="13" font-weight="600" fill="#58738c">{escape(label)}</text>',
                f'<text x="{x + 20}" y="{y + 76}" font-family="Inter,Segoe UI,sans-serif" font-size="22" font-weight="700" fill="#15324b">{escape(value)}</text>',
            ]
        )
        if index < len(boxes) - 1:
            next_x = boxes[index + 1][0]
            lines.extend(
                [
                    f'<line x1="{x + width + 10}" y1="168" x2="{next_x - 16}" y2="168" stroke="#87a4bd" stroke-width="3"/>',
                    f'<path d="M {next_x - 24} 160 L {next_x - 12} 168 L {next_x - 24} 176" fill="none" stroke="#87a4bd" stroke-width="3"/>',
                ]
            )
    lines.extend(
        [
            '<text x="48" y="272" font-family="Inter,Segoe UI,sans-serif" font-size="13" fill="#58738c">Evidence gate</text>',
            f'<text x="150" y="272" font-family="Inter,Segoe UI,sans-serif" font-size="13" font-weight="600" fill="#9a5c16">{escape(record.usage_gate)}</text>',
            '<text x="48" y="298" font-family="Inter,Segoe UI,sans-serif" font-size="12" fill="#71879a">This trace visualizes the frozen receipt; the JSON receipt remains the result source of truth.</text>',
            '</svg>',
        ]
    )
    return "".join(lines)
