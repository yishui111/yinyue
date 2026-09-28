let SONG = null;       // 当前加载的旋律（可能含已填的 char）
let NAME = null;       // 当前旋律名
let SING_FILE = null;

const $ = s => document.querySelector(s);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

async function api(path, opts = {}) {
  let r;
  try {
    r = await fetch(path, opts);
  } catch (e) {
    throw new Error("无法连接工作台服务。请双击「启动工作台.bat」，等页面能打开后再操作。");
  }
  if (!r.ok) {
    let msg = await r.text();
    try { msg = JSON.parse(msg).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}

function setStatus(t, cls) {
  const s = $("#status");
  s.textContent = t;
  s.className = "status " + (cls || "");
}

/* ---------------- 旋律库 ---------------- */
async function loadMelodies() {
  const list = await api("/api/melodies");
  const box = $("#melody-list");
  box.innerHTML = "";
  if (!list.length) {
    box.appendChild(el("div", "hint", "曲库还是空的：点「旋律生成文档」去 DeepSeek 生成一段旋律，再导入。"));
    return;
  }
  list.forEach(m => {
    const b = el("button", "songitem" + (NAME === m.name ? " active" : ""));
    b.textContent = `${m.title}（${m.key || "?"} · ${m.lines || "?"}句${m.filled ? " · 已填词" : ""}）`;
    b.onclick = () => pickMelody(m.name);
    box.appendChild(b);
  });
}

async function pickMelody(name) {
  SONG = await api(`/api/melody?name=${encodeURIComponent(name)}`);
  NAME = name;
  setStatus(`已选《${SONG.title}》`, "ok");
  $("#no-melody").style.display = "none";
  $("#fill-area").style.display = "";
  $("#no-melody2").style.display = "none";
  $("#sing-area").style.display = "";
  $("#editor").style.display = "";
  renderSong();
}

async function importMelody() {
  const text = $("#imp-text").value;
  if (!text.trim()) return alert("请先粘贴 DeepSeek 回复的 JSON");
  try {
    const r = await api("/api/melody/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: $("#imp-name").value.trim(), text })
    });
    setStatus(`旋律「${r.name}」已导入曲库 ✓`, "ok");
    $("#imp-text").value = "";
    await loadMelodies();
    await pickMelody(r.name);
  } catch (e) {
    setStatus("导入失败：" + e.message, "err");
  }
}

async function showMelodyDoc() {
  const r = await api("/api/melodydoc");
  const box = $("#melodydoc-box");
  box.style.display = "";
  $("#btn-copydoc").style.display = "";
  box.value = r.doc;
  box.select();
  setStatus("旋律生成文档已生成：复制全文 → 粘到 DeepSeek 网页对话框（先改开头的填写区）", "ok");
}

/* ---------------- 旋律表格 ---------------- */
const NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"];
const DEG = {0:"1",2:"2",4:"3",5:"4",7:"5",9:"6",11:"7"};

function noteName(midi) {
  return midi == null ? "—" : NOTE_NAMES[midi % 12] + (Math.floor(midi / 12) - 1);
}

function renderSong() {
  if (!SONG) return;
  $("#songbar").style.display = "flex";
  $("#title").value = SONG.title || "";
  const total = SONG.lines.reduce((a, l) => a + l.notes.length, 0);
  const sung = SONG.lines.reduce((a, l) => a + l.notes.filter(n => n.char || n.new_char).length, 0);
  $("#meta").textContent =
    `${SONG.key || "?"} · ${SONG.bpm || "?"} BPM · ${SONG.lines.length} 句 · ${total} 音 · 已填词 ${sung} 字`;
  const box = $("#lines");
  box.innerHTML = "";
  for (const ln of SONG.lines) box.appendChild(renderLine(ln));
}

function renderLine(ln) {
  const card = el("div", "line");
  const head = el("div", "line-head");
  head.appendChild(el("span", "line-id", "#" + ln.line_id));
  if (ln.text) head.appendChild(el("span", "line-orig", ln.text));
  if (ln.new_text) head.appendChild(el("span", "line-new", "→ " + ln.new_text));
  const cur = ln.notes.map(n => n.new_char || n.char || "").join("");
  const btnEdit = el("button", "mini", "✏️ 本句打字");
  head.appendChild(btnEdit);
  card.appendChild(head);

  const box = el("div", "line-edit");
  box.style.display = "none";
  const input = el("input");
  input.value = cur;
  const cnt = el("span", "cnt", `需 ${ln.notes.length} 字`);
  const sync = () => { cnt.textContent = `需 ${ln.notes.length} 字 / 你 ${[...input.value].filter(c => !/[\s，。！？、：；,.!?;:~～…（）"'“”]/.test(c)).length} 字`; };
  input.oninput = sync;
  const applyOne = async () => {
    const chars = [...input.value].filter(c => !/[\s，。！？、：；,.!?;:~～…（）"'“”]/.test(c));
    if (chars.length !== ln.notes.length) return alert(`这句需要 ${ln.notes.length} 个字，你写了 ${chars.length} 个。`);
    ln.notes.forEach((n, i) => n.char = chars[i]);
    ln.new_text = chars.join("");
    await saveNow();
    renderSong();
  };
  const apply = el("button", "mini ok", "应用");
  apply.onclick = applyOne;
  input.onkeydown = e => { if (e.key === "Enter") applyOne(); };
  box.appendChild(input);
  box.appendChild(cnt);
  box.appendChild(apply);
  card.appendChild(box);
  btnEdit.onclick = () => { box.style.display = box.style.display === "none" ? "flex" : "none"; input.focus(); };

  const row = el("div", "notes");
  ln.notes.forEach(n => row.appendChild(renderNote(n)));
  card.appendChild(row);
  return card;
}

function renderNote(n) {
  const cell = el("div", "note");
  const cin = el("input", "char");
  cin.value = n.new_char || n.char || "";
  cin.onchange = () => { n.char = cin.value; scheduleSave(); };
  cell.appendChild(cin);
  const sub = el("div", "sub");
  sub.appendChild(el("span", "jp", n.jianpu || ""));
  sub.appendChild(el("span", "nn", noteName(n.midi)));
  cell.appendChild(sub);
  const row2 = el("div", "editrow");
  const mid = el("input", "midi");
  mid.type = "number";
  mid.value = n.midi;
  mid.onchange = () => { n.midi = parseInt(mid.value) || n.midi; scheduleSave(); renderSong(); };
  const dur = el("input", "dur");
  dur.type = "number";
  dur.step = "0.05";
  dur.value = n.duration;
  dur.onchange = () => { n.duration = parseFloat(dur.value) || 0.5; scheduleSave(); };
  row2.appendChild(mid);
  row2.appendChild(el("span", "unit", "·"));
  row2.appendChild(dur);
  cell.appendChild(row2);
  return cell;
}

/* ---------------- 填词文档（DeepSeek 网页流程） ---------------- */
async function genFillDoc() {
  if (!SONG) return;
  await saveNow();
  const q = new URLSearchParams({ name: NAME, story: $("#story").value.trim(), extra: $("#extra").value.trim() });
  const r = await api(`/api/filldoc?${q}`);
  const box = $("#filldoc-box");
  box.value = r.doc;
  box.select();
  setStatus("填词文档已生成 ✓ 复制全文，连同你的故事发给 DeepSeek 网页对话框", "ok");
}

async function copyFillDoc() {
  const t = $("#filldoc-box");
  if (!t.value) return alert("请先生成填词文档");
  try {
    await navigator.clipboard.writeText(t.value);
    setStatus("已复制 ✓ 粘到 DeepSeek 对话框，加上你的故事，发送", "ok");
  } catch (e) {
    t.select();
    document.execCommand("copy");
  }
}

async function applyReply() {
  const text = $("#ds-reply").value;
  if (!text.trim()) return alert("请先把 DeepSeek 回复的 JSON 粘进来");
  try {
    SONG = await api("/api/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: NAME, json_text: text })
    });
    setStatus("填词已应用 ✓ 逐字对位，旋律未动。可以点「🎤 按旋律唱出来」了", "ok");
    renderSong();
  } catch (e) {
    setStatus("应用失败（详见弹窗）", "err");
    alert("校验未通过。把下面的错误原样发给 DeepSeek 让它修正：\n\n" + e.message);
  }
}

async function clearFill() {
  if (!confirm("还原为填词前的原词？")) return;
  await api("/api/melody/clearfill", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: NAME })
  });
  SONG = await api(`/api/melody?name=${encodeURIComponent(NAME)}`);
  renderSong();
  setStatus("已还原原词", "ok");
}

