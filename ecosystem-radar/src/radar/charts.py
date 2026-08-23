"""Hand-rolled SVG charts.

Deliberately dependency-free: matplotlib would add ~30s to every CI run
and commit binary PNGs, which produce unreadable diffs. SVG is text, so
the dataset history stays reviewable in `git diff`.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

PALETTE = {
    "ink": "#0d1b2a",
    "grid": "#dbe4ec",
    "line": "#1f6f8b",
    "fill": "#1f6f8b22",
    "up": "#2f9e63",
    "down": "#c8553d",
    "muted": "#66788a",
}


def _points(
    values: list[float], width: float, height: float, pad: float
) -> list[tuple[float, float]]:
    if not values:
        return []
    if len(values) == 1:
        return [(pad, height / 2)]

    low, high = min(values), max(values)
    span = high - low
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    coords = []
    for index, value in enumerate(values):
        x = pad + inner_w * index / (len(values) - 1)
        ratio = 0.5 if span == 0 else (value - low) / span
        y = pad + inner_h * (1 - ratio)
        coords.append((round(x, 2), round(y, 2)))
    return coords


def sparkline(values: list[float], width: int = 220, height: int = 48, pad: float = 4.0) -> str:
    """A tiny trend line, sized to sit inline in a Markdown table."""
    coords = _points(values, width, height, pad)
    if not coords:
        return _empty(width, height)

    rising = values[-1] >= values[0]
    stroke = PALETTE["up"] if rising else PALETTE["down"]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(coords))
    area = (
        f"M{coords[0][0]},{height - pad} "
        + " ".join(f"L{x},{y}" for x, y in coords)
        + f" L{coords[-1][0]},{height - pad} Z"
    )
    last_x, last_y = coords[-1]

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="trend">'
        f'<path d="{area}" fill="{stroke}1f"/>'
        f'<path d="{path}" fill="none" stroke="{stroke}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.6" fill="{stroke}"/>'
        f"</svg>"
    )


def bar_chart(
    items: list[tuple[str, float]],
    width: int = 640,
    bar_height: int = 26,
    gap: int = 8,
    pad: int = 12,
    label_width: int = 190,
) -> str:
    """Horizontal bars — used for the category league table."""
    if not items:
        return _empty(width, 60)

    height = pad * 2 + len(items) * bar_height + (len(items) - 1) * gap
    top = max(abs(value) for _, value in items) or 1.0
    track = width - label_width - pad * 2 - 60

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="chart" '
        f'font-family="ui-sans-serif, system-ui, sans-serif">'
    ]

    for index, (label, value) in enumerate(items):
        y = pad + index * (bar_height + gap)
        length = max(2.0, track * abs(value) / top)
        colour = PALETTE["up"] if value >= 0 else PALETTE["down"]
        parts.append(
            f'<text x="{label_width}" y="{y + bar_height * 0.7}" text-anchor="end" '
            f'font-size="12" fill="{PALETTE["ink"]}">{escape(str(label))}</text>'
        )
        parts.append(
            f'<rect x="{label_width + 10}" y="{y}" width="{length:.1f}" '
            f'height="{bar_height - 6}" rx="3" fill="{colour}"/>'
        )
        parts.append(
            f'<text x="{label_width + 18 + length:.1f}" y="{y + bar_height * 0.66}" '
            f'font-size="11" fill="{PALETTE["muted"]}">{_fmt(value)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _fmt(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if magnitude >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:.0f}"


def _empty(width: int, height: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><text x="{width / 2}" y="{height / 2}" '
        f'text-anchor="middle" font-size="11" fill="{PALETTE["muted"]}" '
        f'font-family="sans-serif">no data yet</text></svg>'
    )
