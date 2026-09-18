const samples = [
  "公司是否指定有合作的差旅预订平台？",
  "报销的单据逾期了怎么办？",
  "公派车辆出差，是否还能报销交通费用？",
  "紧急出差来不及走审批怎么办？",
  "公司出差津贴的计算标准",
  "因预算原因，费用报销流程无法提交怎么办？",
];

const logEl = document.getElementById("log");
const form = document.getElementById("form");
const qEl = document.getElementById("q");
const sendBtn = document.getElementById("send");
const statusEl = document.getElementById("status");
const samplesEl = document.getElementById("samples");
const healthEl = document.getElementById("health");
const fileListEl = document.getElementById("file-list");
const pdfInput = document.getElementById("pdf-input");
const ingestStatusEl = document.getElementById("ingest-status");
const HEADING = "【直接回答】";

samples.forEach((t) => {
  const li = document.createElement("li");
  li.textContent = t;
  li.onclick = () => {
    qEl.value = t;
    form.requestSubmit();
  };
  samplesEl.appendChild(li);
});

function applyHealth(d) {
  healthEl.textContent = `知识库 ${d.files} 份文件 / ${d.clauses} 条条款`;
}

function refreshFiles() {
  return fetch("/api/files")
    .then((r) => r.json())
    .then((d) => {
      applyHealth(d);
      fileListEl.innerHTML = "";
      (d.items || []).forEach((f) => {
        const li = document.createElement("li");
        li.className = "file-item";
        const title = document.createElement("div");
        title.textContent = f.title || f.id;
        const sub = document.createElement("div");
        sub.className = "sub";
        sub.textContent = `${f.doc_no || f.id} · ${f.clause_count || 0} 条`;
        li.appendChild(title);
        li.appendChild(sub);
        fileListEl.appendChild(li);
      });
    })
    .catch(() => {
      healthEl.textContent = "后端未连接";
    });
}

refreshFiles();

function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  if (text) div.textContent = text;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
  return div;
}

function fmtSec(ms) {
  return `${(ms / 1000).toFixed(1)}s`;
}

async function readSse(res, onEvent) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop();
    for (const block of parts) {
      let dataLine = "";
      let eventName = "message";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) dataLine += line.slice(5).trim();
      }
      if (!dataLine) continue;
      onEvent(eventName, JSON.parse(dataLine));
    }
  }
}

function ensureAnswer(body) {
  if (body.dataset.answerReady) return body._answerText;
  body.dataset.answerReady = "1";
  body.textContent = "";
  const heading = document.createElement("div");
  heading.className = "answer-heading";
  heading.textContent = HEADING;
  const text = document.createElement("div");
  text.className = "answer-body";
  body.appendChild(heading);
  body.appendChild(text);
  body._answerText = text;
  body._raw = "";
  return text;
}

