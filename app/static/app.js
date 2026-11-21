const $ = (id) => document.getElementById(id);

const BUSY = ["processing", "packing", "unpacking", "deleting"];
const TABS = [
  { id: "search" },
  { id: "history" },
  { id: "profile" },
  { id: "files", admin: true },
  { id: "requests", admin: true },
  { id: "invites", admin: true },
  { id: "users", admin: true },
  { id: "stats", admin: true },
  { id: "missed", admin: true },
  { id: "backups", admin: true },
  { id: "audit", admin: true },
];

let me = null;
let tab = "search";
let timer = null;
let toastTimer = null;
let current = null;
let auditBefore = null;
let editing = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(label, className, handler) {
  const node = el("button", className, label);
  node.type = "button";
  node.addEventListener("click", handler);
  return node;
}

function locale() {
  return LANG === "uk" ? "uk-UA" : "en-GB";
}

function date(value) {
  return value ? new Date(value).toLocaleString(locale(), { dateStyle: "short", timeStyle: "short" }) : "";
}

function size(bytes) {
  const units = LANG === "uk" ? ["Б", "КБ", "МБ", "ГБ", "ТБ"] : ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let value = Number(bytes) || 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function toast(text) {
  let node = $("toast");
  if (!node) {
    node = el("div", "toast");
    node.id = "toast";
    document.body.append(node);
  }
  node.textContent = text;
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 3500);
}

async function api(url, options = {}) {
  const init = { method: options.method || "GET", headers: {}, credentials: "same-origin" };
  if (options.json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.json);
  }
  if (options.form) init.body = options.form;
  const res = await fetch(url, init);
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (res.status === 401 && me && !url.startsWith("/api/auth/")) {
    me = null;
    showAuth();
  }
  return { ok: res.ok, status: res.status, data };
}

function detail(res) {
  const d = res.data && res.data.detail;
  if (typeof d === "string") return errorText(d);
  return d ? t("err_check") : t("err_generic");
}

async function act(url, options, done) {
  const res = await api(url, options);
  if (!res.ok) {
    toast(detail(res));
    return null;
  }
  if (done) done(res.data);
  return res.data;
}

function showAuth() {
  clearInterval(timer);
  $("app").hidden = true;
  $("me").hidden = true;
  $("auth").hidden = false;
}

function renderNav() {
  const nav = $("nav");
  const tabs = TABS.filter((x) => !x.admin || me.role === "admin");
  const nodes = [];
  let divider = false;
  for (const item of tabs) {
    if (item.admin && !divider) {
      nodes.push(el("span", "nav-gap"));
      divider = true;
    }
    const b = button(t(`tab_${item.id}`), `tab${item.id === tab ? " active" : ""}`, () => switchTab(item.id));
    b.dataset.tab = item.id;
    nodes.push(b);
  }
  nav.replaceChildren(...nodes);
  nav.hidden = tabs.length < 2;
}

function showApp() {
  $("auth").hidden = true;
  $("app").hidden = false;
  $("me").hidden = false;
  $("hidden-box").hidden = me.role !== "admin";
  tab = "search";
  renderMe();
  renderNav();
  switchTab("search");
}

function roleName(role) {
  return t(`role_${role}`);
}

function renderMe() {
  $("me-name").textContent = me.username;
  const badge = $("me-role");
  badge.textContent = roleName(me.role);
  badge.className = `badge ${me.role}`;
  badge.title = me.role_until ? t("until", { date: date(me.role_until) }) : "";
  $("me-rank").textContent = rankLine(me.rank);
  renderQuota(me.quota);
}

function rankLine(rank) {
  let text = t("rank_line", { title: t(`rank_${rank.title}`), total: rank.total });
  if (rank.next_at) {
    text += t("rank_next", { next: t(`rank_${rank.next_title}`), left: rank.next_at - rank.total });
  }
  return text;
}

function renderQuota(quota) {
  const text = $("quota-text");
  const fill = $("quota-fill");
  fill.className = "bar-fill";
  if (quota.limit === null) {
    text.textContent = t("quota_unlimited");
    fill.style.width = "100%";
    return;
  }
  text.textContent = t("quota_used", { used: quota.used, limit: quota.limit });
  const ratio = quota.limit ? quota.used / quota.limit : 1;
  fill.style.width = `${Math.min(100, Math.round(ratio * 100))}%`;
  if (quota.remaining === 0) fill.classList.add("full");
  else if (ratio >= 0.8) fill.classList.add("warn");
}

async function refreshMe() {
  const res = await api("/api/auth/me");
  if (!res.ok) return;
  const before = me && me.rank.title;
  me = res.data;
  renderMe();
  if (before && before !== me.rank.title) toast(t("rank_new", { title: t(`rank_${me.rank.title}`) }));
}

