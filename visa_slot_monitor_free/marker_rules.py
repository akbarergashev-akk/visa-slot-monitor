"""Conservative interpretation of Embassy calendar image markers.

Based on the user's read-only October 2026 inspection:
icon_disabled.svg is closed. No image does NOT mean bookable.
Any other image needs human confirmation; never report it as a booked/open slot.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

CLOSED_MARKER = "icon_disabled.svg"

# Only in the monthly calendar (not legend); no session data or URLs returned.
CALENDAR_MARKERS_JS = r"""() => {
  const table = document.querySelector('table.sc_cal_month');
  if (!table) return {status:'not_found', cells:0, marks:[]};
  const safeAsset = el => {
    const src = el.getAttribute('src') || '';
    if (!src || /^(data:|blob:)/i.test(src)) return 'unidentified_image';
    try {
      const name = new URL(src, location.href).pathname.split('/').pop();
      return /^[a-z][a-z0-9_.-]{0,65}\.(svg|png|gif|webp|jpe?g)$/i.test(name)
        ? name.toLowerCase() : 'unidentified_image';
    } catch (_) { return 'unidentified_image'; }
  };
  const cells = [...table.querySelectorAll('td')];
  const marks = [];
  cells.forEach((cell, index) => {
    const dayEl = cell.querySelector('.sc_cal_date');
    const dayText = (dayEl?.textContent || '').trim();
    const day = /^\d{1,2}$/.test(dayText) ? Number(dayText) : null;
    const assets = [...cell.querySelectorAll('img')]
        .filter(x=>!!x.getClientRects().length).map(safeAsset);
    if (assets.length) marks.push({cell:index + 1, day, assets});
  });
  return {status:'ok', cells:cells.length, marks};
}"""

@dataclass(frozen=True)
class MarkerResult:
    cell: int
    day: int | None
    assets: tuple[str, ...]
    classification: str  # closed | needs_review

def classify_calendar_marks(payload: dict) -> list[MarkerResult]:
    if payload.get('status') != 'ok' or int(payload.get('cells') or 0) < 28:
        raise ValueError('Not a confirmed monthly calendar')
    output = []
    for mark in payload.get('marks', []):
        assets = tuple(str(a).lower() for a in mark['assets'])
        if not assets:
            continue
        classification = 'closed' if all(a == CLOSED_MARKER for a in assets) else 'needs_review'
        output.append(MarkerResult(
            cell=int(mark['cell']), day=mark.get('day'),
            assets=assets, classification=classification,
        ))
    return output

def newly_unrecognized(previous: Iterable[MarkerResult],
                       current: Iterable[MarkerResult]) -> list[MarkerResult]:
    old = {(p.cell, p.day, p.assets) for p in previous if p.classification == 'needs_review'}
    return [v for v in current if v.classification == 'needs_review'
            and (v.cell, v.day, v.assets) not in old]
