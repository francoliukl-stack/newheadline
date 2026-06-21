from __future__ import annotations

import base64
import html
from datetime import datetime
from mimetypes import guess_type
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Tuple

try:
    import qrcode
except Exception:  # pragma: no cover - optional runtime dependency fallback
    qrcode = None

from .gbss_report import build_report_data
from .publish_format import (
    field_text,
    sorted_recent_records,
    topic_fields,
    topic_value,
)


WIDTH = 900
HEIGHT = 2260
LEFT = 42
RIGHT = WIDTH - 42
ACCENT = "#1677ff"
NAVY = "#07182f"
ANT_BLUE = "#1677ff"
LIGHT_BLUE = "#eef6ff"
MUTED = "#6e7280"
GRID = "#e5e7ef"
PINK = "#eef6ff"
YELLOW = "#f7fbff"
GREEN = "#effaf2"


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _text_len(value: str) -> float:
    total = 0.0
    for char in value:
        total += 1.75 if ord(char) > 127 else 1.0
    return total


def _display_value(value: Any) -> str:
    text = str(value or "")
    replacements = [
        ("ePOS / Antom / WorldFirst", "Merchant Service / ePOS, Antom, WorldFirst"),
        ("ePOS、Antom、WorldFirst", "Merchant Service / ePOS、Antom、WorldFirst"),
        ("Antom / WorldFirst / ePOS", "Antom / WorldFirst / Merchant Service"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    while "Merchant Service / Merchant Service / ePOS" in text:
        text = text.replace("Merchant Service / Merchant Service / ePOS", "Merchant Service / ePOS")
    return text


def _wrap(value: Any, max_units: int, max_lines: int = 2, ellipsis: bool = True) -> List[str]:
    text = " ".join(_display_value(value or "-").replace("\n", " ").split())
    if not text:
        return ["-"]
    words = text.split(" ")
    if len(words) > 1:
        lines: List[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if _text_len(candidate) <= max_units:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = word
            else:
                lines.append(word[:max_units])
                current = word[max_units:]
            if len(lines) >= max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
        if ellipsis and len(lines) == max_lines and " ".join(lines) != text:
            lines[-1] = lines[-1].rstrip(" .,;:") + "..."
        return lines or ["-"]
    lines: List[str] = []
    current = ""
    for char in text:
        candidate = f"{current}{char}"
        if _text_len(candidate) <= max_units:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = "" if char == " " else char
        else:
            lines.append(char)
            current = ""
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if ellipsis and len(lines) == max_lines and current:
        consumed = " ".join(lines)
        if len(consumed) < len(text):
            lines[-1] = lines[-1].rstrip(" .。") + "..."
    return lines or ["-"]


def _text(x: int, y: int, value: Any, size: int = 18, color: str = "#202334", weight: int = 400) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="Arial, PingFang SC, Microsoft YaHei, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{color}">{_esc(value)}</text>'
    )


def _wrapped_text(x: int, y: int, value: Any, max_units: int, size: int = 18, color: str = "#202334", weight: int = 400, max_lines: int = 2, line_gap: int = 24, ellipsis: bool = True) -> str:
    parts = []
    for index, line in enumerate(_wrap(value, max_units, max_lines=max_lines, ellipsis=ellipsis)):
        parts.append(_text(x, y + index * line_gap, line, size=size, color=color, weight=weight))
    return "\n".join(parts)


def _rect(x: int, y: int, width: int, height: int, fill: str, stroke: str = "none", radius: int = 0) -> str:
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" fill="{fill}" stroke="{stroke}"/>'


def _section_title(y: int, title: str) -> str:
    return "\n".join([
        _text(LEFT, y, title, size=20, color=ACCENT, weight=700),
        f'<line x1="{LEFT}" y1="{y + 10}" x2="{RIGHT}" y2="{y + 10}" stroke="{ACCENT}" stroke-width="2"/>',
    ])


def _chip(x: int, y: int, label: str, fill: str, color: str = "#ffffff") -> str:
    width = max(46, int(_text_len(label) * 11 + 20))
    return "\n".join([
        _rect(x, y - 17, width, 24, fill, radius=2),
        _text(x + 10, y, label, size=13, color=color, weight=700),
    ])


def _priority_fill(priority: str) -> Tuple[str, str]:
    if priority == "P0":
        return NAVY, "#ffffff"
    if priority == "P1":
        return ANT_BLUE, "#ffffff"
    if priority == "P2":
        return "#dcebff", NAVY
    return "#edf0f5", "#536178"


def _qr_svg(value: str, x: int, y: int, size: int) -> str:
    if not value or qrcode is None:
        return "\n".join([
            _rect(x, y, size, size, "#ffffff", stroke="#bfdcff", radius=6),
            _wrapped_text(x + 12, y + 52, "Full report link", 16, size=11, color=NAVY, weight=700, max_lines=2, ellipsis=False),
            _wrapped_text(x + 12, y + 88, "全文链接生成后可查看", 16, size=10, color="#43516a", max_lines=2, ellipsis=False),
        ])
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=1)
    qr.add_data(value)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    modules = len(matrix)
    module = max(1, size // modules)
    actual = module * modules
    offset = (size - actual) // 2
    parts = [_rect(x, y, size, size, "#ffffff", stroke="#bfdcff", radius=6)]
    for row_index, row in enumerate(matrix):
        for col_index, dark in enumerate(row):
            if dark:
                parts.append(_rect(x + offset + col_index * module, y + offset + row_index * module, module, module, NAVY))
    return "\n".join(parts)


def _image_svg(path_value: str, x: int, y: int, size: int, fallback: str) -> str:
    path = Path(path_value) if path_value else Path()
    if path_value and path.exists():
        mime = guess_type(str(path))[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return "\n".join([
            _rect(x, y, size, size, "#ffffff", stroke="#bfdcff", radius=6),
            f'<image x="{x + 6}" y="{y + 6}" width="{size - 12}" height="{size - 12}" href="data:{mime};base64,{encoded}" preserveAspectRatio="xMidYMid meet"/>',
        ])
    return "\n".join([
        _rect(x, y, size, size, "#ffffff", stroke="#bfdcff", radius=6),
        _wrapped_text(x + 10, y + 48, fallback, 15, size=10, color=NAVY, weight=700, max_lines=3, line_gap=13, ellipsis=False),
    ])


def _source_text(record: Dict[str, Any]) -> str:
    source = first_source_link(record)
    if "](" in source:
        return source.split("](", 1)[0].lstrip("[")
    return source


def _topic(record: Optional[Dict[str, Any]]) -> str:
    return topic_value(record, "Topic", "GBSS Industry and Competitor Intelligence")


def _research_question(record: Optional[Dict[str, Any]]) -> str:
    return topic_value(record, "Research Question", "What changed this week, and what should GBSS learn from it?")


def _roadmap_rows(next_topics: Optional[List[Dict[str, Any]]]) -> List[List[str]]:
    rows = []
    for index, topic in enumerate(next_topics or [], start=1):
        fields = topic_fields(topic)
        rows.append([
            f"T+{index}",
            field_text(fields.get("Publish Date")),
            field_text(fields.get("Topic")),
        ])
    return rows[:4]


def build_one_page_report_svg(
    records: List[Dict[str, Any]],
    range_label: str,
    draft: bool = False,
    research_topic: Optional[Dict[str, Any]] = None,
    next_topics: Optional[List[Dict[str, Any]]] = None,
    generated_at: Optional[datetime] = None,
    detail_url: str = "",
    group_qr_path: str = "",
    research_context: Optional[Dict[str, Any]] = None,
) -> str:
    records = sorted_recent_records(records)
    topic = _topic(research_topic)
    if topic in {"GBSS Industry and Competitor Intelligence", "-"}:
        topic = "AI is reshaping Contact Center operating model and business support capability"
    report = build_report_data(records, range_label, topic, research_context=research_context)
    brief = report["onePageBrief"]
    theme = brief["weeklyTheme"]
    radar = brief["businessSignalRadar"]
    priorities = brief["topPriorities"]
    impacts = brief["gbssStrategicImpact"]
    deep = brief["weeklyDeepInsight"]
    research_quality = report.get("researchQuality") or {}
    generated = generated_at or datetime.now()
    status = "DRAFT FOR REVIEW" if draft else "FINAL"

    priority_items = priorities[:10] or [{
        "priority": "Watch",
        "signal": "No priority signal selected / 本周暂无重点动态",
        "gbssRelevance": "Continue signal collection and evidence review. 持续采集信号并完成证据审核。",
        "publishDate": "-",
    }]
    impact_rows = max(1, min(6, len(impacts)))
    signal_brief_only = (
        research_quality.get("status") == "Signal Brief"
        and impact_rows == 1
        and "Research Quality" in str((impacts[0] if impacts else {}).get("theme") or "")
    )
    priority_y = 156
    priority_height = 52 + len(priority_items) * 54 + 8
    radar_y = priority_y + priority_height + 12
    radar_height = 78
    impact_y = radar_y + radar_height + 12
    impact_height = 52 if signal_brief_only else 48 + impact_rows * 40 + 8
    insight_y = impact_y + impact_height + 12
    insight_height = 270 if signal_brief_only else 330
    access_y = insight_y + insight_height + 12
    access_height = 116
    canvas_height = access_y + access_height + 48

    svg: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{canvas_height}" viewBox="0 0 {WIDTH} {canvas_height}">',
        _rect(0, 0, WIDTH, canvas_height, "#f6f8fb"),
        _rect(0, 0, WIDTH, 134, NAVY),
        _wrapped_text(LEFT, 42, "GBSS Weekly AI & Service Intelligence", 48, size=28, color="#ffffff", weight=700, max_lines=1),
        _text(LEFT, 74, f"One-page Brief | {research_quality.get('status', 'Signal Brief')} | Mobile View", size=16, color="#94bfff", weight=700),
        _text(LEFT, 104, f"{range_label} | {status} | {generated:%Y-%m-%d}", size=14, color="#c7d2e6", weight=400),
        _text(LEFT, 128, "Business Support | Contact Center AI | Voice AI | AIQC | OPC | Governance", size=12, color="#94bfff", weight=600),
    ]

    # 1. Top priorities come first: an executive should see what happened
    # before reading the GBSS interpretation of those signals.
    x1, y1, w1, h1 = LEFT, priority_y, RIGHT - LEFT, priority_height
    svg.append(_rect(x1, y1, w1, h1, "#ffffff", stroke=GRID, radius=6))
    svg.append(_text(x1 + 20, y1 + 29, f"1. Top Signals / 本周重点动态 ({len(priority_items)})", size=17, color=NAVY, weight=700))
    for index, item in enumerate(priority_items):
        row_y = y1 + 60 + index * 54
        fill, color = _priority_fill(item["priority"])
        svg.append(_rect(x1 + 20, row_y - 18, 54, 27, fill, radius=5))
        svg.append(_text(x1 + 35, row_y, item["priority"], size=13, color=color, weight=800))
        svg.append(_wrapped_text(x1 + 92, row_y - 7, item["signal"], 58, size=13, color=NAVY, weight=700, max_lines=1, line_gap=15, ellipsis=True))
        svg.append(_rect(x1 + 614, row_y - 19, 156, 25, LIGHT_BLUE, stroke="#d6eaff", radius=5))
        svg.append(_text(x1 + 624, row_y - 3, "PUBLISH DATE", size=8, color="#536178", weight=800))
        svg.append(_text(x1 + 708, row_y - 3, item.get("publishDate") or "-", size=11, color=ANT_BLUE, weight=800))
        svg.append(_wrapped_text(x1 + 92, row_y + 15, item["gbssRelevance"], 88, size=10, color="#43516a", max_lines=1, line_gap=12, ellipsis=True))

    # 2. Dense text pulse: the counts are useful context, not a dashboard.
    x2, y2, w2, h2 = LEFT, radar_y, RIGHT - LEFT, radar_height
    svg.append(_rect(x2, y2, w2, h2, "#f8fbff", stroke="#bfdcff", radius=6))
    svg.append(_text(x2 + 20, y2 + 26, "2. Business & Signal Pulse / 重点业务与外部信号", size=16, color=ANT_BLUE, weight=700))
    business_line = (
        f"Business signals / 业务信号: Merchant Service / ePOS {radar.get('merchantServiceSignals', radar.get('ePOSSignals', 0))} | "
        f"Antom {radar.get('antomSignals', 0)} | WorldFirst {radar.get('worldFirstSignals', 0)}"
    )
    summary = radar.get("prioritySummary") or {}
    operating_line = (
        f"Operating signals / 运营信号: Contact Center {radar.get('contactCenterSignals', 0)} | OPC Model {radar.get('opModelSignals', 0)} | "
        f"P0 {summary.get('P0', 0)} | P1 {summary.get('P1', 0)} | P2 {summary.get('P2', 0)} | Watch {summary.get('Watch', 0)}"
    )
    svg.append(_wrapped_text(x2 + 20, y2 + 49, business_line, 100, size=11, color="#29364d", weight=600, max_lines=1, ellipsis=False))
    svg.append(_wrapped_text(x2 + 20, y2 + 68, operating_line, 100, size=11, color="#43516a", max_lines=1, ellipsis=False))

    # 3. The GBSS judgement follows the observed signal pulse.
    x3, y3, w3, h3 = LEFT, impact_y, RIGHT - LEFT, impact_height
    svg.append(_rect(x3, y3, w3, h3, "#ffffff", stroke=GRID, radius=6))
    if signal_brief_only:
        svg.append(_text(x3 + 20, y3 + 31, "3. GBSS Impact / 战略影响", size=15, color=NAVY, weight=700))
        svg.append(_wrapped_text(
            x3 + 240,
            y3 + 30,
            "Evidence pending / 证据审核中: no GBSS conclusion / 暂不输出 GBSS 战略结论。",
            68,
            size=10,
            color="#43516a",
            max_lines=1,
            ellipsis=False,
        ))
    else:
        svg.append(_text(x3 + 20, y3 + 28, "3. GBSS Strategic Impact / 对 GBSS 战略主线的影响", size=17, color=NAVY, weight=700))
        for index, item in enumerate(impacts[:6]):
            row_y = y3 + 56 + index * 40
            fill, color = _priority_fill(item["priority"])
            svg.append(_rect(x3 + 20, row_y - 17, 54, 25, fill, radius=5))
            svg.append(_text(x3 + 35, row_y, item["priority"], size=12, color=color, weight=800))
            svg.append(_wrapped_text(x3 + 92, row_y - 5, item["theme"], 72, size=12, color=NAVY, weight=700, max_lines=1, ellipsis=False))
            svg.append(_wrapped_text(x3 + 92, row_y + 11, item["impact"], 96, size=10, color="#43516a", max_lines=2, line_gap=12, ellipsis=False))

    # 4. Theme and deep insight intentionally form one causal chain.
    x4, y4, w4, h4 = LEFT, insight_y, RIGHT - LEFT, insight_height
    svg.append(_rect(x4, y4, w4, h4, "#f8fbff", stroke="#bfdcff", radius=6))
    svg.append(_text(x4 + 20, y4 + 28, "4. Weekly Theme & Deep Insight / 本周主题研判与深度洞察", size=17, color=ANT_BLUE, weight=700))
    if signal_brief_only:
        svg.append(_wrapped_text(x4 + 20, y4 + 56, theme["topic"], 74, size=17, color=NAVY, weight=700, max_lines=2, line_gap=20, ellipsis=False))
        svg.append(_wrapped_text(x4 + 20, y4 + 94, theme["oneSentenceJudgement"], 104, size=11, color="#29364d", max_lines=2, line_gap=13, ellipsis=False))
        svg.append(_rect(x4 + 20, y4 + 122, w4 - 40, 1, "#d6eaff"))
        svg.append(_text(x4 + 20, y4 + 146, "Weekly Deep Insight / 本周深度洞察", size=14, color=ANT_BLUE, weight=700))
        svg.append(_text(x4 + 20, y4 + 170, "Insight / 洞察", size=10, color=MUTED, weight=700))
        svg.append(_wrapped_text(x4 + 130, y4 + 170, deep["insight"], 90, size=10, color=NAVY, weight=700, max_lines=2, line_gap=12, ellipsis=False))
        svg.append(_text(x4 + 20, y4 + 206, "Why now / 为何现在", size=10, color=MUTED, weight=700))
        svg.append(_wrapped_text(x4 + 150, y4 + 206, deep["whyNow"], 86, size=10, color="#43516a", max_lines=2, line_gap=12, ellipsis=False))
        svg.append(_text(x4 + 20, y4 + 242, "30-day Move / 30天动作", size=10, color=MUTED, weight=700))
        svg.append(_wrapped_text(x4 + 170, y4 + 242, deep["next30DayMove"], 82, size=10, color="#43516a", max_lines=2, line_gap=12, ellipsis=False))
    else:
        svg.append(_wrapped_text(x4 + 20, y4 + 56, theme["topic"], 68, size=18, color=NAVY, weight=700, max_lines=2, line_gap=22, ellipsis=False))
        svg.append(_wrapped_text(x4 + 20, y4 + 104, theme["oneSentenceJudgement"], 100, size=12, color="#29364d", max_lines=2, line_gap=15, ellipsis=False))
        svg.append(_wrapped_text(x4 + 20, y4 + 138, "Management Takeaway / 管理层结论: " + theme["managementTakeaway"], 96, size=11, color="#29364d", weight=700, max_lines=2, line_gap=14, ellipsis=False))
        svg.append(_rect(x4 + 20, y4 + 170, w4 - 40, 1, "#d6eaff"))
        svg.append(_text(x4 + 20, y4 + 196, "Weekly Deep Insight / 本周深度洞察", size=15, color=ANT_BLUE, weight=700))
        svg.append(_text(x4 + 20, y4 + 224, "Insight / 洞察", size=10, color=MUTED, weight=700))
        svg.append(_wrapped_text(x4 + 130, y4 + 224, deep["insight"], 86, size=11, color=NAVY, weight=700, max_lines=3, line_gap=13, ellipsis=False))
        svg.append(_text(x4 + 20, y4 + 268, "Why now / 为何现在", size=10, color=MUTED, weight=700))
        svg.append(_wrapped_text(x4 + 150, y4 + 268, deep["whyNow"], 82, size=10, color="#43516a", max_lines=2, line_gap=12, ellipsis=False))
        svg.append(_text(x4 + 20, y4 + 306, "30-day Move / 30天动作", size=10, color=MUTED, weight=700))
        svg.append(_wrapped_text(x4 + 170, y4 + 306, deep["next30DayMove"], 78, size=10, color="#43516a", max_lines=2, line_gap=12, ellipsis=False))

    # Access remains compact, but both QR codes stay separately labelled.
    x5, y5, w5, h5 = LEFT, access_y, RIGHT - LEFT, access_height
    svg.append(_rect(x5, y5, w5, h5, "#ffffff", stroke="#bfdcff", radius=6))
    svg.append(_text(x5 + 20, y5 + 26, "5. Access / 查看方式", size=16, color=ANT_BLUE, weight=700))
    svg.append(_wrapped_text(x5 + 20, y5 + 50, "Scan Full Report for detail. 扫报告详情码查看完整调研；如无权限，先扫入群码。", 62, size=10, color="#43516a", max_lines=2, line_gap=12, ellipsis=False))
    qr_size = 76
    detail_x = x5 + 590
    group_x = x5 + 690
    svg.append(_wrapped_text(detail_x, y5 + 20, "Full Report / 报告详情", 16, size=8, color="#43516a", weight=700, max_lines=2, line_gap=10, ellipsis=False))
    svg.append(_qr_svg(detail_url, detail_x, y5 + 32, qr_size))
    svg.append(_wrapped_text(group_x, y5 + 20, "Join Group / 入群权限", 16, size=8, color="#43516a", weight=700, max_lines=2, line_gap=10, ellipsis=False))
    svg.append(_image_svg(group_qr_path, group_x, y5 + 32, qr_size, "Join Group / 入群"))

    svg.append(_rect(LEFT, canvas_height - 32, RIGHT - LEFT, 1, GRID))
    svg.append(_wrapped_text(LEFT, canvas_height - 14, "Methodology / 方法: accepted News; 7D scoring; evidence lineage in Evidence Bank and Claim Ledger.", 96, size=8, color=MUTED, max_lines=1, ellipsis=False))
    svg.append("</svg>")
    return "\n".join(svg)


def one_page_report_markdown(svg: str, title: str) -> str:
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return "\n".join([
        f"# {title}",
        "",
        f"![{title}](data:image/svg+xml;base64,{encoded})",
        "",
        "If DingTalk does not render the image directly, open the original image or attachment to view the one-page report.",
        "如钉钉客户端未直接渲染图片，请打开原图/附件查看一页式报告。",
    ])


def save_one_page_report(svg: str, output_dir: Path, filename_stem: str) -> Tuple[Path, Optional[Path]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    svg_path = output_dir / f"{filename_stem}.svg"
    svg_path.write_text(svg, encoding="utf-8")
    png_path = output_dir / f"{filename_stem}.png"
    try:
        subprocess.run(
            ["sips", "-s", "format", "png", str(svg_path), "--out", str(png_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        png_path = None
    return svg_path, png_path if png_path and png_path.exists() else None