function switchTab(id) {
  tab = id;
  clearInterval(timer);
  document.querySelectorAll("section[data-tab]").forEach((node) => {
    node.hidden = node.dataset.tab !== id;
  });
  document.querySelectorAll("#nav .tab").forEach((node) => {
    node.classList.toggle("active", node.dataset.tab === id);
  });
  const loaders = {
    files: [loadFiles, 1500],
    requests: [loadRequests, 5000],
    invites: [loadInvites, 0],
    users: [loadUsers, 0],
    audit: [() => loadAudit(true), 0],
    stats: [loadStats, 0],
    missed: [loadMissed, 0],
    backups: [loadBackups, 3000],
    history: [loadHistory, 0],
    profile: [renderProfile, 0],
    search: [loadSources, 0],
  };
  if (id === "files") loadAutopack();
  const entry = loaders[id];
  if (!entry) return;
  entry[0]();
  if (entry[1]) timer = setInterval(entry[0], entry[1]);
}

function escapeRe(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlight(text, list) {
  const frag = document.createDocumentFragment();
  const marks = [...new Set((list || []).filter(Boolean))].sort((a, b) => b.length - a.length);
  if (!marks.length) {
    frag.append(text);
    return frag;
  }
  const re = new RegExp(`(${marks.map(escapeRe).join("|")})`, "giu");
  text.split(re).forEach((part, i) => {
    if (i % 2) frag.append(el("mark", "", part));
    else if (part) frag.append(part);
  });
  return frag;
}

function hiddenCols() {
  try {
    return new Set(JSON.parse(localStorage.getItem("hiddenCols") || "[]"));
  } catch {
    return new Set();
  }
}

function saveHiddenCols(set) {
  try {
    localStorage.setItem("hiddenCols", JSON.stringify([...set]));
  } catch {
    return;
  }
}

function groupKeys(groups) {
  const keys = [];
  for (const g of groups) {
    for (const r of g.records) {
      for (const key of Object.keys(r.data)) if (!keys.includes(key)) keys.push(key);
    }
  }
  return keys;
}

function mergeFields(records) {
  const map = new Map();
  records.forEach((rec, i) => {
    for (const [k, v] of Object.entries(rec.data)) {
      if (v === null || v === "") continue;
      const text = String(v);
      if (!map.has(k)) map.set(k, new Map());
      const values = map.get(k);
      const norm = text.trim().toLowerCase();
      if (!values.has(norm)) values.set(norm, { text, srcs: [] });
      values.get(norm).srcs.push(i);
    }
  });
  return map;
}

function sourceTags(srcs) {
  const wrap = el("span", "srcs");
  srcs.forEach((i) => wrap.append(el("sup", "src", String(i + 1))));
  return wrap;
}

function fieldRows(records, marks, hide, tagged) {
  const rows = [];
  for (const [key, values] of mergeFields(records)) {
    if (hide && hide.has(key)) continue;
    const row = el("div", "row");
    row.append(el("b", "", `${key}: `));
    [...values.values()].forEach((v, i) => {
      if (i) row.append(" · ");
      row.append(highlight(v.text, marks));
      if (tagged) row.append(sourceTags(v.srcs));
    });
    rows.push(row);
  }
  return rows;
}

function cardTitle(record) {
  for (const v of Object.values(record.data)) {
    const text = v === null ? "" : String(v).trim();
    if (text && text.length <= 80) return text;
  }
  return "";
}

function findGroupOf(rec) {
  return current && current.items.find((g) => g.records.includes(rec));
}

function afterRecordChange(group, rec, removed) {
  if (removed) {
    group.records = group.records.filter((r) => r !== rec);
    group.own_ids = group.own_ids.filter((id) => id !== rec.id);
    if (!group.records.length) {
      current.items = current.items.filter((g) => g !== group);
    } else if (group.id === rec.id) {
      group.id = group.records[0].id;
      group.file_id = group.records[0].file_id;
      group.data = group.records[0].data;
    }
  } else if (group.id === rec.id) {
    group.data = rec.data;
  }
  refreshTools();
  drawResults();
}

function recordActions(rec) {
  const bar = el("div", "rec-actions");
  if (!me || me.role !== "admin") return bar;
  if (typeof rec.id !== "number") {
    bar.append(el("span", "muted-inline", t("packed_note")));
    return bar;
  }
  const group = () => findGroupOf(rec);
  const hiddenMode = current && current.hidden;
  bar.append(
    button(t("edit"), "mini", () => openEdit(rec, group)),
    button(hiddenMode ? t("unhide") : t("hide"), "mini", () =>
      act(`/api/admin/records/${rec.id}/hide`, { method: "POST", json: { hidden: !hiddenMode } }, () => {
        toast(t(hiddenMode ? "record_unhidden" : "record_hidden"));
        const g = group();
        if (g) afterRecordChange(g, rec, true);
      })
    ),
    button(t("delete"), "mini danger", () => {
      if (!confirm(t("delete_record_q"))) return;
      act(`/api/admin/records/${rec.id}`, { method: "DELETE" }, () => {
        toast(t("record_deleted"));
        const g = group();
        if (g) afterRecordChange(g, rec, true);
      });
    })
  );
  return bar;
}

function recordPanel(rec, index, marks, hide) {
  const box = el("div", "rec");
  const head = el("div", "rec-head");
  head.append(el("span", "src-num", String(index + 1)), el("span", "rec-file", rec.file || t("from_file")));
  box.append(head);
  for (const [k, v] of Object.entries(rec.data)) {
    if (v === null || v === "" || (hide && hide.has(k))) continue;
    const row = el("div", "row");
    row.append(el("b", "", `${k}: `), highlight(String(v), marks));
    box.append(row);
  }
  box.append(recordActions(rec));
  return box;
}

function renderGroup(group, marks, hide, label) {
  const card = el("article", "card");
  const records = group.records;
  const head = el("div", "card-head");
  const title = label || cardTitle(records[0]);
  head.append(el("div", "card-title", title));
  const badges = el("div", "card-badges");
  if (current && current.hidden) badges.append(el("span", "badge muted", t("hidden_mark")));
  if (records.length > 1) badges.append(el("span", "badge vip", t("sources_n", { n: records.length })));
  head.append(badges);
  card.append(head);
  const body = el("div", "card-body");
  body.append(...fieldRows(records, marks, hide, records.length > 1));
  card.append(body);
  if (records.length === 1) {
    const foot = el("div", "card-foot");
    if (records[0].file) foot.append(el("span", "chip", records[0].file));
    foot.append(recordActions(records[0]));
    card.append(foot);
    return card;
  }
  const chips = el("div", "card-foot");
  records.forEach((rec, i) => {
    const chip = el("span", "chip");
    chip.append(el("span", "src-num", String(i + 1)), rec.file || "");
    chips.append(chip);
  });
  card.append(chips);
  const details = el("div", "details");
  details.hidden = true;
  records.forEach((rec, i) => details.append(recordPanel(rec, i, marks, hide)));
  const toggle = button(t("details"), "link toggle", () => {
    details.hidden = !details.hidden;
    toggle.textContent = t(details.hidden ? "details" : "hide_details");
  });
  card.append(toggle, details);
  return card;
}

function sortedItems() {
  const items = [...current.items];
  const [field, dir] = $("sort").value.split(":");
  if (!field) return items;
  const sign = dir === "desc" ? -1 : 1;
  const value = (g) => String(g.data[field] ?? "");
  return items.sort((x, y) => sign * value(x).localeCompare(value(y), locale(), { numeric: true }));
}

function refreshTools() {
  const keys = groupKeys(current.items);
  const sort = $("sort");
  const chosen = sort.value;
  sort.replaceChildren(new Option(t("as_found"), ""));
  for (const key of keys) {
    sort.append(
      new Option(t("sort_asc", { k: key }), `${key}:asc`),
      new Option(t("sort_desc", { k: key }), `${key}:desc`)
    );
  }
  sort.value = [...sort.options].some((o) => o.value === chosen) ? chosen : "";
  const hidden = hiddenCols();
  $("cols-list").replaceChildren(
    ...keys.map((key) => {
      const label = el("label", "check");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = !hidden.has(key);
      box.addEventListener("change", () => {
        const set = hiddenCols();
        if (box.checked) set.delete(key);
        else set.add(key);
        saveHiddenCols(set);
        drawResults();
      });
      label.append(box, ` ${key}`);
      return label;
    })
  );
}

function drawResults() {
  const items = sortedItems();
  const hide = hiddenCols();
  $("results").replaceChildren(
    ...(items.length ? items.map((g) => renderGroup(g, current.marks, hide)) : [el("p", "empty", t("empty"))])
  );
  $("more").hidden = !current.more;
  $("result-tools").hidden = !items.length;
  $("result-count").textContent = t("found_count", { n: items.length });
  $("export").hidden = current.hidden;
}

function showMessage(node) {
  current = null;
  $("results").replaceChildren(node);
  $("more").hidden = true;
  $("result-tools").hidden = true;
}

async function loadSources() {
  const res = await api("/api/sources");
  if (!res.ok) return;
  const select = $("scope");
  const value = select.value;
  select.replaceChildren(new Option(t("all_files"), ""));
  res.data.forEach((f) => select.append(new Option(f.name, String(f.id))));
  select.value = [...select.options].some((o) => o.value === value) ? value : "";
}

async function runSearch(url, render) {
  const res = await api(url);
  if (!res.ok) {
    showMessage(el("p", "empty", detail(res)));
    if (res.status === 429) refreshMe();
    return false;
  }
  render(res.data);
  if (res.data.quota) renderQuota(res.data.quota);
  refreshMe();
  return true;
}

function searchUrl(state) {
  const params = new URLSearchParams({ q: state.q, offset: String(state.offset) });
  if (state.files) params.set("files", state.files);
  if (state.hidden) params.set("hidden", "true");
  if (state.searchId && state.offset) params.set("search_id", String(state.searchId));
  return `/api/search?${params}`;
}

function takeFresh(data) {
  const fresh = data.items.filter((g) => !g.own_ids.every((id) => current.seen.has(id)));
  for (const g of data.items) {
    for (const id of g.own_ids) current.seen.add(id);
    for (const r of g.records) current.seen.add(r.id);
  }
  return fresh;
}

async function startSearch(q, files) {
  const hidden = me.role === "admin" && $("show-hidden").checked;
  const next = { q, files, hidden, offset: 0, searchId: null, marks: [], items: [], more: false, seen: new Set() };
  await runSearch(searchUrl(next), (data) => {
    current = next;
    current.searchId = data.search_id;
    current.marks = data.marks || [];
    current.offset = data.raw;
    current.items = takeFresh(data);
    current.more = data.more;
    refreshTools();
    drawResults();
  });
}

$("more").addEventListener("click", async () => {
  if (!current) return;
  await runSearch(searchUrl(current), (data) => {
    current.items = current.items.concat(takeFresh(data));
    current.offset += data.raw;
    current.marks = data.marks || current.marks;
    current.more = data.more;
    refreshTools();
    drawResults();
  });
});

$("sort").addEventListener("change", () => current && drawResults());

$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("query").value.trim();
  if (!q) return;
  startSearch(q, $("scope").value);
});