/* ---------------- 保存 ---------------- */
let saveTimer = null;
function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 800);
}
async function saveNow() {
  if (!SONG) return;
  SONG.title = $("#title").value || SONG.title;
  await api("/api/melody/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: NAME, melody: SONG })
  });
  setStatus("已保存", "ok");
}

/* ---------------- 演唱 / 导出 ---------------- */
async function sing() {
  if (!SONG) return;
  const hasChar = SONG.lines.some(l => l.notes.some(n => n.char));
  if (!hasChar) return alert("这段旋律还没有字：请先填词或手动打字。");
  await saveNow();
  $("#btn-sing").disabled = true;
  setStatus("演唱合成中（逐字调用 GPT-SoVITS，进度见下方）…", "busy");
  try {
    const r = await api("/api/sing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: NAME,
        voice: $("#sing-voice").value.trim(),
        limit_seconds: $("#sing-short").checked ? 60 : 0
      })
    });
    SING_FILE = r.file;
    pollJob(r.job_id);
  } catch (e) {
    setStatus("提交失败：" + e.message, "err");
    $("#btn-sing").disabled = false;
  }
}

let pollTimer = null;
function pollJob(jobId) {
  $("#prog").style.display = "";
  clearInterval(pollTimer);
  let errs = 0;
  pollTimer = setInterval(async () => {
    let j;
    try {
      j = await api(`/api/progress/${jobId}`);
      errs = 0;
    } catch (e) {
      errs += 1;
      if (errs >= 15) {
        clearInterval(pollTimer);
        $("#btn-sing").disabled = false;
        setStatus("与服务失联。请刷新页面；若页面打不开就双击「启动工作台.bat」。", "err");
      }
      return;
    }
    renderProgress(j);
    if (!j.done) return;
    clearInterval(pollTimer);
    $("#btn-sing").disabled = false;
    if (j.error) {
      setStatus("演唱失败：" + j.error, "err");
      return;
    }
    if (SING_FILE) { $("#audio").src = SING_FILE; $("#audio").play(); }
    setStatus("演唱合成完成 ✓ 正在播放", "ok");
  }, 2000);
}

