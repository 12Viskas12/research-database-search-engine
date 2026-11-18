const filesEl = document.getElementById("files");
const resultsEl = document.getElementById("results");
const statsEl = document.getElementById("stats");

const STATUS = {
  pending: "в очереди",
  processing: "загрузка",
  packing: "сжатие",
  unpacking: "распаковка",
  done: "готово",
  failed: "ошибка",
};
const BUSY = ["processing", "packing", "unpacking"];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
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

async function post(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "Ошибка");
    return false;
  }
  loadFiles();
  return true;
}

function action(label, handler) {
  const button = el("button", "link", label);
  button.type = "button";
  button.addEventListener("click", handler);
  return button;
}

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
  if (busy && f.progress === 0) {
    fill.classList.add("indeterminate");
  } else {
    fill.style.width = f.status === "done" ? "100%" : `${f.progress}%`;
  }
  const bar = el("div", "bar");
  bar.append(fill);

  li.append(head, bar);

  if (f.status === "done") {
    const actions = el("div", "actions");
    if (f.packed) {
      actions.append(action("Распаковать", () => post(`/api/compress/files/${f.id}/unpack`)));
    } else {
      actions.append(action("Сжать", () => post(`/api/compress/files/${f.id}/pack`)));
    }
    li.append(actions);
  }
  if (f.error) li.append(el("div", "file-error", f.error));
  return li;
}

async function loadFiles() {
  const res = await fetch("/api/files");
  if (!res.ok) return;
  const files = await res.json();
  filesEl.replaceChildren(...files.map(renderFile));
  loadStats();
}

async function loadStats() {
  const res = await fetch("/api/compress/stats");
  if (!res.ok) return;
  const s = await res.json();
  if (!s.files) {
    statsEl.textContent = "";
    return;
  }
  let text = `Файлов: ${s.files}, сжато: ${s.packed_files}`;
  if (s.packed_files && s.packed_bytes > 0) {
    text += `. Сжатые данные: ${size(s.raw_bytes)} → ${size(s.packed_bytes)}`;
  }
  text += `. На диске: записи ${size(s.records_size)}, сжатые блоки ${size(s.blocks_size)}`;
  statsEl.textContent = text;
}

function renderItem(item) {
  const data = item.data || item;
  const card = el("div", "card");
  for (const [k, v] of Object.entries(data)) {
    if (v === null || v === "") continue;
    const row = el("div", "row");
    row.append(el("b", "", `${k}: `), String(v));
    card.append(row);
  }
  return card;
}

document.getElementById("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("file");
  const body = new FormData();
  body.append("file", input.files[0]);
  const res = await fetch("/api/files", { method: "POST", body });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || "Ошибка загрузки");
    return;
  }
  input.value = "";
  loadFiles();
});

document.getElementById("merge-all").addEventListener("click", () => {
  if (!confirm("Все готовые файлы будут объединены в один и сжаты. Исходные файлы заменятся. Продолжить?")) return;
  post("/api/compress/merge", {});
});

document.getElementById("reclaim").addEventListener("click", async () => {
  if (await post("/api/compress/reclaim")) alert("Запущено, поиск может ненадолго замедлиться");
});

document.getElementById("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = document.getElementById("query").value.trim();
  if (!q) return;
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) return;
  const { items } = await res.json();
  if (!items.length) {
    resultsEl.replaceChildren(el("p", "empty", "Ничего не найдено"));
    return;
  }
  resultsEl.replaceChildren(...items.map(renderItem));
});

loadFiles();
setInterval(loadFiles, 1500);