$("lucky").addEventListener("click", () => {
  runSearch("/api/lucky", ({ item }) => {
    current = { q: "", files: "", hidden: false, items: [], marks: [], more: false, offset: 0, seen: new Set() };
    const group = {
      id: item.id,
      file_id: item.file_id,
      data: item.data,
      own_ids: [item.id],
      records: [{ id: item.id, file_id: item.file_id, file: "", data: item.data, own: true }],
    };
    current.items = [group];
    $("results").replaceChildren(renderGroup(group, [], hiddenCols(), t("random_record")));
    $("more").hidden = true;
    $("result-tools").hidden = true;
  });
});

async function download(url, name) {
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) {
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    toast(data && typeof data.detail === "string" ? errorText(data.detail) : t("err_generic"));
    return;
  }
  saveBlob(await res.blob(), name);
  refreshMe();
}

function saveBlob(blob, name) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

$("export").addEventListener("click", () => {
  if (!current || !current.q) return;
  const params = new URLSearchParams({ q: current.q });
  if (current.files) params.set("files", current.files);
  if (current.searchId) params.set("search_id", String(current.searchId));
  download(`/api/export?${params}`, "search.csv");
});

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

let bulkRows = [];

$("bulk-toggle").addEventListener("click", () => {
  $("bulk").hidden = !$("bulk").hidden;
});

