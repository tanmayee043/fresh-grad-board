"use strict";

const APPLIED_KEY = "fgb:applied";
const OTHER_OPEN_KEY = "fgb:other-open";
const THEME_KEY = "fgb:theme";

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: marks just won't persist */ }
  },
};

const $ = (id) => document.getElementById(id);
const state = {
  data: null,
  industry: "",
  role: "",
  applied: new Set(store.get(APPLIED_KEY, [])),
};

function timeAgo(epochSeconds) {
  const mins = Math.max(0, Math.round((Date.now() / 1000 - epochSeconds) / 60));
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function listLocations(locs) {
  const shown = locs.slice(0, 3);
  const extra = locs.length - shown.length;
  return shown.join("; ") + (extra > 0 ? ` and ${extra} more` : "");
}

function evidenceNode(job) {
  const p = document.createElement("span");
  if (job.basis === "posting") {
    p.append("Posting says ");
    const q = document.createElement("q");
    q.textContent = job.evidence;
    p.append(q);
  } else if (job.basis === "h1b") {
    p.textContent = `Employer had ${job.h1b_approvals.toLocaleString()} H-1B petitions approved in FY${state.data.h1b_fiscal_year}. ` +
      (job.has_description ? "The posting doesn't mention sponsorship." : "Check the posting for sponsorship.");
  } else if (job.basis === "defense") {
    p.textContent = "Defense employer. These roles usually need U.S. citizenship or a clearance.";
  } else {
    p.textContent = job.has_description
      ? "The posting doesn't mention sponsorship and we found no H-1B history."
      : "We couldn't read this posting. Check it for sponsorship.";
  }
  return p;
}

const LETTER_COLORS = ["#2f6f8f", "#7a4fb0", "#b0503c", "#3f7d4e", "#a6741a", "#4b5bb5", "#a1436f", "#3d7a7a"];

function letterLogo(el, company) {
  const name = company.replace(/^the\s+/i, "");
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  el.replaceChildren(name.charAt(0).toUpperCase());
  el.classList.add("letter");
  el.style.background = LETTER_COLORS[hash % LETTER_COLORS.length];
}

const LOGO_SOURCES = [
  // The first service answers unknown sites with a generic 16px globe, so only trust bigger icons.
  { url: (d) => `https://www.google.com/s2/favicons?domain=${d}&sz=64`, minWidth: 17 },
  { url: (d) => `https://icons.duckduckgo.com/ip3/${d}.ico`, minWidth: 1 },
];

function renderLogo(el, job, source = 0) {
  if (!job.domain || source >= LOGO_SOURCES.length) return letterLogo(el, job.company);
  const { url, minWidth } = LOGO_SOURCES[source];
  const next = () => renderLogo(el, job, source + 1);
  const img = new Image();
  img.alt = "";
  img.loading = "lazy";
  img.decoding = "async";
  img.referrerPolicy = "no-referrer";
  img.onload = () => { if (img.naturalWidth < minWidth) next(); };
  img.onerror = next;
  img.src = url(encodeURIComponent(job.domain));
  el.replaceChildren(img);
}

function renderRow(job) {
  const node = $("job-row").content.firstElementChild.cloneNode(true);
  renderLogo(node.querySelector(".logo"), job);
  node.querySelector(".company").textContent = job.company;
  const link = node.querySelector(".title a");
  link.textContent = job.title;
  link.href = job.url;
  const meta = node.querySelector(".meta");
  const role = document.createElement("span");
  role.className = "role";
  role.textContent = job.role;
  meta.append(role, ` role in ${listLocations(job.locations)}`);
  node.querySelector(".evidence").append(evidenceNode(job));
  const posted = node.querySelector(".posted");
  posted.dateTime = new Date(job.posted_at * 1000).toISOString();
  posted.textContent = `Posted ${timeAgo(job.posted_at)}`;
  const apply = node.querySelector(".apply");
  apply.href = job.url;
  apply.setAttribute("aria-label", `Apply to ${job.title} at ${job.company}`);

  const box = node.querySelector(".applied input");
  box.checked = state.applied.has(job.id);
  box.setAttribute("aria-label", `Mark ${job.title} at ${job.company} as applied`);
  node.classList.toggle("is-applied", box.checked);
  box.addEventListener("change", () => {
    if (box.checked) state.applied.add(job.id); else state.applied.delete(job.id);
    store.set(APPLIED_KEY, [...state.applied]);
    node.classList.toggle("is-applied", box.checked);
    if ($("hideApplied").checked) render();
  });
  return node;
}

const sponsorshipFilter = () => document.querySelector('input[name="sponsorship"]:checked').value;

function filtered({ ignore = "" } = {}) {
  const sponsorship = ignore === "sponsorship" ? "all" : sponsorshipFilter();
  const q = $("q").value.trim().toLowerCase();
  const since = Date.now() / 1000 - Number($("window").value) * 3600;
  return state.data.jobs.filter((j) =>
    j.posted_at >= since &&
    (sponsorship === "all" || (sponsorship === "yes") === (j.sponsorship === "yes")) &&
    (ignore === "role" || !state.role || j.role === state.role) &&
    (!$("remote").checked || j.remote) &&
    (!$("hideApplied").checked || !state.applied.has(j.id)) &&
    (ignore === "industry" || !state.industry || j.industry === state.industry) &&
    (!q || `${j.company} ${j.title} ${j.locations.join(" ")}`.toLowerCase().includes(q))
  );
}

// One row of filter chips: `key` is the job field and the state slot it filters on.
// `pinned` chips stay visible at zero so their place in the row never moves.
function renderChipRow(key, navId, order, allLabel, pinned = []) {
  const counts = {};
  for (const j of filtered({ ignore: key })) counts[j[key]] = (counts[j[key]] || 0) + 1;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const nav = $(navId);
  nav.replaceChildren();
  const chip = (value, label, n) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.setAttribute("aria-pressed", String(state[key] === value));
    b.disabled = n === 0 && state[key] !== value;
    b.append(label);
    const c = document.createElement("span");
    c.className = "n";
    c.textContent = n;
    b.append(c);
    b.addEventListener("click", () => {
      state[key] = state[key] === value ? "" : value;
      render();
    });
    nav.append(b);
  };
  chip("", allLabel, total);
  for (const name of order) {
    if (counts[name] || state[key] === name || pinned.includes(name)) chip(name, name, counts[name] || 0);
  }
}

