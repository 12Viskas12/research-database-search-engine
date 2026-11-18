const $ = (id) => document.getElementById(id);

const ROLE = { user: "Обычный", vip: "VIP", admin: "Админ" };
const STATUS = {
  pending: "в очереди",
  processing: "загрузка",
  packing: "сжатие",
  unpacking: "распаковка",
  done: "готово",
  failed: "ошибка",
};
const BUSY = ["processing", "packing", "unpacking"];
const TABS = [
  { id: "search", label: "Поиск" },
  { id: "files", label: "Файлы", admin: true },
  { id: "requests", label: "Заявки", admin: true },
  { id: "invites", label: "Токены", admin: true },
  { id: "users", label: "Пользователи", admin: true },
];

let me = null;
let tab = "search";
let timer = null;
let toastTimer = null;

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
    text.textContent = "Запросов сегодня без ограничений";
    fill.style.width = "100%";
    return;
  }
  text.textContent = `Запросов сегодня: ${quota.used} из ${quota.limit}`;
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
  };
  const entry = loaders[id];
  if (!entry) return;
  entry[0]();
  if (entry[1]) timer = setInterval(entry[0], entry[1]);
}

function escapeRe(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function terms(query) {
  const found = query.toLowerCase().match(/[\p{L}\p{N}_]+/gu) || [];
  const list = found.length ? found : [query.trim().toLowerCase()];
  return [...new Set(list.filter(Boolean))].sort((a, b) => b.length - a.length);
}

function highlight(text, list) {
  const frag = document.createDocumentFragment();
  if (!list.length) {
    frag.append(text);
    return frag;
  }
  const re = new RegExp(`(${list.map(escapeRe).join("|")})`, "giu");
  text.split(re).forEach((part, i) => {
    if (i % 2) frag.append(el("mark", "", part));
    else if (part) frag.append(part);
  });
  return frag;
}

function renderItem(item, list, title) {
  const data = item.data || item;
  const card = el("div", "card");
  if (title) card.append(el("div", "card-title", title));
  for (const [k, v] of Object.entries(data)) {
    if (v === null || v === "") continue;
    const row = el("div", "row");
    row.append(el("b", "", `${k}: `), highlight(String(v), list));
    card.append(row);
  }
  return card;
}

function showResults(nodes) {
  $("results").replaceChildren(...nodes);
}

async function runSearch(url, render) {
  const res = await api(url);
  if (res.status === 429) {
    showResults([el("p", "empty", detail(res))]);
    refreshMe();
    return;
  }
  if (!res.ok) {
    showResults([el("p", "empty", detail(res))]);
    return;
  }
  render(res.data);
  if (res.data.quota) renderQuota(res.data.quota);
  refreshMe();
}

$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("query").value.trim();
  if (!q) return;
  const list = terms(q);
  runSearch(`/api/search?q=${encodeURIComponent(q)}`, ({ items }) => {
    showResults(
      items.length
        ? items.map((item) => renderItem(item, list))
        : [el("p", "empty", "Ничего не найдено")]
    );
  });
});

$("lucky").addEventListener("click", () => {
  runSearch("/api/lucky", ({ item }) => showResults([renderItem(item, [], "Случайная запись")]));
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

  if (f.status === "done") {
    const actions = el("div", "actions");
    const kind = f.packed ? "unpack" : "pack";
    actions.append(
      button(f.packed ? "Распаковать" : "Сжать", "link", () =>
        act(`/api/compress/files/${f.id}/${kind}`, { method: "POST" }, loadFiles)
      )
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
          act(`/api/admin/requests/${r.id}/approve`, { method: "POST", json: { role } }, () => {
            toast("Одобрено. Бот отправит токен пользователю, он есть и во вкладке «Токены»");
            loadRequests();
          });
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
      title.append(" ", el("span", `badge ${i.role}`, ROLE[i.role]));
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
  const json = { role: $("invite-role").value, note: $("invite-note").value };
  const data = await act("/api/admin/invites", { method: "POST", json });
  if (!data) return;
  $("invite-note").value = "";
  const box = $("new-token");
  box.hidden = false;
  box.replaceChildren(
    el("span", "token mono", data.token),
    el("span", "badge " + data.role, ROLE[data.role]),
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
          `сегодня ${u.today}, всего ${u.total}${u.tg_id ? " · Telegram привязан" : ""} · ${date(u.created_at)}`
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
        const ok = await act(`/api/admin/users/${u.id}`, { method: "PATCH", json: { role: select.value } });
        if (!ok) loadUsers();
        else toast("Роль изменена");
      });
      side.append(select);
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