function bulkData(r) {
  return r.item ? r.item.data || r.item : {};
}

$("bulk-run").addEventListener("click", async () => {
  const values = $("bulk-text").value.split("\n").map((v) => v.trim()).filter(Boolean);
  if (!values.length) return;
  const res = await api("/api/search/bulk", {
    method: "POST",
    json: { values, files: $("scope").value || null },
  });
  if (!res.ok) {
    toast(detail(res));
    if (res.status === 429) refreshMe();
    return;
  }
  bulkRows = res.data.results;
  renderQuota(res.data.quota);
  refreshMe();
  $("bulk-summary").textContent = t("bulk_summary", { found: res.data.found, total: bulkRows.length });
  $("bulk-csv").hidden = false;
  $("bulk-result").replaceChildren(
    ...bulkRows.map((r) => {
      const li = el("li", "item");
      const info = el("div", "item-info");
      info.append(el("div", "item-title", r.value));
      if (r.item) {
        const line = Object.values(bulkData(r)).filter((v) => v).join(" · ");
        info.append(el("div", "item-sub detail", line));
      }
      const side = el("div", "item-side");
      side.append(el("span", `badge ${r.found ? "vip" : "muted"}`, t(r.found ? "found" : "not_found")));
      li.append(info, side);
      return li;
    })
  );
});

$("bulk-csv").addEventListener("click", () => {
  const keys = [];
  for (const r of bulkRows) for (const k of Object.keys(bulkData(r))) if (!keys.includes(k)) keys.push(k);
  const lines = [["value", "found", ...keys].map(csvCell).join(",")];
  for (const r of bulkRows) {
    const data = bulkData(r);
    lines.push([r.value, r.found ? "yes" : "no", ...keys.map((k) => data[k] ?? "")].map(csvCell).join(","));
  }
  saveBlob(new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" }), "bulk.csv");
});

function fillEditRow(key, value) {
  const row = el("div", "edit-row");
  const k = el("input");
  k.value = key;
  k.placeholder = t("edit_key");
  k.maxLength = 100;
  const v = el("input");
  v.value = value;
  v.placeholder = t("edit_value");
  row.append(k, v);
  $("edit-fields").append(row);
  return row;
}

function openEdit(rec, group) {
  editing = { rec, group };
  $("edit-fields").replaceChildren();
  for (const [key, value] of Object.entries(rec.data)) fillEditRow(key, value === null ? "" : String(value));
  $("edit-dialog").showModal();
}

$("edit-add").addEventListener("click", () => fillEditRow("", "").firstChild.focus());

$("edit-cancel").addEventListener("click", () => $("edit-dialog").close());

$("edit-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!editing) return;
  const data = {};
  $("edit-fields").querySelectorAll(".edit-row").forEach((row) => {
    const [k, v] = row.querySelectorAll("input");
    const key = k.value.trim();
    if (key) data[key] = v.value;
  });
  const { rec, group } = editing;
  const ok = await act(`/api/admin/records/${rec.id}`, { method: "PATCH", json: { data } });
  if (!ok) return;
  rec.data = data;
  $("edit-dialog").close();
  toast(t("record_saved"));
  const g = group();
  if (g) afterRecordChange(g, rec, false);
});

