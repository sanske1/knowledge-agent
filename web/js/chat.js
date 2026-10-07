/**
 * 智能对话模块
 */
// 配置 marked：启用换行、代码高亮等
if (typeof marked !== "undefined") {
  marked.setOptions({
    breaks: true,        // 单个 \n 也转为 <br>
    gfm: true,           // GitHub 风格 Markdown
  });
}

/** 将 Markdown 文本渲染为安全的 HTML */
function renderMarkdown(text) {
  if (!text) return "";
  try {
    const html = marked.parse(text);
    return DOMPurify.sanitize(html, { ADD_ATTR: ["target", "rel"] });
  } catch (e) {
    return escapeHtml(text).replace(/\n/g, "<br>");
  }
}

const ChatModule = {
  sessions: [],
  currentSessionId: null,
  messages: [],
  isLoading: false,

  render(container) {
    container.innerHTML = `
      <div class="chat-layout">
        <div class="chat-sessions">
          <div class="chat-sessions-header">
            <strong>会话列表</strong>
            <button class="btn btn-primary btn-sm" id="new-session-btn">+ 新建</button>
          </div>
          <div class="session-list" id="session-list"></div>
        </div>
        <div class="chat-main">
          <div class="chat-messages" id="chat-messages"></div>
          <div class="chat-input-area">
            <textarea class="chat-input" id="chat-input" placeholder="输入消息，回车发送，Shift+Enter 换行..."></textarea>
            <div class="chat-input-actions">
              <div>
                <button class="btn btn-default btn-sm" id="clear-ctx-btn">清空上下文</button>
              </div>
              <button class="btn btn-primary" id="send-btn">发送</button>
            </div>
          </div>
        </div>
        <div class="chat-tools">
          <div class="card-title">工具调用记录</div>
          <div id="tool-calls-list"><p style="color:var(--text-2);font-size:12px">暂无工具调用</p></div>
        </div>
      </div>
    `;

    this.bindEvents();
    this.loadSessions();
  },

  bindEvents() {
    document.getElementById("new-session-btn").onclick = () => this.newSession();
    document.getElementById("send-btn").onclick = () => this.sendMessage();
    document.getElementById("clear-ctx-btn").onclick = () => this.clearContext();
    const input = document.getElementById("chat-input");
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.sendMessage(); }
    });
  },

  async loadSessions() {
    try {
      const res = await API.chatSessions();
      this.sessions = res.data || [];
      this.renderSessions();
    } catch (e) { /* 静默 */ }
  },

  renderSessions() {
    const list = document.getElementById("session-list");
    if (this.sessions.length === 0) {
      list.innerHTML = "<div style='padding:12px;color:var(--text-2);font-size:12px'>暂无会话</div>";
      return;
    }
    list.innerHTML = this.sessions.map(s => `
      <div class="session-item ${s.session_id === this.currentSessionId ? "active" : ""}" data-id="${s.session_id}">
        <div class="session-info" style="flex:1;min-width:0">
          <div class="session-title">${escapeHtml(s.title)}</div>
          <div class="session-meta">${s.message_count} 条消息</div>
        </div>
        <button class="btn btn-danger btn-sm session-delete-btn" data-id="${s.session_id}" title="删除会话">删除</button>
      </div>
    `).join("");
    list.querySelectorAll(".session-item").forEach(el => {
      el.onclick = () => this.selectSession(el.dataset.id);
    });
    list.querySelectorAll(".session-delete-btn").forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        this.deleteSession(btn.dataset.id);
      };
    });
  },

  async deleteSession(sid) {
    const session = this.sessions.find(s => s.session_id === sid);
    const title = session ? session.title : "该会话";
    confirmDialog("删除会话", `确定要删除会话「${title}」吗？此操作不可恢复。`, async () => {
      try {
        await API.chatDeleteSession(sid);
        toast("会话已删除", "success");
        if (this.currentSessionId === sid) {
          this.currentSessionId = null;
          this.messages = [];
          this.renderMessages();
        }
        await this.loadSessions();
      } catch (e) { /* toast 已处理 */ }
    });
  },

  async selectSession(sid) {
    this.currentSessionId = sid;
    this.renderSessions();
    try {
      const res = await API.chatMessages(sid);
      this.messages = res.data || [];
      this.renderMessages();
    } catch (e) { this.messages = []; this.renderMessages(); }
  },

  newSession() {
    this.currentSessionId = null;
    this.messages = [];
    this.renderMessages();
    this.renderSessions();
  },

  clearContext() {
    confirmDialog("清空上下文", "确定要清空当前会话的上下文吗？", () => {
      this.messages = [];
      this.renderMessages();
      toast("上下文已清空", "success");
    });
  },

  renderMessages() {
    const box = document.getElementById("chat-messages");
    if (this.messages.length === 0) {
      box.innerHTML = "<div style='text-align:center;color:var(--text-2);padding:40px'>开始对话吧～</div>";
      return;
    }
    box.innerHTML = this.messages.map(m => {
      if (m.role === "user") {
        return `<div class="msg user"><div class="msg-avatar">我</div><div class="msg-bubble">${escapeHtml(m.content).replace(/\n/g, "<br>")}</div></div>`;
      } else {
        const tools = (m.tool_calls || []).length > 0 ? `
          <div class="msg-tool">
            ${(m.tool_calls || []).map(tc => `
              <div><strong>${escapeHtml(tc.name)}</strong> <span class="tag tag-green">${tc.status}</span></div>
              <div style="font-size:11px;color:var(--text-2);word-break:break-all">${escapeHtml(JSON.stringify(tc.args))}</div>
            `).join("")}
          </div>
        ` : "";
        const contentHtml = m.content ? renderMarkdown(m.content) : "<em style='color:var(--text-2)'>(无文本回复)</em>";
        return `<div class="msg assistant"><div class="msg-avatar">AI</div><div class="msg-bubble markdown-body">${contentHtml}${tools}</div></div>`;
      }
    }).join("");
    box.scrollTop = box.scrollHeight;
  },

  async sendMessage() {
    const input = document.getElementById("chat-input");
    const msg = input.value.trim();
    if (!msg || this.isLoading) return;

    this.isLoading = true;
    document.getElementById("send-btn").disabled = true;
    input.value = "";

    // 乐观渲染用户消息
    this.messages.push({ role: "user", content: msg });
    this.renderMessages();

    try {
      const res = await API.chatSend(msg, this.currentSessionId);
      this.currentSessionId = res.session_id;
      this.messages.push({ role: "assistant", content: res.message, tool_calls: res.tool_calls });
      this.renderMessages();
      this.renderToolCalls(res.tool_calls || []);
      await this.loadSessions();
    } catch (e) {
      this.messages.push({ role: "assistant", content: "请求失败：" + e.message });
      this.renderMessages();
    } finally {
      this.isLoading = false;
      document.getElementById("send-btn").disabled = false;
      input.focus();
    }
  },

  renderToolCalls(calls) {
    const box = document.getElementById("tool-calls-list");
    if (calls.length === 0) { box.innerHTML = "<p style='color:var(--text-2);font-size:12px'>本轮无工具调用</p>"; return; }
    box.innerHTML = calls.map(tc => `
      <div class="tool-call-item">
        <div>
          <span class="tool-call-name">${escapeHtml(tc.name)}</span>
          <span class="tool-call-status tag ${tc.status === 'success' ? 'tag-green' : 'tag-red'}">${tc.status}</span>
        </div>
        <div class="tool-call-args">入参: ${escapeHtml(JSON.stringify(tc.args))}</div>
        ${tc.result ? `<div class="tool-call-args">返回: ${escapeHtml(tc.result)}</div>` : ""}
      </div>
    `).join("");
  },
};