function renderChips() {
  renderChipRow("role", "roles", state.data.roles, "All job types", state.data.pinned_roles || []);
  renderChipRow("industry", "industries", state.data.industries, "All industries");
}

function renderList(container, jobs, emptyText) {
  container.replaceChildren();
  if (!jobs.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.append(`${emptyText} `);
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = "Clear filters";
    b.addEventListener("click", clearFilters);
    p.append(b);
    container.append(p);
    return;
  }
  for (const name of state.data.industries) {
    const group = jobs.filter((j) => j.industry === name);
    if (!group.length) continue;
    const section = document.createElement("section");
    section.className = "industry-group";
    const h = document.createElement("h3");
    h.append(name);
    const n = document.createElement("span");
    n.className = "n";
    n.textContent = group.length;
    h.append(n);
    section.append(h, ...group.map(renderRow));
    container.append(section);
  }
}

function renderSegmentCounts() {
  const jobs = filtered({ ignore: "sponsorship" });
  const yes = jobs.filter((j) => j.sponsorship === "yes").length;
  $("seg-all").textContent = jobs.length;
  $("seg-yes").textContent = yes;
  $("seg-no").textContent = jobs.length - yes;
}

function render() {
  renderSegmentCounts();
  renderChips();
  const choice = sponsorshipFilter();
  $("sponsor-board").hidden = choice === "no";
  $("other-board").hidden = choice === "yes";
  // Picking "No sponsorship" means you want to see that list, so open it.
  if (choice === "no") $("other-board").open = true;
  const jobs = filtered();
  const sponsor = jobs.filter((j) => j.sponsorship === "yes");
  // Postings that say they sponsor go above ones inferred from H-1B history.
  sponsor.sort((a, b) => (b.basis === "posting") - (a.basis === "posting") || b.posted_at - a.posted_at);
  const other = jobs.filter((j) => j.sponsorship !== "yes");
  $("sponsor-stamp").textContent = sponsor.length;
  $("other-count").textContent = other.length;
  renderList($("sponsor-list"), sponsor, "No visa-sponsoring jobs match these filters.");
  renderList($("other-list"), other, "No other jobs match these filters.");
}

function clearFilters() {
  $("q").value = "";
  $("remote").checked = false;
  $("hideApplied").checked = false;
  document.querySelector('input[name="sponsorship"][value="all"]').checked = true;
  state.industry = "";
  state.role = "";
  render();
}

function setupThemeToggle() {
  const button = $("theme-toggle");
  const sync = () => {
    const dark = document.documentElement.dataset.theme === "dark";
    button.textContent = dark ? "Light mode" : "Dark mode";
  };
  button.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme !== "dark";
    if (dark) document.documentElement.dataset.theme = "dark";
    else delete document.documentElement.dataset.theme;
    store.set(THEME_KEY, dark ? "dark" : "light");
    sync();
  });
  sync();
}

// The side panel sticks just below the filter bar, whose height changes as it wraps.
function trackFilterBarHeight() {
  const bar = $("filters");
  const update = () => document.documentElement.style.setProperty("--filters-h", `${bar.offsetHeight}px`);
  new ResizeObserver(update).observe(bar);
  update();
}

async function main() {
  setupThemeToggle();
  trackFilterBarHeight();
  try {
    const res = await fetch("data/jobs.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.data = await res.json();
  } catch (err) {
    $("updated").textContent = "Couldn't load today's jobs. Run python scripts/fetch_jobs.py, then reload.";
    return;
  }
  $("updated").textContent = `Updated ${timeAgo(state.data.generated_at)}. New jobs arrive every morning.`;

  for (const id of ["q", "window", "remote", "hideApplied"]) {
    $(id).addEventListener(id === "q" ? "input" : "change", render);
  }
  for (const radio of document.querySelectorAll('input[name="sponsorship"]')) radio.addEventListener("change", render);
  const otherBoard = $("other-board");
  otherBoard.open = store.get(OTHER_OPEN_KEY, false);
  otherBoard.addEventListener("toggle", () => {
    if (sponsorshipFilter() !== "no") store.set(OTHER_OPEN_KEY, otherBoard.open);
  });

  render();
  document.querySelector(".stamp").classList.add("inked");
}

main();