async function loadHistory() {
  const res = await api("/api/history");
  if (!res.ok) return;
  if (!res.data.length) {
    $("history").replaceChildren(el("li", "empty", t("history_empty")));
    return;
  }
  $("history").replaceChildren(
    ...res.data.map((h) => {
      const li = el("li", "item");
      const info = el("div", "item-info");
      const sub = [date(h.at), t("history_found", { n: h.results })];
      if (h.source === "bot") sub.push(t("history_bot"));
      if (h.files) sub.push(t("history_filter"));
      info.append(el("div", "item-title", h.query), el("div", "item-sub", sub.join(" · ")));
      const side = el("div", "item-side");
      side.append(
        button(t("repeat"), "mini", () => {
          $("query").value = h.query;
          $("scope").value = h.files.includes(",") ? "" : h.files;
          switchTab("search");
          startSearch(h.query, $("scope").value);
        })
      );
      li.append(info, side);
      return li;
    })
  );
}

$("history-clear").addEventListener("click", () => {
  if (confirm(t("history_clear_q"))) act("/api/history", { method: "DELETE" }, loadHistory);
});

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast(t("copied"));
  } catch {
    toast(text);
  }
}

function renderProfile() {
  const box = $("tg-box");
  box.replaceChildren();
  if (me.tg_linked) {
    box.append(
      el("p", "muted", t("tg_linked")),
      button(t("tg_unlink"), "mini danger", () =>
        act("/api/auth/tg", { method: "DELETE" }, async () => {
          await refreshMe();
          renderProfile();
        })
      )
    );
    return;
  }
  box.append(
    el("p", "muted", t("tg_hint")),
    button(t("tg_get_code"), "mini", () =>
      act("/api/auth/tg-code", { method: "POST" }, (d) => {
        const code = el("div", "token-box");
        code.append(
          el("span", "token mono", d.code),
          el("span", "muted-inline", t("tg_valid", { n: d.minutes })),
          button(t("copy"), "mini", () => copy(d.code))
        );
        box.append(code);
      })
    )
  );
}

$("password-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const json = { current: $("pw-current").value, new: $("pw-new").value };
  const ok = await act("/api/auth/password", { method: "POST", json });
  if (ok) {
    $("pw-current").value = "";
    $("pw-new").value = "";
    toast(t("pw_changed"));
  }
});

function renderFile(f) {
  const li = el("li", `file ${f.status}`);
  const busy = BUSY.includes(f.status);
  let meta = t(`status_${f.status}`);
  if (busy && f.progress > 0) meta = `${meta} ${f.progress}%`;
  if (f.status === "done") {
    meta = t("file_rows", { n: f.rows_count });
    if (f.packed && f.packed_bytes > 0) {
      meta += ", " + t("file_packed_size", {
        raw: size(f.raw_bytes),
        packed: size(f.packed_bytes),
        ratio: (f.raw_bytes / f.packed_bytes).toFixed(1),
      });
    } else if (f.packed) {
      meta += ", " + t("file_packed");
    }
  }
  const head = el("div", "file-head");
  head.append(el("span", "file-name", f.name), el("span", "file-meta", meta));
  const fill = el("div", "bar-fill");
  if (busy && f.progress === 0) {
    fill.classList.add("indeterminate");
    fill.style.animationDelay = `-${Date.now() % 2200}ms`;
  }
  else fill.style.width = f.status === "done" ? "100%" : `${f.progress}%`;
  const bar = el("div", "bar");
  bar.append(fill);
  li.append(head, bar);

  if (f.status === "done" || f.status === "failed") {
    const actions = el("div", "toolbar actions");
    if (f.status === "done") {
      const kind = f.packed ? "unpack" : "pack";
      actions.append(
        button(t(kind), "link", () => act(`/api/compress/files/${f.id}/${kind}`, { method: "POST" }, loadFiles))
      );
    } else {
      actions.append(
        button(t("retry"), "link", () => act(`/api/files/${f.id}/retry`, { method: "POST" }, loadFiles))
      );
    }
    actions.append(
      button(t("delete"), "link", () => {
        if (!confirm(t("delete_file_q", { name: f.name }))) return;
        act(`/api/files/${f.id}`, { method: "DELETE" }, loadFiles);
      })
    );
    li.append(actions);
  }
  if (f.error) li.append(el("div", "file-error", errorText(f.error)));
  return li;
}

async function loadFiles() {
  const res = await api("/api/files");
  if (!res.ok) return;
  $("files").replaceChildren(...res.data.map(renderFile));
  const stats = await api("/api/compress/stats");
  if (!stats.ok) return;
  const s = stats.data;
  if (!s.files) {
    $("stats").textContent = "";
    return;
  }
  let text = t("files_stats", { files: s.files, packed: s.packed_files });
  if (s.packed_files && s.packed_bytes > 0) {
    text += t("files_stats_size", { raw: size(s.raw_bytes), packed: size(s.packed_bytes) });
  }
  text += t("files_disk", { records: size(s.records_size), blocks: size(s.blocks_size) });
  $("stats").textContent = text;
}

async function loadAutopack() {
  const res = await api("/api/admin/settings");
  if (!res.ok) return;
  const a = res.data.autopack;
  $("ap-enabled").checked = a.enabled;
  $("ap-days").value = String(a.days);
  $("ap-method").value = a.method;
}