function renderProgress(j) {
  const secs = Math.max(0, Math.round(Date.now() / 1000 - j.started_at));
  $("#prog-elapsed").textContent = `已用 ${Math.floor(secs / 60)} 分 ${secs % 60} 秒`;
  $("#prog-detail").textContent = j.detail || "";
  const log = $("#prog-log");
  log.textContent = j.log.slice(-8).join("\n");
  log.scrollTop = log.scrollHeight;
}

async function exportFile(fmt) {
  if (!SONG) return;
  try {
    const r = await api("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: NAME, fmt })
    });
    if (fmt === "hum") {
      $("#audio").src = r.file;
      $("#audio").play();
      setStatus("哼鸣已生成，正在播放旋律 ✓", "ok");
    } else if (fmt === "karaoke") {
      window.open(r.file, "_blank");
      setStatus("卡拉OK视频已生成，已在新页面打开 ✓", "ok");
    } else {
      const a = el("a");
      a.href = r.file;
      a.download = "";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setStatus(`已导出 ${fmt}`, "ok");
    }
  } catch (e) {
    setStatus("导出失败：" + e.message, "err");
  }
}

/* ---------------- 设置 ---------------- */
async function openCfg() {
  const c = await api("/api/config");
  $("#cfg-url").value = c.gptsovits_url;
  $("#cfg-voice").value = c.gptsovits_voice || "";
  $("#cfg-dir").value = c.gptsovits_dir || "";
  $("#modal").style.display = "flex";
}
async function saveCfg() {
  await api("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      gptsovits_url: $("#cfg-url").value.trim(),
      gptsovits_voice: $("#cfg-voice").value.trim(),
      gptsovits_dir: $("#cfg-dir").value.trim()
    })
  });
  $("#modal").style.display = "none";
  setStatus("设置已保存", "ok");
}

/* ---------------- init ---------------- */
$("#btn-refresh").onclick = loadMelodies;
$("#btn-import").onclick = importMelody;
$("#btn-melodydoc").onclick = showMelodyDoc;
$("#btn-copydoc").onclick = async () => {
  const t = $("#melodydoc-box");
  try { await navigator.clipboard.writeText(t.value); setStatus("已复制 ✓", "ok"); }
  catch (e) { t.select(); document.execCommand("copy"); }
};
$("#btn-filldoc").onclick = genFillDoc;
$("#btn-copyfill").onclick = copyFillDoc;
$("#btn-apply").onclick = applyReply;
$("#btn-clearfill").onclick = clearFill;
$("#btn-sing").onclick = sing;
$("#btn-save").onclick = saveNow;
document.querySelectorAll("[data-fmt]").forEach(b => b.onclick = () => exportFile(b.dataset.fmt));
$("#btn-cfg").onclick = openCfg;
$("#cfg-save").onclick = saveCfg;
$("#cfg-close").onclick = () => $("#modal").style.display = "none";

async function checkCfg() {
  try {
    const c = await api("/api/config");
    $("#sing-voice").value = c.gptsovits_voice || "";
    $("#cfg-url").value = c.gptsovits_url || "";
  } catch (e) {}
}
async function init() {
  await loadMelodies();
  const q = new URLSearchParams(location.search);
  const nm = q.get("name");
  if (nm) {
    try { await pickMelody(nm); } catch (e) {}
    if (q.get("autodoc") === "1") { try { await genFillDoc(); } catch (e) {} }
  }
  checkCfg();
}
init();