function appendAnswer(body, piece) {
  const text = ensureAnswer(body);
  body._raw = (body._raw || "") + (piece || "");
  let shown = body._raw.replace(/^\s+/, "");
  if (shown.startsWith(HEADING)) {
    shown = shown.slice(HEADING.length).replace(/^\s+/, "");
  } else if (HEADING.startsWith(shown)) {
    shown = "";
  }
  text.textContent = shown;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = qEl.value.trim();
  if (!question) return;
  qEl.value = "";
  addMsg("user", question);
  const bot = addMsg("bot", "");
  const tools = document.createElement("div");
  tools.className = "tools";
  const meta = document.createElement("div");
  meta.className = "tools-meta";
  meta.textContent = "第 0 轮 · 0.0s";
  tools.appendChild(meta);
  bot.appendChild(tools);
  const body = document.createElement("div");
  bot.appendChild(body);
  sendBtn.disabled = true;
  const t0 = performance.now();
  let lastRound = 0;
  const setStatus = (text) => {
    const elapsed = fmtSec(performance.now() - t0);
    statusEl.textContent = `${text} · ${elapsed}`;
    meta.textContent = `第 ${lastRound} 轮 · ${elapsed}`;
  };
  statusEl.textContent = "检索中…";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    await readSse(res, (eventName, data) => {
      const elapsedLabel = data.elapsed_ms != null ? fmtSec(data.elapsed_ms) : fmtSec(performance.now() - t0);
      if (data.round) lastRound = data.round;
      if (eventName === "route_start") {
        setStatus("判断问题方向");
        const row = document.createElement("div");
        row.className = "route";
        row.textContent = `${elapsedLabel} 正在根据目录判断问题方向与拟引用章节…`;
        tools.appendChild(row);
      } else if (eventName === "route") {
        const row = document.createElement("div");
        row.className = "route";
        const cands = (data.candidates || [])
          .map((c) => `${c.id} ${c.title || ""}`.trim())
          .join("；");
        const unans = data.maybe_unanswerable ? "（目录可能无专门规定）" : "";
        row.textContent = `${elapsedLabel} 方向：${data.direction || "未判定"}${unans}${cands ? `。拟引用：${cands}` : ""}`;
        tools.appendChild(row);
        setStatus("已圈定章节");
      } else if (eventName === "round_start") {
        lastRound = data.round || lastRound;
        setStatus(data.force_answer ? "作答中" : `第${lastRound}轮`);
      } else if (eventName === "answer_start") {
        ensureAnswer(body);
        setStatus("作答中");
      } else if (eventName === "token") {
        appendAnswer(body, data.text || "");
      } else if (eventName === "tool_call") {
        const row = document.createElement("div");
        row.textContent = `第${data.round || lastRound}轮 ${elapsedLabel} 调用 ${data.name} ${JSON.stringify(data.arguments || {})}`;
        tools.appendChild(row);
        setStatus(`第${data.round || lastRound}轮 · ${data.name}`);
      } else if (eventName === "tool_result") {
        const row = document.createElement("div");
        row.textContent = `第${data.round || lastRound}轮 ${elapsedLabel} 返回 ${data.summary || data.name}`;
        tools.appendChild(row);
      } else if (eventName === "error") {
        const target = body._answerText || body;
        target.textContent += `\n[错误] ${data.message || ""}`;
      } else if (eventName === "done") {
        lastRound = data.rounds || lastRound;
        const spent = data.elapsed_ms != null ? fmtSec(data.elapsed_ms) : fmtSec(performance.now() - t0);
        statusEl.textContent = `完成 · ${data.rounds || 0}轮 · ${data.tool_calls || 0}次工具 · ${spent}`;
        meta.textContent = `共 ${data.rounds || 0} 轮 · ${data.tool_calls || 0} 次工具 · ${spent}`;
      }
      logEl.scrollTop = logEl.scrollHeight;
    });
  } catch (err) {
    body.textContent += `\n[网络错误] ${err.message}`;
  } finally {
    sendBtn.disabled = false;
    if (statusEl.textContent.startsWith("检索中")) statusEl.textContent = "空闲";
  }
});

pdfInput.addEventListener("change", async () => {
  const file = pdfInput.files && pdfInput.files[0];
  pdfInput.value = "";
  if (!file) return;
  ingestStatusEl.textContent = `正在添加 ${file.name}…`;
  pdfInput.disabled = true;
  try {
    const fd = new FormData();
    fd.append("file", file, file.name);
    const res = await fetch("/api/ingest", { method: "POST", body: fd });
    await readSse(res, (eventName, data) => {
      if (eventName === "progress") {
        ingestStatusEl.textContent = data.message || data.stage || "处理中…";
      } else if (eventName === "done") {
        ingestStatusEl.textContent = `已加入《${data.title || file.name}》· ${data.clauses || 0} 条，可提问`;
        refreshFiles();
      } else if (eventName === "error") {
        ingestStatusEl.textContent = `添加失败：${data.message || ""}`;
      }
    });
  } catch (err) {
    ingestStatusEl.textContent = `添加失败：${err.message}`;
  } finally {
    pdfInput.disabled = false;
  }
});