$("autopack-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const json = {
    enabled: $("ap-enabled").checked,
    days: Number($("ap-days").value),
    method: $("ap-method").value,
  };
  act("/api/admin/settings", { method: "PUT", json }, () => toast(t("saved")));
});

$("vocab-rebuild").addEventListener("click", () => {
  act("/api/admin/vocab/rebuild", { method: "POST" }, () => toast(t("vocab_started")));
});

$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("file");
  const list = [...input.files];
  let done = 0;
  const failed = [];
  for (const file of list) {
    const form = new FormData();
    form.append("file", file);
    const res = await api("/api/files", { method: "POST", form });
    if (res.ok) done += 1;
    else failed.push(`${file.name}: ${detail(res)}`);
    loadFiles();
  }
  input.value = "";
  const more = failed.length > 1 ? ` (+${failed.length - 1})` : "";
  toast(failed.length ? `${failed[0]}${more}` : t("upload_done", { ok: done, total: list.length }));
});

$("merge-all").addEventListener("click", () => {
  if (!confirm(t("merge_q"))) return;
  act("/api/compress/merge", { method: "POST", json: {} }, loadFiles);
});

$("reclaim").addEventListener("click", () => {
  act("/api/compress/reclaim", { method: "POST" }, () => toast(t("reclaim_started")));
});

function days(value) {
  return value ? Number(value) : null;
}

function term(role, n) {
  return role === "vip" && n ? t("days_short", { n }) : "";
}

function who(r) {
  return r.tg_username ? `@${r.tg_username}` : `tg ${r.tg_id}`;
}

async function loadRequests() {
  const res = await api("/api/admin/requests");
  if (!res.ok) return;
  const list = res.data;
  if (!list.length) {
    $("requests").replaceChildren(el("li", "empty", t("requests_empty")));
    return;
  }
  $("requests").replaceChildren(
    ...list.map((r) => {
      const li = el("li", "item");
      const info = el("div", "item-info");
      info.append(el("div", "item-title", who(r)));
      info.append(el("div", "item-sub", [r.message, date(r.created_at)].filter(Boolean).join(" · ")));
      const side = el("div", "item-side");
      if (r.status === "pending") {
        const decide = (role) =>
          act(
            `/api/admin/requests/${r.id}/approve`,
            { method: "POST", json: { role, days: role === "vip" ? days($("req-days").value) : null } },
            () => {
              toast(t("approved_toast"));
              loadRequests();
            }
          );
        side.append(
          button(t("approve_user"), "mini", () => decide("user")),
          button(t("approve_vip"), "mini", () => decide("vip")),
          button(t("reject"), "mini danger", () =>
            act(`/api/admin/requests/${r.id}/reject`, { method: "POST" }, loadRequests)
          )
        );
      } else {
        side.append(el("span", `state ${r.status}`, t(r.status === "approved" ? "request_approved" : "request_rejected")));
      }
      li.append(info, side);
      return li;
    })
  );
}

function inviteState(i) {
  if (i.used_at) return { text: `${t("token_used")}${i.used_by_name ? `: ${i.used_by_name}` : ""}`, cls: "approved" };
  if (new Date(i.expires_at) < new Date()) return { text: t("token_expired"), cls: "rejected" };
  return { text: t("token_active", { date: date(i.expires_at) }), cls: "pending" };
}

async function loadInvites() {
  const res = await api("/api/admin/invites");
  if (!res.ok) return;
  const list = res.data;
  if (!list.length) {
    $("invites").replaceChildren(el("li", "empty", t("tokens_empty")));
    return;
  }
  $("invites").replaceChildren(
    ...list.map((i) => {
      const state = inviteState(i);
      const li = el("li", "item");
      const info = el("div", "item-info");
      const title = el("div", "item-title mono", i.token);
      title.append(" ", el("span", `badge ${i.role}`, roleName(i.role) + term(i.role, i.role_days)));
      info.append(title, el("div", "item-sub", [i.note, date(i.created_at)].filter(Boolean).join(" · ")));
      const side = el("div", "item-side");
      side.append(el("span", `state ${state.cls}`, state.text));
      if (!i.used_at) {
        side.append(
          button(t("copy"), "mini", () => copy(i.token)),
          button(t("delete"), "mini danger", () =>
            act(`/api/admin/invites/${i.id}`, { method: "DELETE" }, loadInvites)
          )
        );
      }
      li.append(info, side);
      return li;
    })
  );
}

$("invite-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const role = $("invite-role").value;
  const json = {
    role,
    note: $("invite-note").value,
    days: role === "vip" ? days($("invite-days").value) : null,
  };
  const data = await act("/api/admin/invites", { method: "POST", json });
  if (!data) return;
  $("invite-note").value = "";
  const box = $("new-token");
  box.hidden = false;
  box.replaceChildren(
    el("span", "token mono", data.token),
    el("span", "badge " + data.role, roleName(data.role) + term(data.role, data.role_days)),
    button(t("copy"), "mini", () => copy(data.token))
  );
  loadInvites();
});

