#!/usr/bin/env python3
"""Safe Colab notebook cell entry / execution primitives for CDP operators.

Policy (mandatory):
  A. Prefer running an existing cell whose source already matches — do not edit.
  B. If source must change: use Colab ``cell.setText(desired)`` then verify
     with ``getText()`` before run (never caret-append / ``Input.insertText``).
  C. Never send text blindly to the current caret.
  D. Operations must be idempotent: retry must not produce
     ``control_panel()control_panel()``.
  E. Execute via the cell's ``<colab-run-button>``, not by retyping source.

This module is orchestration-only. It does not change Package 4.12.3 semantics.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class CellWriteMode(str, Enum):
    """How an operator should apply desired cell source."""

    RUN_EXISTING = "RUN_EXISTING"  # source already correct — run only (no mutation)
    REPLACE_SELECT_ALL = "REPLACE_SELECT_ALL"  # atomic replace via setText (never caret-append)
    ABORT_AMBIGUOUS = "ABORT_AMBIGUOUS"  # do not type


@dataclass(frozen=True)
class CellWritePlan:
    mode: CellWriteMode
    current_source: str
    desired_source: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d


def normalize_cell_source(text: str | None) -> str:
    """Normalize editor text for comparison (NBSP, trailing newlines)."""
    if text is None:
        return ""
    return text.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n").strip()


def sources_equivalent(current: str | None, desired: str | None) -> bool:
    return normalize_cell_source(current) == normalize_cell_source(desired)


def would_duplicate_on_append(current: str | None, fragment: str | None) -> bool:
    """True if caret-append of fragment onto current would create a duplicate glue.

    Example: current='control_panel()', fragment='control_panel()' →
    'control_panel()control_panel()'.
    """
    cur = normalize_cell_source(current)
    frag = normalize_cell_source(fragment)
    if not frag:
        return False
    if not cur:
        return False
    glued = (cur + frag).replace("\n", "").replace(" ", "")
    # Exact doubled command (most common Colab operator failure)
    if frag and glued == (frag + frag).replace("\n", "").replace(" ", ""):
        return True
    # Current already ends with the fragment
    if cur.endswith(frag):
        return True
    # Current already contains the exact desired one-liner command
    if cur.replace(" ", "") == frag.replace(" ", ""):
        return True
    return False


def plan_cell_source_write(current: str | None, desired: str | None) -> CellWritePlan:
    """Decide how to apply desired source without caret-append duplication.

    Idempotent: if current already equals desired → RUN_EXISTING (no typing).
    Otherwise → REPLACE_SELECT_ALL (never blind insert).
    """
    cur = normalize_cell_source(current)
    des = normalize_cell_source(desired)
    if not des:
        return CellWritePlan(
            mode=CellWriteMode.ABORT_AMBIGUOUS,
            current_source=cur,
            desired_source=des,
            reason="desired source is empty",
        )
    if sources_equivalent(cur, des):
        return CellWritePlan(
            mode=CellWriteMode.RUN_EXISTING,
            current_source=cur,
            desired_source=des,
            reason="source already matches; do not edit — run existing cell only",
        )
    if would_duplicate_on_append(cur, des):
        return CellWritePlan(
            mode=CellWriteMode.REPLACE_SELECT_ALL,
            current_source=cur,
            desired_source=des,
            reason=(
                "append-at-caret would duplicate command "
                f"({cur!r}+{des!r}); must select-all/replace"
            ),
        )
    return CellWritePlan(
        mode=CellWriteMode.REPLACE_SELECT_ALL,
        current_source=cur,
        desired_source=des,
        reason="source differs; select-all/replace then verify before run",
    )


def verify_cell_source_before_run(actual: str | None, expected: str | None) -> tuple[bool, str]:
    """Gate execution: only proceed when verified source matches expected."""
    if sources_equivalent(actual, expected):
        return True, "verified"
    return (
        False,
        f"source mismatch before run: actual={normalize_cell_source(actual)!r} "
        f"expected={normalize_cell_source(expected)!r}",
    )


# ---------------------------------------------------------------------------
# Browser-side JS helpers (string constants for Runtime.evaluate)
# ---------------------------------------------------------------------------

JS_LIST_CODE_CELLS = r"""
(() => {
  const cells = [...document.querySelectorAll('div.cell.code')];
  return cells.map((c, i) => {
    let src = '';
    try { src = typeof c.getText === 'function' ? String(c.getText()) : ''; } catch (e) { src = ''; }
    return {
      index: i,
      sourceTrim: src.replace(/\u00a0/g, ' ').trim(),
      len: src.length,
      focused: /focused/.test(c.className || ''),
      hasSetText: typeof c.setText === 'function',
    };
  });
})()
"""

JS_FIND_SHORT_CONTROL_PANEL_CELL = r"""
(() => {
  const cells = [...document.querySelectorAll('div.cell.code')];
  for (let i = 0; i < cells.length; i++) {
    let src = '';
    try { src = typeof cells[i].getText === 'function' ? String(cells[i].getText()) : ''; } catch (e) {}
    src = src.replace(/\u00a0/g, ' ').trim();
    const compact = src.replace(/\s+/g, '');
    if (compact.includes('control_panel()') && src.length < 80) {
      return { index: i, source: src, compact, found: true };
    }
  }
  // Also detect invocation cell that was overwritten (last short cell after menu)
  return { found: false, cellCount: cells.length };
})()
"""

JS_FIND_CONTROL_PANEL_INVOCATION_CELL = r"""
(() => {
  // Canonical notebook: large Cell 11 menu definition, then a short invocation cell.
  const cells = [...document.querySelectorAll('div.cell.code')];
  let menuIdx = -1;
  for (let i = 0; i < cells.length; i++) {
    let src = '';
    try { src = String(cells[i].getText() || ''); } catch (e) {}
    if (/def control_panel\s*\(/.test(src) && /=== AI Studio Control Panel ===/.test(src)) {
      menuIdx = i;
      break;
    }
  }
  if (menuIdx < 0) return { found: false, reason: 'menu_def_missing' };
  // Prefer next code cell as invocation cell
  const invIdx = menuIdx + 1;
  if (invIdx >= cells.length) return { found: false, reason: 'no_cell_after_menu', menuIdx };
  let inv = '';
  try { inv = String(cells[invIdx].getText() || ''); } catch (e) {}
  inv = inv.replace(/\u00a0/g, ' ').trim();
  return {
    found: true,
    menuIdx,
    index: invIdx,
    source: inv,
    compact: inv.replace(/\s+/g, ''),
    isDup: inv.replace(/\s+/g, '') === 'control_panel()control_panel()',
    isExact: inv.replace(/\s+/g, '') === 'control_panel()',
  };
})()
"""


def js_focus_cell_by_index(index: int) -> str:
    return f"""
(() => {{
  const cells = [...document.querySelectorAll('div.cell.code')];
  const cell = cells[{int(index)}];
  if (!cell) return {{ ok: false, reason: 'cell_index_missing' }};
  cell.scrollIntoView({{ block: 'center' }});
  if (typeof cell.focusCell_ === 'function') {{
    try {{ cell.focusCell_(); }} catch (e) {{}}
  }}
  cell.click();
  return {{ ok: true, index: {int(index)} }};
}})()
"""


def js_read_cell_source(index: int) -> str:
    """Prefer Colab cell.getText() — cm-content is often unmounted when unfocused."""
    return f"""
(() => {{
  const cells = [...document.querySelectorAll('div.cell.code')];
  const cell = cells[{int(index)}];
  if (!cell) return {{ ok: false }};
  let src = '';
  try {{
    if (typeof cell.getText === 'function') src = String(cell.getText() || '');
  }} catch (e) {{
    return {{ ok: false, reason: String(e) }};
  }}
  src = src.replace(/\\u00a0/g, ' ');
  return {{ ok: true, source: src, sourceTrim: src.trim(), via: 'getText' }};
}})()
"""


def js_set_cell_source(index: int, text: str) -> str:
    """Atomic replace via Colab cell.setText — never caret-append."""
    payload = json.dumps(text)
    return f"""
(() => {{
  const cells = [...document.querySelectorAll('div.cell.code')];
  const cell = cells[{int(index)}];
  if (!cell) return {{ ok: false, reason: 'missing_cell' }};
  if (typeof cell.setText !== 'function' || typeof cell.getText !== 'function') {{
    return {{ ok: false, reason: 'setText/getText unavailable' }};
  }}
  const before = String(cell.getText() || '');
  cell.setText({payload});
  const after = String(cell.getText() || '');
  return {{
    ok: true,
    before: before.replace(/\\u00a0/g, ' ').trim(),
    after: after.replace(/\\u00a0/g, ' ').trim(),
    via: 'setText',
  }};
}})()
"""


def js_cell_output_text(index: int) -> str:
    return f"""
(() => {{
  const cells = [...document.querySelectorAll('div.cell.code')];
  const cell = cells[{int(index)}];
  if (!cell) return {{ ok: false }};
  const outs = [...cell.querySelectorAll(
    '.output, .output-area, colab-output-area, .output_subarea, .output-content, pre'
  )];
  const text = outs.map(o => o.innerText || '').join('\\n');
  return {{
    ok: true,
    text,
    textTrim: text.trim(),
    hasSyntaxError: /SyntaxError/i.test(text),
    hasMarker: /CDP_SAFE_CELL_EXEC_OK/.test(text),
  }};
}})()
"""


def js_clear_cell_output(index: int) -> str:
    """Clear stale output so the next run's evidence is unambiguous."""
    return f"""
(() => {{
  const cells = [...document.querySelectorAll('div.cell.code')];
  const cell = cells[{int(index)}];
  if (!cell) return {{ ok: false, reason: 'missing_cell' }};
  const names = [];
  for (const k of Object.getOwnPropertyNames(cell)) names.push(k);
  const proto = Object.getOwnPropertyNames(Object.getPrototypeOf(cell) || {{}});
  // Prefer official clear helpers when present
  for (const fn of ['clearOutput', 'clearOutputs', 'clear_output']) {{
    if (typeof cell[fn] === 'function') {{
      try {{ cell[fn](); return {{ ok: true, via: fn }}; }} catch (e) {{}}
    }}
  }}
  // Toolbar "clear output" / icon
  const btns = [...cell.querySelectorAll('button, [role="button"], paper-icon-button, mat-icon')];
  for (const el of btns) {{
    const label = ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '') + ' ' + (el.textContent || '')).toLowerCase();
    if (/clear.*output|clear output/.test(label)) {{
      (el.closest('button') || el).click();
      return {{ ok: true, via: 'toolbar', label }};
    }}
  }}
  return {{ ok: false, reason: 'no_clear', props: names.slice(0, 40), proto: proto.slice(0, 40) }};
}})()
"""


def js_click_cell_run(index: int) -> str:
    """Click the cell's own Run control — never retype source as part of execution."""
    return f"""
(() => {{
  const cells = [...document.querySelectorAll('div.cell.code')];
  const cell = cells[{int(index)}];
  if (!cell) return {{ ok: false, reason: 'missing_cell' }};

  // Preferred: <colab-run-button> (Lit element; often no aria-label)
  const runBtn = cell.querySelector('colab-run-button');
  if (runBtn) {{
    const beforeCount = runBtn.executionCount;
    const beforeState = runBtn.executionState;
    // Click once via shadow inner control when present; else host.
    let via = 'colab-run-button.host';
    try {{
      const root = runBtn.shadowRoot || runBtn.renderRoot;
      const inner = root && root.querySelector('div, button, [role="button"]');
      if (inner) {{
        inner.click();
        via = 'colab-run-button.shadow';
      }} else {{
        runBtn.click();
      }}
    }} catch (e) {{
      runBtn.click();
      via = 'colab-run-button.host_fallback';
    }}
    return {{
      ok: true,
      via,
      beforeCount,
      beforeState,
      afterCount: runBtn.executionCount,
      afterState: runBtn.executionState,
    }};
  }}

  const candidates = [...cell.querySelectorAll(
    '[aria-label*="Run cell"], [aria-label*="Run"], [title*="Run"], button, paper-icon-button'
  )];
  for (const el of candidates) {{
    const label = ((el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '') + ' ' + (el.textContent || '')).toLowerCase();
    if (/run/.test(label) && !/runtime|run all|run before|run after/.test(label)) {{
      el.click();
      return {{ ok: true, via: 'labeled', label }};
    }}
  }}
  return {{ ok: false, reason: 'no_run_control' }};
}})()
"""


def js_run_button_status(index: int) -> str:
    return f"""
(() => {{
  const cells = [...document.querySelectorAll('div.cell.code')];
  const cell = cells[{int(index)}];
  if (!cell) return {{ ok: false }};
  const runBtn = cell.querySelector('colab-run-button');
  if (!runBtn) return {{ ok: false, reason: 'no_run_button' }};
  return {{
    ok: true,
    executionCount: runBtn.executionCount,
    executionState: runBtn.executionState,
    busy: !!runBtn.busy,
    hasError: !!runBtn.hasError,
  }};
}})()
"""


JS_RUNTIME_CONNECTED_HINT = r"""
(() => {
  const t = (document.body && document.body.innerText) ? document.body.innerText.slice(0, 4000) : '';
  return {
    connectedToken: /\bConnected\b/i.test(t),
    L4: /\bL4\b/.test(t),
    RAM: /\bRAM\b/.test(t),
    Disk: /\bDisk\b/.test(t),
    python3: /Python 3/i.test(t),
    // Operator policy: Connected OR (GPU chip + RAM/Disk) counts as connected evidence
    connectedEvidence: /\bConnected\b/i.test(t)
      || (/\bL4\b|\bT4\b|\bA100\b|\bV100\b/.test(t) && /\bRAM\b/.test(t)),
  };
})()
"""
