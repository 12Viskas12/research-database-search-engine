const $ = (id) => document.getElementById(id);

const ROLE = { user: "Обычный", vip: "VIP", admin: "Админ" };
const STATUS = {
  pending: "в очереди",
  processing: "загрузка",
  packing: "сжатие",
  unpacking: "распаковка",
  done: "готово",
  failed: "ошибка",
  deleting: "удаление",
};
const BUSY = ["processing", "packing", "unpacking", "deleting"];
const TABS = [
  { id: "search", label: "Поиск" },
  { id: "history", label: "История" },
  { id: "profile", label: "Профиль" },
  { id: "files", label: "Файлы", admin: true },
  { id: "requests", label: "Заявки", admin: true },
  { id: "invites", label: "Токены", admin: true },
  { id: "users", label: "Пользователи", admin: true },
  { id: "stats", label: "Статистика", admin: true },
  { id: "audit", label: "Журнал", admin: true },
];

let me = null;
let tab = "search";
let timer = null;
let toastTimer = null;
let current = null;
let auditBefore = null;

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

function date(value) {
  return value
    ? new Date(value).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })
    : "";
}

function size(bytes) {
  const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
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

function detail(res, fallback = "Ошибка") {
  const d = res.data && res.data.detail;
  if (typeof d === "string") return d;
  return d ? "Проверьте введенные данные" : fallback;
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

function showApp() {
  $("auth").hidden = true;
  $("app").hidden = false;
  $("me").hidden = false;
  renderMe();
  const nav = $("nav");
  const tabs = TABS.filter((t) => !t.admin || me.role === "admin");
  nav.replaceChildren(
    ...tabs.map((t) => {
      const b = button(t.label, "tab", () => switchTab(t.id));
      b.dataset.tab = t.id;
      return b;
    })
  );
  nav.hidden = tabs.length < 2;
  switchTab("search");
}

function renderMe() {
  $("me-name").textContent = me.username;
  const badge = $("me-role");
  badge.textContent = ROLE[me.role];
  badge.className = `badge ${me.role}`;
  badge.title = me.role_until ? `до ${date(me.role_until)}` : "";
  const rank = me.rank;
  let text = `${rank.title} · поисков: ${rank.total}`;
  if (rank.next_at) text += ` · до «${rank.next_title}» ещё ${rank.next_at - rank.total}`;
  $("me-rank").textContent = text;
  renderQuota(me.quota);
}

function renderQuota(quota) {
  const text = $("quota-text");
  const fill = $("quota-fill");
  fill.className = "bar-fill";
  if (quota.limit === null) {
    text.textContent = "Запросов без ограничений";
    fill.style.width = "100%";
    return;
  }
  text.textContent = `Запросов в этом месяце: ${quota.used} из ${quota.limit}`;
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
  if (before && before !== me.rank.title) toast(`Новое звание: ${me.rank.title}!`);
}

function switchTab(id) {
  tab = id;
  clearInterval(timer);
  document.querySelectorAll("[data-tab]").forEach((node) => {
    if (node.tagName === "SECTION") node.hidden = node.dataset.tab !== id;
    else node.classList.toggle("active", node.dataset.tab === id);
  });
  const loaders = {
    files: [loadFiles, 1500],
    requests: [loadRequests, 5000],
    invites: [loadInvites, 0],
    users: [loadUsers, 0],
    audit: [() => loadAudit(true), 0],
    stats: [loadStats, 0],
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
  const marks = [...new Set(list.filter(Boolean))].sort((a, b) => b.length - a.length);
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

function renderItem(item, list, title, hidden) {
  const data = item.data || item;
  const card = el("div", "card");
  if (title) card.append(el("div", "card-title", title));
  for (const [k, v] of Object.entries(data)) {
    if (v === null || v === "" || (hidden && hidden.has(k))) continue;
    const row = el("div", "row");
    row.append(el("b", "", `${k}: `), highlight(String(v), list));
    card.append(row);
  }
  return card;
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

function columnsOf(items) {
  const keys = [];
  for (const item of items) {
    for (const key of Object.keys(item.data || item)) if (!keys.includes(key)) keys.push(key);
  }
  return keys;
}

function sortedItems() {
  const items = [...current.items];
  const [field, dir] = $("sort").value.split(":");
  if (!field) return items;
  const sign = dir === "desc" ? -1 : 1;
  const value = (item) => String((item.data || item)[field] ?? "");
  return items.sort(
    (x, y) => sign * value(x).localeCompare(value(y), "ru", { numeric: true })
  );
}

function refreshTools() {
  const keys = columnsOf(current.items);
  const sort = $("sort");
  const chosen = sort.value;
  sort.replaceChildren(new Option("Как найдено", ""));
  for (const key of keys) {
    sort.append(new Option(`${key} А-Я`, `${key}:asc`), new Option(`${key} Я-А`, `${key}:desc`));
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
  const hidden = hiddenCols();
  $("results").replaceChildren(
    ...(items.length
      ? items.map((item) => renderItem(item, current.marks, "", hidden))
      : [el("p", "empty", "Ничего не найдено")])
  );
  $("more").hidden = !current.more;
  $("result-tools").hidden = !items.length;
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
  select.replaceChildren(new Option("Все файлы", ""));
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
  if (state.searchId && state.offset) params.set("search_id", String(state.searchId));
  return `/api/search?${params}`;
}

async function startSearch(q, files) {
  const next = { q, files, offset: 0, searchId: null, marks: [], items: [], more: false };
  await runSearch(searchUrl(next), (data) => {
    current = next;
    current.searchId = data.search_id;
    current.marks = data.marks || [];
    current.items = data.items;
    current.more = data.more;
    refreshTools();
    drawResults();
  });
}

$("more").addEventListener("click", async () => {
  if (!current) return;
  const next = { ...current, offset: current.items.length };
  await runSearch(searchUrl(next), (data) => {
    current.items = current.items.concat(data.items);
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
    showMessage(renderItem(item, [], "Случайная запись", hiddenCols()));
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
    toast((data && data.detail) || "Ошибка");
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
  if (!current) return;
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
  $("bulk-summary").textContent = `Найдено ${res.data.found} из ${bulkRows.length}`;
  $("bulk-csv").hidden = false;
  $("bulk-result").replaceChildren(
    ...bulkRows.map((r) => {
      const li = el("li", "item");
      const info = el("div", "item-info");
      info.append(el("div", "item-title", r.value));
      if (r.item) {
        const data = r.item.data || r.item;
        const line = Object.values(data).filter((v) => v).join(" · ");
        info.append(el("div", "item-sub detail", line));
      }
      const side = el("div", "item-side");
      side.append(el("span", `badge ${r.found ? "vip" : ""}`, r.found ? "найдено" : "нет"));
      li.append(info, side);
      return li;
    })
  );
});

$("bulk-csv").addEventListener("click", () => {
  const keys = columnsOf(bulkRows.filter((r) => r.item).map((r) => r.item));
  const lines = [["value", "found", ...keys].map(csvCell).join(",")];
  for (const r of bulkRows) {
    const data = r.item ? r.item.data || r.item : {};
    lines.push([r.value, r.found ? "yes" : "no", ...keys.map((k) => data[k] ?? "")].map(csvCell).join(","));
  }
  saveBlob(new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" }), "bulk.csv");
});

async function loadHistory() {
  const res = await api("/api/history");
  if (!res.ok) return;
  if (!res.data.length) {
    $("history").replaceChildren(el("li", "empty", "История пуста"));
    return;
  }
  $("history").replaceChildren(
    ...res.data.map((h) => {
      const li = el("li", "item");
      const info = el("div", "item-info");
      const sub = [date(h.at), `найдено на первой странице: ${h.results}`];
      if (h.source === "bot") sub.push("бот");
      if (h.files) sub.push("с фильтром по файлу");
      info.append(el("div", "item-title", h.query), el("div", "item-sub", sub.join(" · ")));
      const side = el("div", "item-side");
      side.append(
        button("Повторить", "mini", () => {
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
  if (confirm("Очистить историю поиска?")) act("/api/history", { method: "DELETE" }, loadHistory);
});

function renderProfile() {
  const box = $("tg-box");
  box.replaceChildren();
  if (me.tg_linked) {
    box.append(
      el("p", "muted", "Telegram привязан."),
      button("Отвязать", "mini danger", () =>
        act("/api/auth/tg", { method: "DELETE" }, async () => {
          await refreshMe();
          renderProfile();
        })
      )
    );
    return;
  }
  box.append(
    el("p", "muted", "Получите код и отправьте боту: /link КОД"),
    button("Получить код", "mini", () =>
      act("/api/auth/tg-code", { method: "POST" }, (d) => {
        const code = el("div", "token-box");
        code.append(
          el("span", "token mono", d.code),
          el("span", "muted-inline", `действует ${d.minutes} минут`),
          button("Копировать", "mini", () => copy(d.code))
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
    toast("Пароль изменен");
  }
});

function renderFile(f) {
  const li = el("li", `file ${f.status}`);
  const busy = BUSY.includes(f.status);
  let meta = STATUS[f.status] || f.status;
  if (busy && f.progress > 0) meta = `${STATUS[f.status]} ${f.progress}%`;
  if (f.status === "done") {
    meta = `строк ${f.rows_count}`;
    if (f.packed && f.packed_bytes > 0) {
      meta += `, сжато ${size(f.raw_bytes)} → ${size(f.packed_bytes)} (x${(f.raw_bytes / f.packed_bytes).toFixed(1)})`;
    } else if (f.packed) {
      meta += ", сжато";
    }
  }
  const head = el("div", "file-head");
  head.append(el("span", "file-name", f.name), el("span", "file-meta", meta));

  const fill = el("div", "bar-fill");
  if (busy && f.progress === 0) fill.classList.add("indeterminate");
  else fill.style.width = f.status === "done" ? "100%" : `${f.progress}%`;
  const bar = el("div", "bar");
  bar.append(fill);
  li.append(head, bar);

  if (f.status === "done" || f.status === "failed") {
    const actions = el("div", "toolbar actions");
    if (f.status === "done") {
      const kind = f.packed ? "unpack" : "pack";
      actions.append(
        button(f.packed ? "Распаковать" : "Сжать", "link", () =>
          act(`/api/compress/files/${f.id}/${kind}`, { method: "POST" }, loadFiles)
        )
      );
    } else {
      actions.append(
        button("Повторить", "link", () =>
          act(`/api/files/${f.id}/retry`, { method: "POST" }, loadFiles)
        )
      );
    }
    actions.append(
      button("Удалить", "link", () => {
        if (!confirm(`Удалить файл «${f.name}» и все его записи?`)) return;
        act(`/api/files/${f.id}`, { method: "DELETE" }, loadFiles);
      })
    );
    li.append(actions);
  }
  if (f.error) li.append(el("div", "file-error", f.error));
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
  let text = `Файлов: ${s.files}, сжато: ${s.packed_files}`;
  if (s.packed_files && s.packed_bytes > 0) {
    text += `. Сжатые данные: ${size(s.raw_bytes)} → ${size(s.packed_bytes)}`;
  }
  $("stats").textContent = `${text}. На диске: записи ${size(s.records_size)}, сжатые блоки ${size(s.blocks_size)}`;
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
  act("/api/admin/settings", { method: "PUT", json }, () => toast("Сохранено"));
});

$("vocab-rebuild").addEventListener("click", () => {
  act("/api/admin/vocab/rebuild", { method: "POST" }, () => toast("Словарь обновляется в фоне"));
});

$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("file");
  const form = new FormData();
  form.append("file", input.files[0]);
  const ok = await act("/api/files", { method: "POST", form });
  if (ok) {
    input.value = "";
    loadFiles();
  }
});

$("merge-all").addEventListener("click", () => {
  if (!confirm("Все готовые файлы будут объединены в один и сжаты. Исходные файлы заменятся. Продолжить?")) return;
  act("/api/compress/merge", { method: "POST", json: {} }, loadFiles);
});

$("reclaim").addEventListener("click", () => {
  act("/api/compress/reclaim", { method: "POST" }, () =>
    toast("Запущено, поиск может ненадолго замедлиться")
  );
});

function days(value) {
  return value ? Number(value) : null;
}

function term(role, n) {
  return role === "vip" && n ? ` · ${n} дн.` : "";
}

function who(r) {
  return r.tg_username ? `@${r.tg_username}` : `tg ${r.tg_id}`;
}

async function loadRequests() {
  const res = await api("/api/admin/requests");
  if (!res.ok) return;
  const list = res.data;
  if (!list.length) {
    $("requests").replaceChildren(el("li", "empty", "Заявок пока нет"));
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
              toast("Одобрено. Бот отправит токен пользователю, он есть и во вкладке «Токены»");
              loadRequests();
            }
          );
        side.append(
          button("Обычный", "mini", () => decide("user")),
          button("VIP", "mini", () => decide("vip")),
          button("Отклонить", "mini danger", () =>
            act(`/api/admin/requests/${r.id}/reject`, { method: "POST" }, loadRequests)
          )
        );
      } else {
        side.append(el("span", `state ${r.status}`, r.status === "approved" ? "одобрена" : "отклонена"));
      }
      li.append(info, side);
      return li;
    })
  );
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Скопировано");
  } catch {
    toast(text);
  }
}

function inviteState(i) {
  if (i.used_at) return { text: `использован${i.used_by_name ? `: ${i.used_by_name}` : ""}`, cls: "approved" };
  if (new Date(i.expires_at) < new Date()) return { text: "истек", cls: "rejected" };
  return { text: `активен до ${date(i.expires_at)}`, cls: "pending" };
}

async function loadInvites() {
  const res = await api("/api/admin/invites");
  if (!res.ok) return;
  const list = res.data;
  if (!list.length) {
    $("invites").replaceChildren(el("li", "empty", "Токенов пока нет"));
    return;
  }
  $("invites").replaceChildren(
    ...list.map((i) => {
      const state = inviteState(i);
      const li = el("li", "item");
      const info = el("div", "item-info");
      const title = el("div", "item-title mono", i.token);
      title.append(" ", el("span", `badge ${i.role}`, ROLE[i.role] + term(i.role, i.role_days)));
      info.append(title, el("div", "item-sub", [i.note, date(i.created_at)].filter(Boolean).join(" · ")));
      const side = el("div", "item-side");
      side.append(el("span", `state ${state.cls}`, state.text));
      if (!i.used_at) {
        side.append(
          button("Копировать", "mini", () => copy(i.token)),
          button("Удалить", "mini danger", () =>
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
    el("span", "badge " + data.role, ROLE[data.role] + term(data.role, data.role_days)),
    button("Копировать", "mini", () => copy(data.token))
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
      info.append(
        el("div", "item-title", own ? `${u.username} (вы)` : u.username),
        el(
          "div",
          "item-sub",
          `${u.blocked ? "заблокирован · " : ""}в этом месяце ${u.used}, всего ${u.total}${u.role_until ? ` · до ${date(u.role_until)}` : ""}${u.tg_id ? " · Telegram привязан" : ""} · ${date(u.created_at)}`
        )
      );
      const side = el("div", "item-side");
      const select = el("select");
      for (const [value, label] of Object.entries(ROLE)) {
        const option = el("option", "", label);
        option.value = value;
        option.selected = value === u.role;
        select.append(option);
      }
      select.disabled = own;
      select.addEventListener("change", async () => {
        let n = null;
        if (select.value === "vip") {
          const answer = prompt("На сколько дней VIP? Пусто = навсегда", "30");
          if (answer === null) {
            loadUsers();
            return;
          }
          n = days(answer.trim());
          if (answer.trim() && !n) {
            toast("Нужно число дней");
            loadUsers();
            return;
          }
        }
        const ok = await act(`/api/admin/users/${u.id}`, {
          method: "PATCH",
          json: { role: select.value, days: n },
        });
        if (ok) toast("Роль изменена");
        loadUsers();
      });
      side.append(select);
      side.append(
        button("Пароль", "mini", async () => {
          const answer = prompt("Новый пароль (пусто = случайный)", "");
          if (answer === null) return;
          const data = await act(`/api/admin/users/${u.id}/password`, {
            method: "POST",
            json: { password: answer || null },
          });
          if (data) prompt("Новый пароль, передайте пользователю:", data.password);
        })
      );
      if (!own && u.role !== "admin") {
        side.append(
          button(u.blocked ? "Разблокировать" : "Заблокировать", "mini", async () => {
            if (!u.blocked && !confirm(`Заблокировать ${u.username}? Его сессии закроются.`)) return;
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
          button("Удалить", "mini danger", () => {
            if (confirm(`Удалить пользователя ${u.username}?`)) {
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
    statCard("поисков сегодня", d.searches_today),
    statCard("поисков за 30 дней", d.searches_30d),
    statCard("пользователей", Object.values(roles).reduce((x, y) => x + y, 0)),
    statCard("файлов", d.files.files),
    statCard("записей", d.files.records),
    statCard("размер базы", size(d.db_bytes))
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
  statRows(
    $("stat-queries"),
    d.top_queries.map((q) => [q.query, q.n]),
    "Пока нет запросов"
  );
  statRows(
    $("stat-users"),
    d.top_users.map((u) => [u.username, u.total]),
    "Пока нет данных"
  );
}

const ACTION = {
  register: "регистрация",
  login: "вход",
  login_failed: "неудачный вход",
  password_changed: "смена пароля",
  password_reset: "сброс пароля",
  tg_linked: "привязка Telegram",
  tg_unlinked: "отвязка Telegram",
  role_changed: "смена роли",
  user_deleted: "удаление пользователя",
  invite_created: "токен создан",
  invite_deleted: "токен удален",
  request_approved: "заявка одобрена",
  request_rejected: "заявка отклонена",
  settings_changed: "настройки",
  file_uploaded: "загрузка файла",
  file_pack: "сжатие файла",
  file_unpack: "распаковка файла",
  files_merged: "объединение файлов",
  reclaim: "освобождение места",
  autopack: "автосжатие",
  vocab_rebuilt: "словарь поиска",
  file_retry: "повтор обработки",
  file_deleted: "удаление файла",
  file_recovered: "восстановление файла",
  user_blocked: "блокировка",
  user_unblocked: "разблокировка",
};

function auditRow(e) {
  const li = el("li", "item");
  const info = el("div", "item-info");
  const title = `${ACTION[e.action] || e.action}${e.actor_name ? ` · ${e.actor_name}` : ""}`;
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
    $("audit").replaceChildren(...(rows.length ? rows : [el("li", "empty", "Записей нет")]));
    const kinds = await api("/api/admin/audit/actions");
    if (kinds.ok) {
      const select = $("audit-action");
      const value = select.value;
      select.replaceChildren(new Option("Все действия", ""));
      kinds.data.forEach((a) => select.append(new Option(ACTION[a] || a, a)));
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
  $("results").replaceChildren();
  showAuth();
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

boot();