async function loadUsers() {
  const res = await api("/api/admin/users");
  if (!res.ok) return;
  $("users").replaceChildren(
    ...res.data.map((u) => {
      const own = me && u.id === me.id;
      const li = el("li", "item");
      const info = el("div", "item-info");
      const sub = [];
      if (u.blocked) sub.push(t("blocked"));
      sub.push(t("user_sub", { used: u.used, total: u.total }));
      if (u.role_until) sub.push(t("until", { date: date(u.role_until) }));
      if (u.tg_id) sub.push(t("tg_bound"));
      sub.push(date(u.created_at));
      info.append(
        el("div", "item-title", own ? `${u.username} (${t("you")})` : u.username),
        el("div", "item-sub", sub.join(" · "))
      );
      const side = el("div", "item-side");
      const select = el("select");
      for (const value of ["user", "vip", "admin"]) {
        const option = el("option", "", roleName(value));
        option.value = value;
        option.selected = value === u.role;
        select.append(option);
      }
      select.disabled = own;
      select.addEventListener("change", async () => {
        let n = null;
        if (select.value === "vip") {
          const answer = prompt(t("vip_days_q"), "30");
          if (answer === null) {
            loadUsers();
            return;
          }
          n = days(answer.trim());
          if (answer.trim() && !n) {
            toast(t("days_number"));
            loadUsers();
            return;
          }
        }
        const ok = await act(`/api/admin/users/${u.id}`, {
          method: "PATCH",
          json: { role: select.value, days: n },
        });
        if (ok) toast(t("role_changed"));
        loadUsers();
      });
      side.append(select);
      side.append(
        button(t("password_btn"), "mini", async () => {
          const answer = prompt(t("new_password_q"), "");
          if (answer === null) return;
          const data = await act(`/api/admin/users/${u.id}/password`, {
            method: "POST",
            json: { password: answer || null },
          });
          if (data) prompt(t("new_password_show"), data.password);
        })
      );
      if (!own && u.role !== "admin") {
        side.append(
          button(t(u.blocked ? "unblock" : "block"), "mini", async () => {
            if (!u.blocked && !confirm(t("block_q", { name: u.username }))) return;
            const ok = await act(`/api/admin/users/${u.id}/block`, {
              method: "POST",
              json: { blocked: !u.blocked },
            });
            if (ok) loadUsers();
          })
        );
      }
      if (!own) {
        side.append(
          button(t("delete"), "mini danger", () => {
            if (confirm(t("delete_user_q", { name: u.username }))) {
              act(`/api/admin/users/${u.id}`, { method: "DELETE" }, loadUsers);
            }
          })
        );
      }
      li.append(info, side);
      return li;
    })
  );
}

function statCard(label, value) {
  const card = el("div", "stat");
  card.append(el("div", "stat-value", String(value)), el("div", "stat-label", label));
  return card;
}

function statRows(node, rows, empty) {
  node.replaceChildren(
    ...(rows.length
      ? rows.map(([title, value]) => {
          const li = el("li", "item");
          li.append(el("div", "item-title", title), el("span", "state", String(value)));
          return li;
        })
      : [el("li", "empty", empty)])
  );
}

async function loadStats() {
  const res = await api("/api/admin/stats");
  if (!res.ok) return;
  const d = res.data;
  const roles = d.roles || {};
  $("stat-cards").replaceChildren(
    statCard(t("stat_today"), d.searches_today),
    statCard(t("stat_30"), d.searches_30d),
    statCard(t("stat_users"), Object.values(roles).reduce((x, y) => x + y, 0)),
    statCard(t("stat_files"), d.files.files),
    statCard(t("stat_records"), d.files.records),
    statCard(t("stat_db"), size(d.db_bytes))
  );
  const max = Math.max(1, ...d.per_day.map((p) => p.searches));
  $("stat-chart").replaceChildren(
    ...d.per_day.map((p) => {
      const bar = el("div", "chart-bar");
      bar.style.height = `${Math.max(2, Math.round((p.searches / max) * 100))}%`;
      bar.title = `${p.day}: ${p.searches}`;
      return bar;
    })
  );
  statRows($("stat-queries"), d.top_queries.map((q) => [q.query, q.n]), t("no_queries"));
  statRows($("stat-users"), d.top_users.map((u) => [u.username, u.total]), t("no_data"));
}

async function loadMissed() {
  const res = await api("/api/admin/missed");
  if (!res.ok) return;
  if (!res.data.length) {
    $("missed").replaceChildren(el("li", "empty", t("missed_empty")));
    return;
  }
  $("missed").replaceChildren(
    ...res.data.map((m) => {
      const li = el("li", "item");
      const info = el("div", "item-info");
      info.append(el("div", "item-title", m.query), el("div", "item-sub", date(m.last)));
      const side = el("div", "item-side");
      side.append(el("span", "state", t("missed_times", { n: m.n })));
      li.append(info, side);
      return li;
    })
  );
}

$("missed-clear").addEventListener("click", () => {
  if (confirm(t("history_clear_q"))) act("/api/admin/missed", { method: "DELETE" }, loadMissed);
});

function backupStatusText(s) {
  if (!s) return "";
  const action = t(s.action === "restore" ? "act_restore" : "act_backup");
  const file = s.file || "";
  if (s.state === "running") return t("backup_running", { action, file });
  if (s.state === "ok") {
    const text = t("backup_ok", { action, file });
    return s.action === "restore" ? `${text}, ${t("backup_restart")}` : text;
  }
  return t("backup_failed", { action, file, message: s.message || "" });
}

