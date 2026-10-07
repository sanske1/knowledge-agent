/**
 * 系统管理模块：数据源配置 / 索引管理 / 服务监控 / 基础配置
 */
const SystemModule = {
  currentTab: "datasource",

  render(container) {
    container.innerHTML = `
      <div class="sys-tabs">
        <div class="sys-tab active" data-tab="datasource">数据源配置</div>
        <div class="sys-tab" data-tab="mcp">MCP 管理</div>
        <div class="sys-tab" data-tab="index">索引管理</div>
        <div class="sys-tab" data-tab="monitor">服务与接口监控</div>
        <div class="sys-tab" data-tab="config">基础配置</div>
      </div>
      <div id="sys-content"></div>
    `;
    container.querySelectorAll(".sys-tab").forEach(t => {
      t.onclick = () => {
        container.querySelectorAll(".sys-tab").forEach(x => x.classList.remove("active"));
        t.classList.add("active");
        this.currentTab = t.dataset.tab;
        this.loadTab();
      };
    });
    this.loadTab();
  },

  loadTab() {
    if (this.currentTab === "datasource") this.renderDatasource();
    else if (this.currentTab === "mcp") this.renderMCP();
    else if (this.currentTab === "index") this.renderIndex();
    else if (this.currentTab === "monitor") this.renderMonitor();
    else if (this.currentTab === "config") this.renderConfig();
  },

  // ========== 数据源配置 ==========
  async renderDatasource() {
    const content = document.getElementById("sys-content");
    content.innerHTML = `
      <div class="card">
        <div class="card-title"><span>MySQL 配置</span><button class="btn btn-primary btn-sm" id="test-mysql-btn">测试连接</button></div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">主机地址</label><input class="form-control" id="mysql-host" /></div>
          <div class="form-group"><label class="form-label">端口</label><input class="form-control" id="mysql-port" type="number" /></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">用户名</label><input class="form-control" id="mysql-user" /></div>
          <div class="form-group"><label class="form-label">密码</label><input class="form-control" id="mysql-password" type="password" /></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">数据库名</label><input class="form-control" id="mysql-database" /></div>
          <div class="form-group"><label class="form-label">字符集</label><input class="form-control" value="utf8mb4" disabled /></div>
        </div>
        <div id="mysql-test-result"></div>
        <div style="margin-top:12px"><button class="btn btn-success" id="save-mysql-btn">保存配置</button></div>
      </div>
      <div class="card">
        <div class="card-title"><span>Redis 配置</span><button class="btn btn-primary btn-sm" id="test-redis-btn">测试连接</button></div>
        <div class="form-group"><label class="form-label">连接 URL</label><input class="form-control" id="redis-url" /></div>
        <div class="form-group"><label class="form-label">向量索引前缀</label><input class="form-control" value="deal_files_chunks_{project_id}" disabled /></div>
        <div id="redis-test-result"></div>
        <div style="margin-top:12px"><button class="btn btn-success" id="save-redis-btn">保存配置</button></div>
      </div>
    `;

    // 加载当前配置
    try {
      const res = await API.configGet();
      const c = res.data;
      document.getElementById("mysql-host").value = c.mysql.host;
      document.getElementById("mysql-port").value = c.mysql.port;
      document.getElementById("mysql-user").value = c.mysql.user;
      document.getElementById("mysql-password").value = "";
      document.getElementById("mysql-database").value = c.mysql.database;
      document.getElementById("redis-url").value = c.redis.url;
    } catch (e) { /* 静默 */ }

    document.getElementById("test-mysql-btn").onclick = () => this.testMySQL();
    document.getElementById("test-redis-btn").onclick = () => this.testRedis();
    document.getElementById("save-mysql-btn").onclick = () => this.saveConfig();
    document.getElementById("save-redis-btn").onclick = () => this.saveConfig();
  },

  async testMySQL() {
    const box = document.getElementById("mysql-test-result");
    box.innerHTML = "<span class='tag tag-yellow'>测试中...</span>";
    const data = {
      host: document.getElementById("mysql-host").value,
      port: parseInt(document.getElementById("mysql-port").value),
      user: document.getElementById("mysql-user").value,
      password: document.getElementById("mysql-password").value || undefined,
      database: document.getElementById("mysql-database").value,
    };
    try {
      const res = await API.testMySQL(data);
      const d = res.data;
      if (d.connected) {
        box.innerHTML = `<span class="tag tag-green">连接成功</span> 版本: ${d.version} | 表数量: ${d.table_count} | 表: ${(d.tables || []).join(", ")}`;
      } else {
        box.innerHTML = `<span class="tag tag-red">连接失败</span> ${escapeHtml(d.error || "")}`;
      }
    } catch (e) { box.innerHTML = `<span class="tag tag-red">测试失败</span>`; }
  },

  async testRedis() {
    const box = document.getElementById("redis-test-result");
    box.innerHTML = "<span class='tag tag-yellow'>测试中...</span>";
    const data = { url: document.getElementById("redis-url").value };
    try {
      const res = await API.testRedis(data);
      const d = res.data;
      if (d.connected) {
        box.innerHTML = `<span class="tag tag-green">连接成功</span> 版本: ${d.redis_version} | 已用内存: ${d.used_memory_human} | Key总量: ${d.total_keys}`;
      } else {
        box.innerHTML = `<span class="tag tag-red">连接失败</span> ${escapeHtml(d.error || "")}`;
      }
    } catch (e) { box.innerHTML = `<span class="tag tag-red">测试失败</span>`; }
  },

  async saveConfig() {
    const data = {
      mysql_host: document.getElementById("mysql-host").value,
      mysql_port: parseInt(document.getElementById("mysql-port").value),
      mysql_user: document.getElementById("mysql-user").value,
      mysql_database: document.getElementById("mysql-database").value,
      redis_url: document.getElementById("redis-url").value,
    };
    const pwd = document.getElementById("mysql-password").value;
    if (pwd) data.mysql_password = pwd;
    try {
      await API.configSave(data);
      toast("配置已保存（需重启服务生效）", "success");
    } catch (e) { /* 已 toast */ }
  },

  // ========== MCP 管理 ==========
  async renderMCP() {
    const content = document.getElementById("sys-content");
    content.innerHTML = `
      <div class="card">
        <div class="card-title">添加 MCP 服务连接</div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">服务名称</label><input class="form-control" id="mcp-name" placeholder="如 my_mcp" /></div>
          <div class="form-group"><label class="form-label">传输方式</label>
            <select class="form-control" id="mcp-transport">
              <option value="http">HTTP/SSE</option>
              <option value="streamable-http">Streamable HTTP</option>
              <option value="stdio">Stdio</option>
            </select>
          </div>
        </div>
        <div class="form-group"><label class="form-label">服务地址 (URL)</label><input class="form-control" id="mcp-url" placeholder="http://127.0.0.1:8889/mcp" /></div>
        <div style="margin-top:12px"><button class="btn btn-success" id="mcp-add-btn">添加连接</button></div>
      </div>
      <div class="card">
        <div class="card-title">已连接的 MCP 服务</div>
        <div id="mcp-list">加载中...</div>
      </div>
      <div class="card">
        <div class="card-title">MCP 工具列表</div>
        <div id="mcp-tools-list">加载中...</div>
      </div>
    `;
    document.getElementById("mcp-add-btn").onclick = () => this.addMCP();
    this.loadMCPList();
    this.loadMCPToolsList();
  },

  async addMCP() {
    const name = document.getElementById("mcp-name").value.trim();
    const url = document.getElementById("mcp-url").value.trim();
    const transport = document.getElementById("mcp-transport").value;
    if (!name || !url) { toast("请填写名称和地址", "error"); return; }
    try {
      await API.mcpAdd({ name, url, transport });
      toast("MCP 连接已添加", "success");
      document.getElementById("mcp-name").value = "";
      document.getElementById("mcp-url").value = "";
      this.loadMCPList();
    } catch (e) { /* toast 已处理 */ }
  },

  async loadMCPList() {
    const box = document.getElementById("mcp-list");
    try {
      const res = await API.mcpList();
      const data = res.data;
      const names = Object.keys(data);
      if (names.length === 0) {
        box.innerHTML = `<span style="color:var(--text-2)">暂无 MCP 连接，请在上方添加</span>`;
        document.getElementById("mcp-tools-list").innerHTML = `<span style="color:var(--text-2)">暂无 MCP 连接</span>`;
        return;
      }
      box.innerHTML = names.map(name => {
        const cfg = data[name];
        const enabled = cfg.enabled !== false;  // 兼容旧数据（无 enabled 字段视为启用）
        const statusTag = enabled
          ? `<span class="tag tag-green">已启用</span>`
          : `<span class="tag tag-red">已停用</span>`;
        const toggleBtn = enabled
          ? `<button class="btn btn-warning btn-sm" data-action="toggle" data-name="${escapeHtml(name)}" data-enabled="false">停用</button>`
          : `<button class="btn btn-success btn-sm" data-action="toggle" data-name="${escapeHtml(name)}" data-enabled="true">启用</button>`;
        return `
          <div style="display:flex;align-items:center;justify-content:space-between;padding:10px;border-bottom:1px solid var(--border);opacity:${enabled ? 1 : 0.6}">
            <div style="flex:1;min-width:0">
              <strong>${escapeHtml(name)}</strong>
              ${statusTag}
              <span class="tag tag-blue">${escapeHtml(cfg.transport)}</span>
              <div style="font-size:12px;color:var(--text-2);margin-top:2px">${escapeHtml(cfg.url)}</div>
            </div>
            <div style="display:flex;gap:6px;flex-shrink:0">
              ${toggleBtn}
              <button class="btn btn-danger btn-sm" data-action="delete" data-name="${escapeHtml(name)}">删除</button>
            </div>
          </div>
        `;
      }).join("");
      box.querySelectorAll("button[data-action='delete']").forEach(btn => {
        btn.onclick = () => this.deleteMCP(btn.dataset.name);
      });
      box.querySelectorAll("button[data-action='toggle']").forEach(btn => {
        btn.onclick = () => this.toggleMCP(btn.dataset.name, btn.dataset.enabled === "true");
      });
    } catch (e) { box.textContent = "加载失败"; }
  },

  async toggleMCP(name, enabled) {
    try {
      const res = await API.mcpToggle(name, enabled);
      toast(res.message || (enabled ? "已启用" : "已停用"), enabled ? "success" : "info");
      this.loadMCPList();
      this.loadMCPToolsList();
    } catch (e) { /* toast 已处理 */ }
  },

  async deleteMCP(name) {
    confirmDialog("删除 MCP 连接", `确定删除 MCP 服务 "${name}" 吗？`, async () => {
      try {
        await API.mcpDelete(name);
        toast("已删除", "success");
        this.loadMCPList();
        this.loadMCPToolsList();
      } catch (e) { /* toast 已处理 */ }
    });
  },

  async loadMCPToolsList() {
    const box = document.getElementById("mcp-tools-list");
    if (!box) return;
    try {
      const res = await API.statusMCPTools();
      const d = res.data;
      if (!d.tools || d.tools.length === 0) {
        box.innerHTML = `<span style="color:var(--text-2)">暂无可用工具${d.error ? "（" + escapeHtml(d.error) + "）" : ""}</span>`;
        return;
      }
      box.innerHTML = `
        <div style="margin-bottom:10px">共 <strong>${d.count}</strong> 个工具</div>
        <div class="tool-grid">
          ${d.tools.map(t => `
            <div class="tool-card">
              <span class="tool-status-dot ${t.status === 'ok' ? 'ok' : 'error'}"></span>
              <div>
                <div style="font-weight:600;font-size:13px">${escapeHtml(t.name)}</div>
                <div style="font-size:11px;color:var(--text-2)">${escapeHtml(t.description || "")}</div>
                ${t.source ? `<div style="font-size:10px;color:var(--text-3)">来源: ${escapeHtml(t.source)}</div>` : ""}
              </div>
            </div>
          `).join("")}
        </div>
      `;
    } catch (e) { box.innerHTML = `<span style="color:var(--text-2)">加载失败</span>`; }
  },

  // ========== 索引管理 ==========
  renderIndex() {
    const content = document.getElementById("sys-content");
    content.innerHTML = `
      <div class="card">
        <div class="card-title">核心操作</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <button class="btn btn-primary" id="rebuild-btn">🔄 重建索引（MySQL → Redis）</button>
          <button class="btn btn-warning" id="import-btn">📥 灾备导入（磁盘 → MySQL）</button>
          <button class="btn btn-default" id="validate-btn">✅ 索引校验</button>
        </div>
        <div id="index-action-result" style="margin-top:12px"></div>
      </div>
      <div class="card">
        <div class="card-title">索引数据统计</div>
        <div id="index-stats">加载中...</div>
      </div>
    `;
    document.getElementById("rebuild-btn").onclick = () => {
      confirmDialog("重建索引", "将从 MySQL 分片全量重建 Redis 向量库，确定继续？", () => this.runIndexAction("rebuild"));
    };
    document.getElementById("import-btn").onclick = () => {
      confirmDialog("灾备导入", "将从磁盘 .meta.json 导入数据到 MySQL 和 Redis，确定继续？", () => this.runIndexAction("import"));
    };
    document.getElementById("validate-btn").onclick = () => this.runIndexAction("validate");
    this.loadIndexStats();
  },

  async runIndexAction(type) {
    const box = document.getElementById("index-action-result");
    box.innerHTML = "<span class='tag tag-yellow'>执行中...</span>";
    try {
      let res;
      if (type === "rebuild") res = await API.indexRebuild();
      else if (type === "import") res = await API.indexImport();
      else res = await API.indexValidate();
      box.innerHTML = `<pre style="background:#f9fafb;padding:10px;border-radius:6px;font-size:12px;overflow:auto">${escapeHtml(JSON.stringify(res.data, null, 2))}</pre>`;
      toast("操作完成", "success");
      this.loadIndexStats();
    } catch (e) { box.innerHTML = `<span class="tag tag-red">执行失败</span>`; }
  },

  async loadIndexStats() {
    try {
      const res = await API.indexStats();
      const d = res.data;
      document.getElementById("index-stats").innerHTML = `
        <div class="stat-grid">
          <div class="stat-card"><div class="stat-value">${d.project_count}</div><div class="stat-label">项目数</div></div>
          <div class="stat-card"><div class="stat-value">${d.file_count}</div><div class="stat-label">文件数</div></div>
          <div class="stat-card"><div class="stat-value">${d.chunk_count}</div><div class="stat-label">分片数</div></div>
          <div class="stat-card"><div class="stat-value">${d.redis.total_vectors || 0}</div><div class="stat-label">Redis向量数</div></div>
        </div>
      `;
    } catch (e) { document.getElementById("index-stats").textContent = "加载失败"; }
  },

  // ========== 服务与接口监控 ==========
  async renderMonitor() {
    const content = document.getElementById("sys-content");
    content.innerHTML = `
      <div class="card">
        <div class="card-title">数据源心跳</div>
        <div id="service-heartbeat">加载中...</div>
      </div>
      <div class="card">
        <div class="card-title">MCP 工具可用性</div>
        <div id="mcp-tools">加载中...</div>
      </div>
    `;
    this.loadHeartbeat();
    this.loadMCPTools();
  },

  async loadHeartbeat() {
    try {
      const res = await API.statusServices();
      const d = res.data;
      const html = (name, info) => `
        <div style="display:flex;align-items:center;gap:10px;padding:8px 0">
          <span class="dot" style="width:10px;height:10px;border-radius:50%;background:${info.status === 'ok' ? 'var(--success)' : 'var(--danger)'}"></span>
          <strong>${name}</strong>
          <span class="tag ${info.status === 'ok' ? 'tag-green' : 'tag-red'}">${info.status}</span>
          ${info.error ? `<span style="color:var(--text-2);font-size:12px">${escapeHtml(info.error)}</span>` : ""}
        </div>
      `;
      document.getElementById("service-heartbeat").innerHTML =
        html("MySQL", d.mysql) + html("Redis", d.redis) + html("MCP", d.mcp);
    } catch (e) { document.getElementById("service-heartbeat").textContent = "加载失败"; }
  },

  async loadMCPTools() {
    try {
      const res = await API.statusMCPTools();
      const d = res.data;
      const box = document.getElementById("mcp-tools");
      if (!d.tools || d.tools.length === 0) {
        box.innerHTML = `<span class="tag tag-red">MCP 服务不可用</span> ${escapeHtml(d.error || "")}`;
        return;
      }
      box.innerHTML = `
        <div style="margin-bottom:10px">共 <strong>${d.count}</strong> 个工具可用</div>
        <div class="tool-grid">
          ${d.tools.map(t => `
            <div class="tool-card">
              <span class="tool-status-dot ${t.status === 'ok' ? 'ok' : 'error'}"></span>
              <div>
                <div style="font-weight:600;font-size:13px">${escapeHtml(t.name)}</div>
                <div style="font-size:11px;color:var(--text-2)">${escapeHtml(t.description || "")}</div>
              </div>
            </div>
          `).join("")}
        </div>
      `;
    } catch (e) { document.getElementById("mcp-tools").textContent = "加载失败"; }
  },

  // ========== 基础配置 ==========
  async renderConfig() {
    const content = document.getElementById("sys-content");
    content.innerHTML = `
      <div class="card">
        <div class="card-title">存储路径配置</div>
        <div class="form-group"><label class="form-label">未处理区路径</label><input class="form-control" id="cfg-inbox" /></div>
        <div class="form-group"><label class="form-label">已处理区路径</label><input class="form-control" id="cfg-archived" /></div>
      </div>
      <div class="card">
        <div class="card-title">服务端口配置</div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">WebAPI 端口</label><input class="form-control" id="cfg-webapi-port" type="number" /></div>
          <div class="form-group"><label class="form-label">MCP 服务端口</label><input class="form-control" id="cfg-mcp-port" type="number" /></div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">全局参数</div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">归档重试次数</label><input class="form-control" id="cfg-retry" type="number" /></div>
          <div class="form-group"><label class="form-label">默认分片大小(字符)</label><input class="form-control" id="cfg-chunk" type="number" /></div>
          <div class="form-group"><label class="form-label">默认 TopK</label><input class="form-control" id="cfg-topk" type="number" /></div>
        </div>
      </div>
      <div style="display:flex;gap:10px">
        <button class="btn btn-primary" id="save-cfg-btn">保存配置</button>
        <button class="btn btn-default" id="reset-cfg-btn">恢复默认</button>
      </div>
    `;

    try {
      const res = await API.configGet();
      const c = res.data;
      document.getElementById("cfg-inbox").value = c.folders.inbox;
      document.getElementById("cfg-archived").value = c.folders.archived;
      document.getElementById("cfg-webapi-port").value = c.params.webapi_port;
      document.getElementById("cfg-mcp-port").value = c.params.mcp_port;
      document.getElementById("cfg-retry").value = c.params.archive_retry;
      document.getElementById("cfg-chunk").value = c.params.chunk_max_chars;
      document.getElementById("cfg-topk").value = c.params.default_topk;
    } catch (e) { /* 静默 */ }

    document.getElementById("save-cfg-btn").onclick = async () => {
      const data = {
        inbox_dir: document.getElementById("cfg-inbox").value,
        archived_dir: document.getElementById("cfg-archived").value,
        webapi_port: parseInt(document.getElementById("cfg-webapi-port").value),
        mcp_port: parseInt(document.getElementById("cfg-mcp-port").value),
        archive_retry: parseInt(document.getElementById("cfg-retry").value),
        chunk_max_chars: parseInt(document.getElementById("cfg-chunk").value),
        default_topk: parseInt(document.getElementById("cfg-topk").value),
      };
      try {
        await API.configSave(data);
        toast("配置已保存", "success");
      } catch (e) { /* 已 toast */ }
    };
    document.getElementById("reset-cfg-btn").onclick = () => {
      confirmDialog("恢复默认", "确定要恢复默认配置吗？", async () => {
        // 清空 runtime_config
        try {
          await fetch("/api/config/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
          toast("已恢复默认配置（需重启生效）", "success");
          this.renderConfig();
        } catch (e) { toast("恢复失败", "error"); }
      });
    };
  },
};
