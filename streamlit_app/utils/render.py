"""
render.py — Shared HTML rendering helpers for the Streamlit app.
"""

import html as html_lib
from typing import Optional

import pandas as pd
import streamlit as st

GRANICUS_PLAYER = (
    "https://corpuschristi.granicus.com/player/clip/{clip_id}"
    "?view_id=2&redirect=true&entrytime={ts}"
)

TOOLTIP_CSS = """
<style>
.cc-tooltip {
    position: relative;
    display: inline-block;
    border-bottom: 1px dotted #888;
    cursor: help;
    color: #888;
    font-size: 0.85em;
}
.cc-tooltip .cc-tooltiptext {
    visibility: hidden;
    width: 300px;
    background-color: #333;
    color: #fff;
    text-align: left;
    padding: 8px 10px;
    border-radius: 6px;
    position: absolute;
    z-index: 9999;
    bottom: 130%;
    left: 50%;
    margin-left: -150px;
    opacity: 0;
    transition: opacity 0.2s;
    font-size: 12px;
    line-height: 1.6;
    pointer-events: auto;
    white-space: normal;
}
.cc-tooltip:hover .cc-tooltiptext {
    visibility: visible;
    opacity: 1;
}
.cc-tooltiptext a {
    color: #7dd3fc;
    text-decoration: none;
}
.cc-tooltiptext a:hover {
    text-decoration: underline;
}
</style>
"""


def fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def time_cell(seconds: float, clip_id: Optional[str]) -> str:
    """Returns an HTML snippet for a timestamp cell — a tooltip link if clip_id is set, plain text otherwise."""
    label = html_lib.escape(fmt_time(seconds))
    if not clip_id:
        return label
    url = GRANICUS_PLAYER.format(clip_id=clip_id, ts=int(seconds))
    return (
        f'<span class="cc-timestamp-link"><a href="{url}" target="_blank" '
        f'title="Watch this moment in the source video">{label} ▶</a></span>'
    )


def granicus_quote_link(clip_id: Optional[str], start_time: Optional[float], label: Optional[str] = None) -> str:
    """Returns an inline '▶ MM:SS' link for use after a quote. Empty string if data unavailable."""
    if not clip_id or start_time is None:
        return ""
    url = GRANICUS_PLAYER.format(clip_id=clip_id, ts=int(start_time))
    display = label or fmt_time(start_time)
    return f'<a href="{url}" target="_blank" style="font-size:0.8em;color:#7dd3fc;text-decoration:none;margin-left:6px;">▶ {html_lib.escape(display)}</a>'


def render_transcript_table(df: pd.DataFrame, clip_id: Optional[str] = None, height: int = 500) -> None:
    """
    Renders a transcript segment table (Time, Speaker, Statement) as scrollable HTML.

    df must have columns: start_time (float), Speaker (str), Text (str).
    If df also has a 'clip_id' column, that value overrides the clip_id parameter per row.
    """
    rows_html = []
    for _, row in df.iterrows():
        row_clip_id = row["clip_id"] if "clip_id" in df.columns else clip_id
        t_html = time_cell(float(row["start_time"]), row_clip_id)
        speaker = html_lib.escape(str(row["Speaker"]))
        text = html_lib.escape(str(row["Text"]))
        rows_html.append(
            f"<tr>"
            f'<td style="width:80px;vertical-align:top;padding:5px 8px;border-bottom:1px solid #2a2a2a;white-space:nowrap;">{t_html}</td>'
            f'<td style="width:160px;vertical-align:top;padding:5px 8px;border-bottom:1px solid #2a2a2a;">{speaker}</td>'
            f'<td style="vertical-align:top;padding:5px 8px;border-bottom:1px solid #2a2a2a;">{text}</td>'
            "</tr>"
        )

    th = '<th style="padding:6px 8px;text-align:left;background:#1a1a1a;position:sticky;top:0;z-index:1;">'
    table_html = (
        f'<div style="max-height:{height}px;overflow-y:auto;border:1px solid #333;border-radius:4px;">'
        '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
        f"<thead><tr>{th}Time</th>{th}Speaker</th>{th}Statement</th></tr></thead>"
        "<tbody>" + "".join(rows_html) + "</tbody>"
        "</table></div>"
    )
    st.markdown(table_html, unsafe_allow_html=True)


def render_statements_table(df: pd.DataFrame, height: int = 350) -> None:
    """
    Renders a person's statement history (Date, Time, Statement) as scrollable HTML.

    df must have columns: Date (str), start_time (float), Text (str), clip_id (str or None).
    """
    rows_html = []
    for _, row in df.iterrows():
        t_html = time_cell(float(row["start_time"]), row.get("clip_id"))
        date = html_lib.escape(str(row["Date"]))
        text = html_lib.escape(str(row["Text"]))
        rows_html.append(
            f"<tr>"
            f'<td style="width:100px;vertical-align:top;padding:5px 8px;border-bottom:1px solid #2a2a2a;white-space:nowrap;">{date}</td>'
            f'<td style="width:70px;vertical-align:top;padding:5px 8px;border-bottom:1px solid #2a2a2a;white-space:nowrap;">{t_html}</td>'
            f'<td style="vertical-align:top;padding:5px 8px;border-bottom:1px solid #2a2a2a;">{text}</td>'
            "</tr>"
        )

    th = '<th style="padding:6px 8px;text-align:left;background:#1a1a1a;position:sticky;top:0;z-index:1;">'
    table_html = (
        f'<div style="max-height:{height}px;overflow-y:auto;border:1px solid #333;border-radius:4px;">'
        '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
        f"<thead><tr>{th}Date</th>{th}Time</th>{th}Statement</th></tr></thead>"
        "<tbody>" + "".join(rows_html) + "</tbody>"
        "</table></div>"
    )
    st.markdown(table_html, unsafe_allow_html=True)
