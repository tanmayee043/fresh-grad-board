"use strict";

const APPLIED_KEY = "fgb:applied"; // older format: a list of job ids
const APPLICATIONS_KEY = "fgb:applications";
const APPS_OPEN_KEY = "fgb:apps-open";
const HIDDEN_KEY = "fgb:hidden-companies";
const CHECKED_KEY = "fgb:sponsors-checked";
const SPONSORS_OPEN_KEY = "fgb:sponsors-open";
const SPONSOR_CATEGORIES = ["Big Tech", "Small Tech", "Universities", "Other"];
const SPONSOR_PAGE = 50;
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
  // Job id -> what you applied to and when. Details are saved with the mark so the
  // list survives after the job drops out of the daily feed.
  applications: store.get(APPLICATIONS_KEY, {}),
  hiddenCompanies: store.get(HIDDEN_KEY, []),
  sponsors: null,
  sponsorCategory: "all",
  sponsorShown: SPONSOR_PAGE,
  checked: store.get(CHECKED_KEY, {}),
};

// "Acme, Inc." and "acme inc" are the same company; legal suffixes don't count.
function companyKey(name) {
  return name.toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ")
    .replace(/^the /, "").replace(/( (inc|llc|ltd|corp|corporation|co|company|plc|lp))+ *$/, "").trim();
}

// A hidden name also covers longer names that start with it, so "Amazon" hides
// "Amazon Web Services", but whole words only: "Meta" leaves "Metabase" alone.
function isHiddenCompany(company) {
  const key = companyKey(company);
  return state.hiddenCompanies.some((name) => {
    const hidden = companyKey(name);
    return hidden && (key === hidden || key.startsWith(hidden + " "));
  });
}

function markApplied(job, on) {
  if (on) {
    state.applications[job.id] = {
      company: job.company, title: job.title, url: job.url, domain: job.domain,
      sponsorship: job.sponsorship, applied_at: Math.floor(Date.now() / 1000),
    };
  } else {
    delete state.applications[job.id];
  }
  store.set(APPLICATIONS_KEY, state.applications);
}

// Marks saved before the applications list existed only had ids; fill in what we can.
function migrateOldMarks() {
  const old = store.get(APPLIED_KEY, null);
  if (!Array.isArray(old)) return;
  const byId = new Map(state.data.jobs.map((j) => [j.id, j]));
  for (const id of old) {
    if (state.applications[id]) continue;
    const job = byId.get(id);
    state.applications[id] = job
      ? { company: job.company, title: job.title, url: job.url, domain: job.domain, sponsorship: job.sponsorship, applied_at: null }
      : { company: "", title: id.replace(/-/g, " "), url: "", domain: null, applied_at: null };
  }
  store.set(APPLICATIONS_KEY, state.applications);
  try { localStorage.removeItem(APPLIED_KEY); } catch { /* nothing to clean up */ }
}

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
  if (job.reposted) {
    const tag = document.createElement("span");
    tag.className = "repost-tag";
    const first = new Date(job.first_listed * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    tag.textContent = `Reposted, first listed ${first}`;
    node.querySelector(".company").append(" ", tag);
  }
  node.querySelector(".evidence").append(evidenceNode(job));
  const posted = node.querySelector(".posted");
  posted.dateTime = new Date(job.posted_at * 1000).toISOString();
  posted.textContent = `Posted ${timeAgo(job.posted_at)}`;
  const apply = node.querySelector(".apply");
  apply.href = job.url;
  apply.setAttribute("aria-label", `Apply to ${job.title} at ${job.company}`);

  const box = node.querySelector(".applied input");
  box.checked = Boolean(state.applications[job.id]);
  box.setAttribute("aria-label", `Mark ${job.title} at ${job.company} as applied`);
  node.classList.toggle("is-applied", box.checked);
  box.addEventListener("change", () => {
    markApplied(job, box.checked);
    node.classList.toggle("is-applied", box.checked);
    renderApplications();
    if ($("hideApplied").checked) render();
  });
  return node;
}

