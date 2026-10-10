/* Веб-редактор: собирает конфиг из формы и обновляет превью на лету. */

const QUICK_EMOJI = ["🔥", "❤️", "👍", "🎉", "😂", "😮", "😢", "🙏", "👏", "🤔",
  "💯", "⚡️", "🚀", "⭐️", "👀", "🥳", "😍", "🤩", "💎", "📈"];

const state = {
  token: null,
  defaults: window.__DEFAULTS__ || {},
  timer: null,
};

/* ---------- утилиты ---------- */
const $ = (id) => document.getElementById(id);

function getPath(obj, path) {
  return path.split(".").reduce((acc, p) => (acc == null ? acc : acc[p]), obj);
}

function setPath(obj, path, value) {
  const parts = path.split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i++) {
    if (typeof cur[parts[i]] !== "object" || cur[parts[i]] === null) cur[parts[i]] = {};
    cur = cur[parts[i]];
  }
  cur[parts[parts.length - 1]] = value;
}

function fieldValue(el) {
  if (el.type === "checkbox") return el.checked;
  if (el.type === "number") return Number(el.value || 0);
  if (el.value === "true") return true;
  if (el.value === "false") return false;
  return el.value;
}

/* ---------- сборка конфига ---------- */
function collectConfig() {
  const cfg = JSON.parse(JSON.stringify(state.defaults));
  document.querySelectorAll("#form [id]").forEach((el) => {
    if (!el.id.includes(".")) return;
    if (el.tagName === "DIV" || el.tagName === "BUTTON") return;
    setPath(cfg, el.id, fieldValue(el));
  });
  // реакции
  cfg.post.reactions = [...document.querySelectorAll(".reaction")].map((row) => ({
    emoji: row.querySelector(".r-emoji").value,
    count: Number(row.querySelector(".r-count").value || 0),
    selected: row.querySelector(".r-sel").checked,
  })).filter((r) => r.emoji.trim() !== "");
  // кнопки
  const buttons = $("buttons").value.split("\n").map((s) => s.trim()).filter(Boolean);
  cfg.post.buttons = buttons;
  cfg._token = state.token;
  return cfg;
}

/* ---------- рендер ---------- */
async function render() {
  const cfg = collectConfig();
  const statusEl = $("status");
  try {
    const res = await fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg),
    });
    const data = await res.json();
    state.token = data.token;
    const img = $("preview-img");
    img.src = data.preview + "?t=" + Date.now();
    img.style.display = "block";
    $("preview-empty").style.display = "none";
    $("btn-png").disabled = false;
    $("btn-json").disabled = false;
    statusEl.textContent = "готово";
    const dev = cfg.screen.device || "iphone_15_pro";
    statusEl.textContent = "готово · " + dev;
  } catch (err) {
    statusEl.textContent = "ошибка рендера";
    console.error(err);
  }
}

function scheduleRender() {
  clearTimeout(state.timer);
  state.timer = setTimeout(render, 350);
}

/* ---------- реакции ---------- */
function addReaction(emoji = "👍", count = 0, selected = false) {
  const wrap = document.createElement("div");
  wrap.className = "reaction";
  wrap.innerHTML = `
    <input class="r-emoji" type="text" value="${emoji}">
    <input class="r-count" type="number" min="0" value="${count}">
    <label class="check"><input class="r-sel" type="checkbox" ${selected ? "checked" : ""}> выбрана</label>
    <button class="btn small" data-del="1">✕</button>
  `;
  wrap.querySelectorAll("input").forEach((i) => i.addEventListener("input", scheduleRender));
  wrap.querySelector("[data-del]").addEventListener("click", () => {
    wrap.remove();
    scheduleRender();
  });
  $("reactions").appendChild(wrap);
}

function renderQuickEmoji() {
  const box = $("quick-emoji");
  QUICK_EMOJI.forEach((e) => {
    const b = document.createElement("button");
    b.textContent = e;
    b.title = "Добавить реакцию " + e;
    b.addEventListener("click", () => {
      addReaction(e, Math.floor(Math.random() * 400) + 10, false);
      scheduleRender();
    });
    box.appendChild(b);
  });
}

/* ---------- загрузка файлов ---------- */
async function upload(input, hiddenId) {
  const file = input.files && input.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  $("status").textContent = "загрузка…";
  const res = await fetch("/api/upload", { method: "POST", body: fd });
  const data = await res.json();
  if (data.path) {
    $(hiddenId).value = data.path;
    render();
  } else {
    $("status").textContent = data.error || "ошибка загрузки";
  }
}

/* ---------- инициализация ---------- */
function applyDefaults(cfg) {
  document.querySelectorAll("#form [id]").forEach((el) => {
    if (!el.id.includes(".")) return;
    const v = getPath(cfg, el.id);
    if (v === undefined) return;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v;
  });
  $("reactions").innerHTML = "";
  (cfg.post.reactions || []).forEach((r) => addReaction(r.emoji, r.count, !!r.selected));
  $("buttons").value = (cfg.post.buttons || [])
    .map((row) => (Array.isArray(row) ? row.join(" | ") : row.text || row)).join("\n");
}

function init() {
  applyDefaults(state.defaults);
  renderQuickEmoji();

  document.querySelectorAll("#form input, #form select, #form textarea").forEach((el) => {
    el.addEventListener("input", scheduleRender);
    el.addEventListener("change", scheduleRender);
  });

  $("add-reaction").addEventListener("click", () => { addReaction(); scheduleRender(); });

  $("media-file").addEventListener("change", (e) => upload(e.target, "post.media"));
  $("avatar-file").addEventListener("change", (e) => upload(e.target, "channel.avatar"));

  document.querySelectorAll("[data-clear]").forEach((btn) => {
    btn.addEventListener("click", () => {
      $(btn.dataset.clear).value = "";
      render();
    });
  });

  $("btn-png").addEventListener("click", () => {
    if (state.token) window.location.href = "/download/" + state.token + ".png";
  });
  $("btn-json").addEventListener("click", () => {
    if (state.token) window.location.href = "/download-config/" + state.token + ".json";
  });
  $("btn-reset").addEventListener("click", () => {
    applyDefaults(JSON.parse(JSON.stringify(state.defaults)));
    render();
  });

  document.querySelectorAll("[data-preset]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.preset;
      $("status").textContent = "загружаю пресет…";
      try {
        const res = await fetch("/api/presets/" + name);
        const cfg = await res.json();
        if (cfg.error) throw new Error(cfg.error);
        state.defaults = cfg;
        applyDefaults(cfg);
        render();
      } catch (err) {
        $("status").textContent = "ошибка пресета";
        console.error(err);
      }
    });
  });

  $("zoom-fit").addEventListener("change", (e) => {
    $("preview-img").classList.toggle("fit-off", !e.target.checked);
  });

  $("preview-img").addEventListener("load", (e) => {
    $("size").textContent = e.target.naturalWidth + "×" + e.target.naturalHeight + " px";
  });

  render();
}

document.addEventListener("DOMContentLoaded", init);
