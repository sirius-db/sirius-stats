// Shared between index.html and labels.html -- kept as one file loaded by both pages
// (via base.html) instead of duplicated inline <script> blocks, per Cursor's review on
// PR #7.

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Matches sirius-db/sirius's own label colors (verified against `gh api
// repos/sirius-db/sirius/labels`). Used only when a priority label currently has zero
// open issues/PRs, so fetch_metrics.py never captured its color that day (color stays
// null in that case) -- see priority_counts's pre-initialized keys in fetch_metrics.py.
const PRIORITY_COLOR_FALLBACK = {
  '! - P0': '#b60205',
  '! - P1': '#d93f0b',
  '! - P2': '#fbca04',
  '! - P3': '#9198a1'
};

// Cycled across however many non-priority labels a chart needs -- unlike priority
// labels, "other" labels aren't fixed in advance, so there's no dedicated color per
// label the way PRIORITY_COLOR_FALLBACK covers P0-P3.
const LABEL_PALETTE = ['#3a7bd5', '#2ecc71', '#e74c3c', '#f0a500', '#9b59b6', '#1abc9c', '#e67e22', '#34495e', '#16a085', '#8e44ad'];

function buildTable(header, rows) {
  const table = document.createElement('table');

  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  for (const h of header) {
    const th = document.createElement('th');
    th.textContent = h;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (const row of rows) {
    const tr = document.createElement('tr');
    for (const cell of row) {
      const td = document.createElement('td');
      const items = Array.isArray(cell) ? cell : [cell];
      for (const item of items) {
        td.appendChild(buildCellItem(item));
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  return table;
}

// A cell (or one entry in a multi-label cell) can be a plain value, {text, href} for a
// link, {text, dotColor} for a small colored dot next to a label name (so its color is
// recognizable at a glance without needing to read GitHub's own styling), or both.
// Only wrap in the .label-item span when there's a dot to show -- plain cells (dates,
// numbers, links with no dot) render exactly as before, no extra inline-flex wrapper.
function buildCellItem(item) {
  const hasDot = item && typeof item === 'object' && 'dotColor' in item;
  const hasHref = item && typeof item === 'object' && 'href' in item;
  const text = item && typeof item === 'object' && 'text' in item ? item.text : item;

  const textNode = hasHref
    ? Object.assign(document.createElement('a'), {
        href: item.href, target: '_blank', rel: 'noopener noreferrer', textContent: text
      })
    : document.createTextNode(text);

  if (!hasDot) {
    return textNode;
  }

  const wrapper = document.createElement('span');
  wrapper.className = 'label-item';
  const dot = document.createElement('span');
  dot.className = 'label-dot';
  dot.style.backgroundColor = item.dotColor;
  wrapper.appendChild(dot);
  wrapper.appendChild(textNode);
  return wrapper;
}

function labelColorOf(labelColors, name) {
  return labelColors[name] ? `#${labelColors[name]}` : PRIORITY_COLOR_FALLBACK[name];
}