const sponsorshipFilter = () => document.querySelector('input[name="sponsorship"]:checked').value;
const postingFilter = () => document.querySelector('input[name="posting"]:checked').value;

function filtered({ ignore = "" } = {}) {
  const sponsorship = ignore === "sponsorship" ? "all" : sponsorshipFilter();
  const posting = ignore === "posting" ? "all" : postingFilter();
  const q = $("q").value.trim().toLowerCase();
  const since = Date.now() / 1000 - Number($("window").value) * 3600;
  return state.data.jobs.filter((j) =>
    j.posted_at >= since &&
    (sponsorship === "all" || (sponsorship === "yes") === (j.sponsorship === "yes")) &&
    (posting === "all" || (posting === "repost") === Boolean(j.reposted)) &&
    (ignore === "role" || !state.role || j.role === state.role) &&
    (!$("remote").checked || j.remote) &&
    (!$("hideApplied").checked || !state.applications[j.id]) &&
    (ignore === "hidden" || !isHiddenCompany(j.company)) &&
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
  const byPosting = filtered({ ignore: "posting" });
  const reposts = byPosting.filter((j) => j.reposted).length;
  $("post-all").textContent = byPosting.length;
  $("post-new").textContent = byPosting.length - reposts;
  $("post-repost").textContent = reposts;
}

function formatDay(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// Everything you've marked applied, newest first. Filters don't apply here.
function renderApplications() {
  const live = new Map(state.data.jobs.map((j) => [j.id, j]));
  const entries = Object.entries(state.applications)
    .sort(([, a], [, b]) => (b.applied_at || 0) - (a.applied_at || 0));
  $("apps-count").textContent = entries.length;
  const list = $("apps-list");
  list.replaceChildren();
  if (!entries.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "Nothing yet. Tick Applied on a job and it will be listed here, even after it leaves the board.";
    list.append(p);
    return;
  }
  const ol = document.createElement("ol");
  ol.className = "apps";
  for (const [id, app] of entries) {
    const li = document.createElement("li");
    li.className = "app";
    const logo = document.createElement("div");
    logo.className = "logo";
    logo.setAttribute("aria-hidden", "true");
    renderLogo(logo, { company: app.company || app.title, domain: app.domain });

    const main = document.createElement("div");
    main.className = "app-main";
    const title = document.createElement(app.url ? "a" : "span");
    title.className = "app-title";
    title.textContent = app.title;
    if (app.url) { title.href = app.url; title.target = "_blank"; title.rel = "noopener"; }
    const sub = document.createElement("p");
    sub.className = "app-sub";
    const bits = [];
    if (app.company) bits.push(app.company);
    bits.push(app.applied_at ? `Applied ${formatDay(app.applied_at)}` : "Applied");
    if (app.sponsorship === "yes") bits.push("Sponsors visas");
    sub.textContent = bits.join(" · ");
    const status = document.createElement("span");
    status.className = live.has(id) ? "app-status open" : "app-status";
    status.textContent = live.has(id) ? "On the board" : "Off the board";
    sub.append(" ", status);
    main.append(title, sub);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "app-remove";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${app.title}${app.company ? ` at ${app.company}` : ""} from your applications`);
    remove.addEventListener("click", () => {
      delete state.applications[id];
      store.set(APPLICATIONS_KEY, state.applications);
      render();
    });
    li.append(logo, main, remove);
    ol.append(li);
  }
  list.append(ol);
}

function renderHiddenCompanies() {
  const list = $("hidden-list");
  list.replaceChildren();
  for (const name of state.hiddenCompanies) {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "hidden-chip";
    b.setAttribute("aria-label", `Show ${name} again`);
    b.append(name);
    const x = document.createElement("span");
    x.setAttribute("aria-hidden", "true");
    x.textContent = "×";
    b.append(x);
    b.addEventListener("click", () => {
      state.hiddenCompanies = state.hiddenCompanies.filter((n) => n !== name);
      store.set(HIDDEN_KEY, state.hiddenCompanies);
      render();
    });
    li.append(b);
    list.append(li);
  }
  // Only jobs that the other filters would otherwise show.
  const count = filtered({ ignore: "hidden" }).length - filtered().length;
  $("hide-note").textContent = state.hiddenCompanies.length
    ? `${count} job${count === 1 ? "" : "s"} hidden. Tap a name to show it again.`
    : "Jobs from companies you add here won't show up.";
}

function setupHideForm() {
  const names = [...new Set(state.data.jobs.map((j) => j.company))].sort((a, b) => a.localeCompare(b));
  $("company-names").replaceChildren(...names.map((n) => Object.assign(document.createElement("option"), { value: n })));
  $("hide-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("hide-input");
    const typed = input.value.trim().replace(/\s+/g, " ");
    input.value = "";
    if (!companyKey(typed)) return;
    // Use the board's spelling when the typed name matches a company on it.
    const name = names.find((n) => companyKey(n) === companyKey(typed)) || typed;
    if (!state.hiddenCompanies.some((n) => companyKey(n) === companyKey(name))) {
      state.hiddenCompanies = [...state.hiddenCompanies, name];
      store.set(HIDDEN_KEY, state.hiddenCompanies);
    }
    render();
  });
}

function render() {
  renderApplications();
  renderHiddenCompanies();
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
  document.querySelector('input[name="posting"][value="all"]').checked = true;
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

// ---------------------------------------------------------------- sponsor list

function renderSponsorCategories() {
  const companies = state.sponsors.companies;
  const nav = $("sponsor-cats");
  nav.replaceChildren();
  const options = [["all", "All", companies.length],
    ...SPONSOR_CATEGORIES.map((c) => [c, c, companies.filter((x) => x.category === c).length])];
  for (const [value, label, n] of options) {
    const l = document.createElement("label");
    const input = Object.assign(document.createElement("input"),
      { type: "radio", name: "sponsor-cat", value, checked: state.sponsorCategory === value });
    input.addEventListener("change", () => {
      state.sponsorCategory = value;
      state.sponsorShown = SPONSOR_PAGE;
      renderSponsorList();
    });
    const span = document.createElement("span");
    const b = document.createElement("b");
    b.textContent = n;
    span.append(`${label} `, b);
    l.append(input, span);
    nav.append(l);
  }
}

function sponsorRow(c) {
  const li = document.createElement("li");
  li.className = "app sponsor-co";
  li.classList.toggle("is-checked", Boolean(state.checked[c.id]));

  const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: Boolean(state.checked[c.id]) });
  box.className = "co-check";
  box.setAttribute("aria-label", `Mark ${c.name} as checked`);
  box.addEventListener("change", () => {
    if (box.checked) state.checked[c.id] = Math.floor(Date.now() / 1000);
    else delete state.checked[c.id];
    store.set(CHECKED_KEY, state.checked);
    li.classList.toggle("is-checked", box.checked);
    renderCheckedCount();
    if ($("hide-checked").checked) renderSponsorList();
  });

  const logo = document.createElement("div");
  logo.className = "logo";
  logo.setAttribute("aria-hidden", "true");
  renderLogo(logo, { company: c.name, domain: c.domain });

  const main = document.createElement("div");
  main.className = "app-main";
  const name = document.createElement(c.careers ? "a" : "span");
  name.className = "app-title";
  name.textContent = c.name;
  if (c.careers) { name.href = c.careers; name.target = "_blank"; name.rel = "noopener"; }
  const sub = document.createElement("p");
  sub.className = "app-sub";
  const latest = c.postings[0];
  const many = c.count >= 20 ? "20+" : c.count;
  sub.append(`${c.industry} · ${many} ${c.count === 1 ? "posting this year says" : "postings this year say"} they sponsor · latest ${formatDay(c.last_posted)}: `);
  if (latest) {
    const a = Object.assign(document.createElement("a"), { href: latest.url, target: "_blank", rel: "noopener" });
    a.className = "co-latest";
    a.textContent = latest.title;
    sub.append(a);
  }
  main.append(name, sub);
  if (latest && latest.evidence) {
    const q = document.createElement("q");
    q.className = "co-quote";
    q.textContent = latest.evidence;
    main.append(q);
  }

  const go = document.createElement(c.careers ? "a" : "span");
  go.className = "apply co-careers";
  go.textContent = "Careers page";
  if (c.careers) {
    go.href = c.careers; go.target = "_blank"; go.rel = "noopener";
    go.setAttribute("aria-label", `${c.name} careers page`);
  }
  li.append(box, logo, main, go);
  return li;
}

function renderCheckedCount() {
  const ids = new Set(state.sponsors.companies.map((c) => c.id));
  const n = Object.keys(state.checked).filter((id) => ids.has(id)).length;
  $("checked-count").textContent = n ? `${n} checked` : "";
}

function renderSponsorList() {
  const q = $("sponsor-q").value.trim().toLowerCase();
  const hideChecked = $("hide-checked").checked;
  const list = state.sponsors.companies.filter((c) =>
    (state.sponsorCategory === "all" || c.category === state.sponsorCategory) &&
    (!hideChecked || !state.checked[c.id]) &&
    (!q || `${c.name} ${c.industry}`.toLowerCase().includes(q)));
  const dir = $("sponsor-dir");
  dir.replaceChildren();
  renderCheckedCount();
  if (!list.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = state.sponsorCategory === "Universities" && !q
      ? "No university postings this year have said they sponsor yet. They will show up here as they are found."
      : "No companies match.";
    dir.append(p);
    return;
  }
  const ol = document.createElement("ol");
  ol.className = "apps";
  ol.append(...list.slice(0, state.sponsorShown).map(sponsorRow));
  dir.append(ol);
  if (list.length > state.sponsorShown) {
    const more = document.createElement("button");
    more.type = "button";
    more.className = "show-more";
    more.textContent = `Show more (${list.length - state.sponsorShown} left)`;
    more.addEventListener("click", () => { state.sponsorShown += SPONSOR_PAGE; renderSponsorList(); });
    dir.append(more);
  }
}

async function loadSponsors() {
  const board = $("sponsors-board");
  board.open = store.get(SPONSORS_OPEN_KEY, false);
  board.addEventListener("toggle", () => store.set(SPONSORS_OPEN_KEY, board.open));
  $("sponsors-link").addEventListener("click", () => { board.open = true; });
  try {
    const res = await fetch("data/sponsors.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.sponsors = await res.json();
  } catch {
    $("sponsor-dir").replaceChildren(Object.assign(document.createElement("p"),
      { className: "empty", textContent: "The sponsor list is not available yet. It is built with each daily update." }));
    return;
  }
  $("sponsors-title").textContent = `Visa sponsors in ${state.sponsors.year}`;
  $("sponsors-count").textContent = state.sponsors.companies.length;
  $("sponsor-q").addEventListener("input", () => { state.sponsorShown = SPONSOR_PAGE; renderSponsorList(); });
  $("hide-checked").addEventListener("change", renderSponsorList);
  renderSponsorCategories();
  renderSponsorList();
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
  migrateOldMarks();
  setupHideForm();
  $("updated").textContent = `Updated ${timeAgo(state.data.generated_at)}. New jobs arrive every morning.`;

  for (const id of ["q", "window", "remote", "hideApplied"]) {
    $(id).addEventListener(id === "q" ? "input" : "change", render);
  }
  for (const radio of document.querySelectorAll('input[name="sponsorship"], input[name="posting"]')) {
    radio.addEventListener("change", render);
  }
  const appsBoard = $("apps-board");
  appsBoard.open = store.get(APPS_OPEN_KEY, false);
  appsBoard.addEventListener("toggle", () => store.set(APPS_OPEN_KEY, appsBoard.open));
  $("apps-link").addEventListener("click", () => { appsBoard.open = true; });

  const otherBoard = $("other-board");
  otherBoard.open = store.get(OTHER_OPEN_KEY, false);
  otherBoard.addEventListener("toggle", () => {
    if (sponsorshipFilter() !== "no") store.set(OTHER_OPEN_KEY, otherBoard.open);
  });

  render();
  document.querySelector(".stamp").classList.add("inked");
  loadSponsors();
}

main();
