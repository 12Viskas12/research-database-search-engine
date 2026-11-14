const filesEl = document.getElementById("files");
const resultsEl = document.getElementById("results");

const STATUS = {
  pending: "в очереди",
  processing: "загрузка",
  done: "готово",
  failed: "ошибка",
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderFile(f) {
  const li = el("li", `file ${f.status}`);
  let meta = STATUS[f.status] || f.status;
  if (f.status === "processing" && f.progress > 0) meta = `${f.progress}%`;
  if (f.status === "done") meta = `готово, строк ${f.rows_count}`;

  const head = el("div", "file-head");
  head.append(el("span", "file-name", f.name), el("span", "file-meta", meta));

  const fill = el("div", "bar-fill");
  if (f.status === "processing" && f.progress === 0) {
    fill.classList.add("indeterminate");
  } else {
    fill.style.width = f.status === "done" ? "100%" : `${f.progress}%`;
  }
  const bar = el("div", "bar");
  bar.append(fill);

  li.append(head, bar);
  if (f.error) li.append(el("div", "file-error", f.error));
  return li;
}

async function loadFiles() {
  const res = await fetch("/api/files");
  if (!res.ok) return;
  const files = await res.json();
  filesEl.replaceChildren(...files.map(renderFile));
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