async function loadBackups() {
  const res = await api("/api/admin/backups");
  if (!res.ok) return;
  const box = $("backup-status");
  const text = backupStatusText(res.data.status);
  box.hidden = !text;
  box.textContent = text;
  box.className = `status ${res.data.status ? res.data.status.state : ""}`;
  const items = res.data.items;
  if (!items.length) {
    $("backups").replaceChildren(el("li", "empty", t("backup_empty")));
    return;
  }
  $("backups").replaceChildren(
    ...items.map((b) => {
      const li = el("li", "item");
      const info = el("div", "item-info");
      info.append(el("div", "item-title mono", b.name), el("div", "item-sub", `${date(b.at * 1000)} · ${size(b.size)}`));
      const side = el("div", "item-side");
      side.append(
        button(t("backup_download"), "mini", () =>
          download(`/api/admin/backups/${encodeURIComponent(b.name)}`, b.name)
        ),
        button(t("backup_restore"), "mini danger", () => {
          if (!confirm(t("backup_confirm", { name: b.name }))) return;
          act("/api/admin/backups/restore", { method: "POST", json: { name: b.name } }, () => {
            toast(t("backup_queued"));
            loadBackups();
          });
        })
      );
      li.append(info, side);
      return li;
    })
  );
}

$("backup-create").addEventListener("click", () => {
  act("/api/admin/backups", { method: "POST" }, () => {
    toast(t("backup_queued"));
    setTimeout(loadBackups, 1500);
  });
});

function auditRow(e) {
  const li = el("li", "item");
  const info = el("div", "item-info");
  const label = DICT[LANG][`a_${e.action}`] || e.action;
  const title = `${label}${e.actor_name ? ` · ${e.actor_name}` : ""}`;
  const parts = e.details
    ? Object.entries(e.details)
        .filter(([, v]) => v !== null && v !== "")
        .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
    : [];
  info.append(el("div", "item-title", title), el("div", "item-sub detail", [date(e.at), ...parts].join(" · ")));
  li.append(info);
  return li;
}

async function loadAudit(reset) {
  if (reset) auditBefore = null;
  const params = new URLSearchParams({ limit: "50" });
  if (auditBefore) params.set("before", String(auditBefore));
  if ($("audit-action").value) params.set("action", $("audit-action").value);
  if ($("audit-actor").value.trim()) params.set("actor", $("audit-actor").value.trim());
  const res = await api(`/api/admin/audit?${params}`);
  if (!res.ok) return;
  const rows = res.data.items.map(auditRow);
  if (reset) {
    $("audit").replaceChildren(...(rows.length ? rows : [el("li", "empty", t("audit_empty"))]));
    const kinds = await api("/api/admin/audit/actions");
    if (kinds.ok) {
      const select = $("audit-action");
      const value = select.value;
      select.replaceChildren(new Option(t("all_actions"), ""));
      kinds.data.forEach((a) => select.append(new Option(DICT[LANG][`a_${a}`] || a, a)));
      select.value = value;
    }
  } else {
    $("audit").append(...rows);
  }
  const items = res.data.items;
  auditBefore = items.length ? items[items.length - 1].id : auditBefore;
  $("audit-more").hidden = !res.data.more;
}

$("audit-form").addEventListener("submit", (e) => {
  e.preventDefault();
  loadAudit(true);
});

$("audit-more").addEventListener("click", () => loadAudit(false));

document.querySelectorAll("[data-auth]").forEach((node) => {
  node.addEventListener("click", () => {
    const mode = node.dataset.auth;
    document.querySelectorAll("[data-auth]").forEach((n) => n.classList.toggle("active", n === node));
    $("login-form").hidden = mode !== "login";
    $("register-form").hidden = mode !== "register";
    $("auth").querySelector("h1").textContent = t(mode === "login" ? "auth_title" : "register");
  });
});

async function enter(url, json) {
  const res = await api(url, { method: "POST", json });
  if (!res.ok) {
    toast(detail(res));
    return;
  }
  await boot();
}

$("login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  enter("/api/auth/login", { username: $("login-name").value, password: $("login-pass").value });
});

$("register-form").addEventListener("submit", (e) => {
  e.preventDefault();
  enter("/api/auth/register", {
    token: $("reg-token").value,
    username: $("reg-name").value,
    password: $("reg-pass").value,
  });
});

$("logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  me = null;
  current = null;
  $("results").replaceChildren();
  $("result-tools").hidden = true;
  $("more").hidden = true;
  showAuth();
});

function refreshLang() {
  applyStatic();
  document.title = t("title");
  if (!me) return;
  renderMe();
  renderNav();
  switchTab(tab);
  if (current && current.items.length) {
    refreshTools();
    drawResults();
  }
}

document.querySelectorAll("[data-lang]").forEach((node) => {
  node.addEventListener("click", () => {
    setLang(node.dataset.lang);
    refreshLang();
  });
});

async function boot() {
  const res = await api("/api/auth/me");
  if (!res.ok) {
    me = null;
    showAuth();
    return;
  }
  me = res.data;
  $("login-pass").value = "";
  $("reg-pass").value = "";
  showApp();
}

setLang(detectLang());
applyStatic();
document.title = t("title");
boot();
