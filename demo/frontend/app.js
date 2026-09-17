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

samples.forEach((t) => {
  const li = document.createElement("li");
  li.textContent = t;
  li.onclick = () => {
    qEl.value = t;
    form.requestSubmit();
  };
  samplesEl.appendChild(li);
});

fetch("/api/health")
  .then((r) => r.json())
  .then((d) => {
    healthEl.textContent = `知识库 ${d.files} 份文件 / ${d.clauses} 条条款`;
  })
  .catch(() => {
    healthEl.textContent = "后端未连接";
  });

function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  logEl.appendChild(div);
  logEl.scrollTop = logEl.scrollHeight;
  return div;
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
  bot.appendChild(tools);
  const body = document.createElement("div");
  bot.appendChild(body);
  sendBtn.disabled = true;
  statusEl.textContent = "检索中…";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let eventName = "message";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop();
      for (const block of parts) {
        let dataLine = "";
        eventName = "message";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          if (line.startsWith("data:")) dataLine += line.slice(5).trim();
        }
        if (!dataLine) continue;
        const data = JSON.parse(dataLine);
        if (eventName === "token") {
          body.textContent += data.text || "";
        } else if (eventName === "tool_call") {
          const row = document.createElement("div");
          row.textContent = `调用 ${data.name} ${JSON.stringify(data.arguments || {})}`;
          tools.appendChild(row);
          statusEl.textContent = `工具 ${data.name}`;
        } else if (eventName === "tool_result") {
          const row = document.createElement("div");
          row.textContent = `返回 ${data.summary || data.name}`;
          tools.appendChild(row);
        } else if (eventName === "error") {
          body.textContent += `\n[错误] ${data.message || ""}`;
        } else if (eventName === "done") {
          statusEl.textContent = `完成 · ${data.tool_calls || 0} 次工具`;
        }
        logEl.scrollTop = logEl.scrollHeight;
      }
    }
  } catch (err) {
    body.textContent += `\n[网络错误] ${err.message}`;
  } finally {
    sendBtn.disabled = false;
    if (statusEl.textContent === "检索中…") statusEl.textContent = "空闲";
  }
});
