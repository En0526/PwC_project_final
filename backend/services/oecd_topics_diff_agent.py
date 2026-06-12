"""OECD 英文議題頁（/en/topics/*.html）差異：可讀中文摘要，避免整頁英文雜訊直接塞進通知。"""
from __future__ import annotations

import re
from urllib.parse import urlparse


def is_oecd_topics_page_url(url: str) -> bool:
    """與 site_profiles 的 OECD topics 截取路徑一致（含 global-minimum-tax、beps.html 等）。"""
    try:
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()
        return host.endswith("oecd.org") and "/topics/" in path and path.endswith(".html")
    except Exception:
        return False


# 頁首／導覽／無關短行（比對時忽略）
_NOISE_LINE_RES = [
    re.compile(r"^skip to main", re.I),
    re.compile(r"^global minimum tax\s*\|\s*oecd", re.I),
    re.compile(r"^base erosion", re.I),
    re.compile(r"^oecd\s*$", re.I),
    re.compile(r"^topics$", re.I),
    re.compile(r"^search$", re.I),
    re.compile(r"^english$", re.I),
    re.compile(r"^share$", re.I),
    re.compile(r"^facebook$", re.I),
    re.compile(r"^twitter$", re.I),
    re.compile(r"^linkedin$", re.I),
    re.compile(r"^see all publications$", re.I),
    re.compile(r"^virtual$", re.I),
]


def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())[:400]


def _strip_oecd_snapshot_prefix(text: str) -> str:
    t = (text or "").strip()
    m = re.search(r"(?i)Latest\s+insights", t)
    if m:
        return t[m.start() :].strip()
    return t


def _slice_monitoring_zone(text: str) -> str:
    """只保留 Latest insights 起、Related events 前的區塊（與截取邏輯對齊）。"""
    t = _strip_oecd_snapshot_prefix(text)
    m = re.search(r"(?i)Latest\s+insights", t)
    if not m:
        return t
    rest = t[m.start() :]
    m_end = re.search(r"(?i)(^|\n)\s*Related\s+events\b", rest)
    if m_end:
        return rest[: m_end.start()].strip()
    return rest.strip()


def _significant_lines(zone: str) -> list[str]:
    """取出可供比對的內容行，略過明顯導覽。"""
    out: list[str] = []
    for raw in (zone or "").splitlines():
        s = raw.strip()
        if len(s) < 10:
            continue
        if any(p.search(s) for p in _NOISE_LINE_RES):
            continue
        out.append(s)
    return out


def _lines_for_keys(keys: set[str], source_lines: list[str]) -> list[str]:
    """依出現順序還原原文列（最多 12 筆）。"""
    seen: set[str] = set()
    out: list[str] = []
    for ln in source_lines:
        k = _norm_key(ln)
        if k in keys and k not in seen and len(k) > 15:
            seen.add(k)
            out.append(ln.strip())
    return out[:12]


def generate_oecd_topics_diff_report(
    *,
    previous_snapshot: str,
    current_snapshot: str,
    url: str = "",
) -> str | None:
    """
    產出繁中摘要。

    示意（實際依列表變化）：
        【OECD 議題頁｜更新摘要】
        範圍：Latest insights、Related publications（不含 Related events）
        【本次較前次多出（重點行）】
          · OECD releases new toolkit …
        【本次較前次不再出現】
          · …
    """
    if not url:
        msrc = re.search(r"\[來源\]\s*(\S+)", (previous_snapshot or "") + "\n" + (current_snapshot or ""))
        if msrc:
            url = msrc.group(1)
    if not is_oecd_topics_page_url(url):
        return None

    prev_zone = _slice_monitoring_zone(previous_snapshot)
    cur_zone = _slice_monitoring_zone(current_snapshot)
    prev_lines = _significant_lines(prev_zone)
    cur_lines = _significant_lines(cur_zone)
    prev_set = {_norm_key(x) for x in prev_lines if len(_norm_key(x)) > 15}
    cur_set = {_norm_key(x) for x in cur_lines if len(_norm_key(x)) > 15}

    added_keys = cur_set - prev_set
    removed_keys = prev_set - cur_set

    lines_out: list[str] = [
        "【OECD 議題頁｜更新摘要】",
        "範圍：Latest insights、Related publications（不含 Related events／活動區）",
        "",
    ]

    len_prev, len_cur = len(previous_snapshot or ""), len(current_snapshot or "")
    if len_prev > 5000 and len_cur < 2500:
        lines_out.append("※ 提示：上一筆快照較像整頁、本次較短；建議多按一次「立即檢查」讓兩次都用同一種區塊截取。")
        lines_out.append("")
    elif len_cur > 5000 and len_prev < 2500:
        lines_out.append("※ 提示：本次快照較長，可能曾以整頁比對；之後會以區塊為主。")
        lines_out.append("")

    if not added_keys and not removed_keys:
        lines_out.append("偵測到內容變更，但列表重點行幾乎相同（可能為順序、空白或輪播微調）。")
        lines_out.append('建議在「目前追蹤」點「看差異」查看完整並排。')
        return "\n".join(lines_out)

    added = _lines_for_keys(added_keys, cur_lines)
    removed = _lines_for_keys(removed_keys, prev_lines)

    if added:
        lines_out.append("【本次較前次多出（重點行）】")
        for t in added:
            short = t if len(t) <= 160 else t[:157] + "…"
            lines_out.append("  · " + short)
        lines_out.append("")
    if removed:
        lines_out.append("【本次較前次不再出現】")
        for t in removed:
            short = t if len(t) <= 160 else t[:157] + "…"
            lines_out.append("  · " + short)

    return "\n".join(lines_out).strip()
