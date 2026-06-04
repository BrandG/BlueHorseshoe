"""GORDON factor briefing — candidates presented per ORTHOGONAL factor group.

Renders the locked factor groups (analysis/factor_groups.py) as side-by-side
columns, each with an honestly-earned confidence badge, so the human picks ACROSS
factors (real diversification) instead of trusting a single additive score that
anti-selects. A column is only "green" when its factor has a validated, sign-stable,
post-cost edge AND a validated within-factor ranking dimension.

Self-contained (does not touch html_reporter) so it can be previewed and wired
independently. Consumes the same candidate dicts produced by
postprocess.CandidateAssembler.build_top_candidates().
"""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

from bluehorseshoe.analysis.factor_groups import (
    AVOID, UNTESTED, VALIDATED, get_factor_groups,
)

_STATUS_STYLE = {
    VALIDATED: ("#1b5e20", "#e8f5e9", "✓ VALIDATED"),
    AVOID:     ("#b71c1c", "#fdecea", "✗ AVOID"),
    UNTESTED:  ("#616161", "#f0f0f0", "— UNTESTED"),
}


def _strategy_display(strategy_name: Optional[str]) -> Optional[str]:
    if not strategy_name:
        return None
    from bluehorseshoe.analysis.strategy_registry import get_strategy
    try:
        return get_strategy(strategy_name).display_name
    except ValueError:
        return None


def _reason_value(candidate: Dict[str, Any], key: str) -> Optional[str]:
    """Pull e.g. 'oversold_age' out of the candidate's formatted reasons list."""
    for r in candidate.get("reasons", []) or []:
        if r.startswith(f"{key}="):
            return r.split("=", 1)[1]
    return None


def _candidates_for(group, candidates: List[Dict[str, Any]], top_n: int) -> List[Dict[str, Any]]:
    display = _strategy_display(group.strategy)
    if display is None:
        return []
    rows = [c for c in candidates if c.get("strategy") == display]
    # Rank by score, which is monotone in the validated dimension by construction.
    rows.sort(key=lambda c: c.get("score", 0), reverse=True)
    return rows[:top_n]


def _render_row(group, c: Dict[str, Any]) -> str:
    sym = html.escape(str(c.get("symbol", "")))
    entry = c.get("close", 0) or 0
    stop = c.get("stop_loss", 0) or 0
    tgt = c.get("target", 0) or 0
    # Surface the validated ranking dimension explicitly when we have it.
    depth = _reason_value(c, "oversold_age")
    rsi = _reason_value(c, "rsi")
    dvol = _reason_value(c, "dollar_vol_M")
    badge = ""
    if group.ranking_dimension == "oversold_age" and depth is not None:
        try:
            d = int(float(depth))
        except (TypeError, ValueError):
            d = 0
        dots = "●" * min(d, 10)
        extra = []
        if rsi is not None:
            extra.append(f"RSI {float(rsi):.0f}")
        if dvol is not None:
            extra.append(f"${float(dvol):.0f}M")
        badge = (f"<span class='depth'>{dots}</span> "
                 f"<span class='meta'>age {d} · {' · '.join(extra)}</span>")
    return (
        "<tr>"
        f"<td class='sym'>{sym}</td>"
        f"<td class='px'>{entry:.2f}</td>"
        f"<td class='px stop'>{stop:.2f}</td>"
        f"<td class='px tgt'>{tgt:.2f}</td>"
        f"<td class='rank'>{badge}</td>"
        "</tr>"
    )


def _render_column(group, candidates: List[Dict[str, Any]], top_n: int) -> str:
    color, bg, label = _STATUS_STYLE.get(group.status, _STATUS_STYLE[UNTESTED])
    rows = _candidates_for(group, candidates, top_n)

    if group.strategy and rows:
        rank_note = (f"ranked by <b>{html.escape(group.ranking_dimension)}</b>"
                     if group.ranking_dimension else "ranking not validated")
        body = (
            "<table class='cands'>"
            "<tr><th>sym</th><th>entry</th><th>stop</th><th>target</th>"
            f"<th>{html.escape(group.ranking_dimension or '')}</th></tr>"
            + "".join(_render_row(group, c) for c in rows) +
            "</table>"
        )
    elif group.status == VALIDATED:
        rank_note = "ranked by " + html.escape(group.ranking_dimension or "")
        body = "<p class='empty'>no candidates firing today</p>"
    else:
        rank_note = ("ranking dimension <b>not validated</b> — shown for context, "
                     "not a buy" if group.status == AVOID
                     else "not yet screened — no validated ranking")
        body = "<p class='empty'>—</p>"

    return (
        f"<div class='col' style='--c:{color};--bg:{bg}'>"
        f"<div class='col-head'>"
        f"<div class='label'>{html.escape(group.label)}</div>"
        f"<div class='badge'>{label}</div>"
        f"<div class='edge'>{html.escape(group.edge_summary)}</div>"
        f"<div class='ranknote'>{rank_note}</div>"
        f"</div>"
        f"{body}"
        f"<div class='note'>{html.escape(group.note)}</div>"
        f"</div>"
    )


_CSS = """
body{font:13px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;margin:18px;color:#222;background:#fafafa}
h1{font-size:18px;margin:0 0 2px} .sub{color:#666;margin:0 0 16px;font-size:12px}
.cols{display:flex;gap:12px;align-items:flex-start;overflow-x:auto}
.col{flex:1 1 0;min-width:230px;border:1px solid #ddd;border-top:4px solid var(--c);
     border-radius:6px;background:#fff;padding:10px}
.col-head{border-bottom:1px solid #eee;padding-bottom:8px;margin-bottom:8px}
.label{font-weight:700;font-size:13px}
.badge{display:inline-block;margin-top:4px;font-size:11px;font-weight:700;color:var(--c);
       background:var(--bg);padding:2px 6px;border-radius:3px}
.edge{font-size:11px;color:#444;margin-top:4px} .ranknote{font-size:11px;color:#666;margin-top:3px}
table.cands{width:100%;border-collapse:collapse;margin-top:4px}
.cands th{font-size:10px;text-transform:uppercase;color:#999;text-align:left;padding:2px 4px}
.cands td{padding:3px 4px;border-top:1px solid #f0f0f0} .sym{font-weight:700}
.px{font-variant-numeric:tabular-nums;text-align:right} .stop{color:#b71c1c} .tgt{color:#1b5e20}
.depth{color:#1b5e20;letter-spacing:-1px} .meta{font-size:10px;color:#777}
.empty{color:#bbb;font-style:italic;padding:8px 2px}
.note{font-size:10.5px;color:#777;border-top:1px dashed #eee;margin-top:8px;padding-top:6px}
"""


def render_factor_briefing(candidates: List[Dict[str, Any]],
                           target_date: Optional[str] = None,
                           top_n: int = 8) -> str:
    """Full standalone HTML doc for the factor briefing."""
    cols = "".join(_render_column(g, candidates, top_n) for g in get_factor_groups())
    when = f" — {html.escape(target_date)}" if target_date else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>GORDON Factor Briefing{when}</title><style>{_CSS}</style></head><body>"
        f"<h1>GORDON Factor Briefing{when}</h1>"
        "<p class='sub'>Candidates by orthogonal factor (participation ratio ≈ 3.7). "
        "Pick across green columns for real diversification — never sum across them. "
        "Confidence is measured edge, not signal strength.</p>"
        f"<div class='cols'>{cols}</div></body></html>"
    )
