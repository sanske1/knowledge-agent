/**
 * API 封装层 —— 统一处理请求、错误与鉴权
 */
const API = {
  base: "",

  async request(method, path, body, options = {}) {
    const headers = { "Accept": "application/json" };
    if (body && !(body instanceof FormData)) headers["Content-Type"] = "application/json";
    const opts = { method, headers, ...options };
    if (body instanceof FormData) opts.body = body;
    else if (body) opts.body = JSON.stringify(body);

    try {
      const resp = await fetch(this.base + path, opts);
      const text = await resp.text();
      let data;
      try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
      if (!resp.ok) {
        const msg = (data && data.detail) || data.error || `HTTP ${resp.status}`;
        throw new Error(msg);
      }
      return data;
    } catch (e) {
      toast(e.message, "error");
      throw e;
    }
  },

  // ===== 入库 =====
  async ingestProcess() { return this.request("POST", "/api/ingest/process"); },
  async ingestUpload(files, project = null) {
    const fd = new FormData();
    files.forEach(f => fd.append("files", f));
    if (project) fd.append("project", project);
    return this.request("POST", "/api/ingest/upload", fd);
  },
  async inboxFiles() { return this.request("GET", "/api/inbox/files"); },

  // ===== 索引 =====
  async indexRebuild() { return this.request("POST", "/api/index/rebuild"); },
  async indexImport() { return this.request("POST", "/api/index/import"); },
  async indexValidate() { return this.request("GET", "/api/index/validate"); },
  async indexStats() { return this.request("GET", "/api/index/stats"); },

  // ===== 检索 =====
  async search(q, top_k = 5, project = null) {
    const params = new URLSearchParams({ q, top_k });
    if (project) params.set("project", project);
    return this.request("GET", `/api/search?${params}`);
  },
  async searchTool(q, top_k = 5) {
    const params = new URLSearchParams({ q, top_k });
    return this.request("GET", `/api/search/tool?${params}`);
  },

  // ===== 失败文件 =====
  async failedList() { return this.request("GET", "/api/failed"); },
  async failedRetry() { return this.request("POST", "/api/failed/retry"); },

  // ===== 项目/文件浏览 =====
  async projects() { return this.request("GET", "/api/projects"); },
  async projectFiles(pid) { return this.request("GET", `/api/projects/${pid}/files`); },
  async fileChunks(fid) { return this.request("GET", `/api/files/${fid}/chunks`); },
  async fileMeta(fid) { return this.request("GET", `/api/files/${fid}/meta`); },

  // ===== 对话 =====
  async chatSessions() { return this.request("GET", "/api/chat/sessions"); },
  async chatDeleteSession(sid) { return this.request("DELETE", `/api/chat/sessions/${sid}`); },
  async chatMessages(sid) { return this.request("GET", `/api/chat/sessions/${sid}/messages`); },
  async chatSend(message, session_id = null) {
    return this.request("POST", "/api/chat/send", { message, session_id });
  },

  // ===== 配置 =====
  async configGet() { return this.request("GET", "/api/config"); },
  async configSave(data) { return this.request("POST", "/api/config/save", data); },
  async testMySQL(data = {}) { return this.request("POST", "/api/config/test_mysql", data); },
  async testRedis(data = {}) { return this.request("POST", "/api/config/test_redis", data); },

  // ===== 状态 =====
  async statusServices() { return this.request("GET", "/api/status/services"); },
  async statusMCPTools() { return this.request("GET", "/api/status/mcp_tools"); },
  async folders() { return this.request("GET", "/api/folders"); },

  // ===== MCP 连接管理 =====
  async mcpAdd(data) { return this.request("POST", "/api/mcp/add", data); },
  async mcpList() { return this.request("GET", "/api/mcp/list"); },
  async mcpDelete(name) { return this.request("DELETE", `/api/mcp/${encodeURIComponent(name)}`); },
  async mcpToggle(name, enabled) { return this.request("POST", `/api/mcp/${encodeURIComponent(name)}/toggle`, { enabled }); },
};

// ==================== Toast 通知 ====================
function toast(msg, type = "info") {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; setTimeout(() => el.remove(), 300); }, 2800);
}

// ==================== 确认弹窗 ====================
function confirmDialog(title, body, onConfirm) {
  const overlay = document.getElementById("modal-overlay");
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").textContent = body;
  overlay.classList.remove("hidden");
  const confirmBtn = document.getElementById("modal-confirm");
  const cancelBtn = document.getElementById("modal-cancel");
  const cleanup = () => { overlay.classList.add("hidden"); confirmBtn.onclick = null; cancelBtn.onclick = null; };
  confirmBtn.onclick = () => { cleanup(); onConfirm(); };
  cancelBtn.onclick = cleanup;
}

// ==================== 工具函数 ====================
function fmtSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 / 1024).toFixed(2) + " MB";
}
function fmtTime(ts) {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  return d.toLocaleString("zh-CN", { hour12: false });
}
function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s ?? "";
  return div.innerHTML;
}
