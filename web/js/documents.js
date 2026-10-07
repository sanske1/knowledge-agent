/**
 * 文档中心模块：未处理区 / 已处理区 / 入库流程监控
 */
const DocumentsModule = {
  currentTab: "inbox",
  currentProjectId: null,

  render(container) {
    container.innerHTML = `
      <div class="doc-tabs">
        <div class="doc-tab active" data-tab="inbox">未处理区</div>
        <div class="doc-tab" data-tab="archived">已处理区</div>
        <div class="doc-tab" data-tab="flow">入库流程监控</div>
      </div>
      <div id="doc-content"></div>
    `;
    container.querySelectorAll(".doc-tab").forEach(t => {
      t.onclick = () => {
        container.querySelectorAll(".doc-tab").forEach(x => x.classList.remove("active"));
        t.classList.add("active");
        this.currentTab = t.dataset.tab;
        this.loadTab();
      };
    });
    this.loadTab();
  },

  loadTab() {
    if (this.currentTab === "inbox") this.renderInbox();
    else if (this.currentTab === "archived") this.renderArchived();
    else if (this.currentTab === "flow") this.renderFlow();
  },

  // ========== 未处理区 ==========
  async renderInbox() {
    const content = document.getElementById("doc-content");
    content.innerHTML = `
      <div class="card">
        <div class="card-title">
          <span>未处理文件</span>
          <div>
            <button class="btn btn-primary" id="upload-btn">📤 上传文件</button>
            <button class="btn btn-success" id="process-btn">▶ 开始处理</button>
            <button class="btn btn-warning" id="refresh-btn">🔄 刷新</button>
          </div>
        </div>
        <input type="file" id="file-input" multiple style="display:none" />
        <div id="inbox-list">加载中...</div>
      </div>
      <div class="card">
        <div class="card-title"><span>失败文件</span></div>
        <div id="failed-list">加载中...</div>
      </div>
    `;

    document.getElementById("upload-btn").onclick = () => document.getElementById("file-input").click();
    document.getElementById("file-input").onchange = (e) => this.uploadFiles(e.target.files);
    document.getElementById("process-btn").onclick = () => this.processInbox();
    document.getElementById("refresh-btn").onclick = () => this.renderInbox();

    await this.loadInboxFiles();
    await this.loadFailed();
  },

  async loadInboxFiles() {
    try {
      const res = await API.inboxFiles();
      const list = document.getElementById("inbox-list");
      if (res.data.length === 0) {
        list.innerHTML = "<p style='color:var(--text-2)'>未处理区为空，上传文件后点击「开始处理」</p>";
        return;
      }
      list.innerHTML = `
        <table>
          <thead><tr><th>文件名</th><th>所属项目</th><th>大小</th><th>修改时间</th></tr></thead>
          <tbody>
            ${res.data.map(f => `
              <tr>
                <td>${escapeHtml(f.name)}</td>
                <td><span class="tag tag-blue">${escapeHtml(f.project)}</span></td>
                <td>${fmtSize(f.size)}</td>
                <td>${fmtTime(f.modified)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
    } catch (e) { document.getElementById("inbox-list").textContent = "加载失败"; }
  },

  async loadFailed() {
    try {
      const res = await API.failedList();
      const list = document.getElementById("failed-list");
      if (res.data.length === 0) {
        list.innerHTML = "<p style='color:var(--text-2)'>暂无失败文件</p>";
        return;
      }
      list.innerHTML = `
        <table>
          <thead><tr><th>文件名</th><th>失败原因</th><th>操作</th></tr></thead>
          <tbody>
            ${res.data.map(f => `
              <tr>
                <td>${escapeHtml(f.name || f.filename || f)}</td>
                <td><span class="tag tag-red">${escapeHtml(f.error || f.reason || "未知")}</span></td>
                <td><button class="btn btn-warning btn-sm" id="retry-btn">重试全部</button></td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
      const btn = document.getElementById("retry-btn");
      if (btn) btn.onclick = () => this.retryFailed();
    } catch (e) { document.getElementById("failed-list").textContent = "加载失败"; }
  },

  async uploadFiles(files) {
    if (!files.length) return;
    try {
      const res = await API.ingestUpload(Array.from(files));
      toast(`成功上传 ${res.count} 个文件`, "success");
      this.loadInboxFiles();
    } catch (e) { /* 已 toast */ }
  },

  async processInbox() {
    const btn = document.getElementById("process-btn");
    btn.disabled = true; btn.textContent = "处理中...";
    try {
      const res = await API.ingestProcess();
      toast("处理完成", "success");
      console.log("处理报告", res.data);
      this.loadInboxFiles();
      this.loadFailed();
    } catch (e) { /* 已 toast */ }
    finally { btn.disabled = false; btn.textContent = "▶ 开始处理"; }
  },

  async retryFailed() {
    try {
      await API.failedRetry();
      toast("重试完成", "success");
      this.loadFailed();
    } catch (e) { /* 已 toast */ }
  },

  // ========== 已处理区 ==========
  async renderArchived() {
    const content = document.getElementById("doc-content");
    content.innerHTML = `
      <div class="doc-layout">
        <div class="project-tree">
          <div class="card-title" style="padding:12px">项目列表</div>
          <div id="project-tree">加载中...</div>
        </div>
        <div class="doc-list" id="file-list-panel">
          <div style="padding:12px;color:var(--text-2)">选择左侧项目查看文件</div>
        </div>
      </div>
    `;
    this.loadProjects();
  },

  async loadProjects() {
    try {
      const res = await API.projects();
      const tree = document.getElementById("project-tree");
      if (res.data.length === 0) {
        tree.innerHTML = "<div style='padding:12px;color:var(--text-2)'>暂无项目</div>";
        return;
      }
      tree.innerHTML = res.data.map(p => `
        <div class="project-tree-item" data-id="${p.project_id}">
          <div class="project-tree-name">${escapeHtml(p.name)}</div>
          <div class="project-tree-count">${p.file_count} 个文件</div>
        </div>
      `).join("");
      tree.querySelectorAll(".project-tree-item").forEach(el => {
        el.onclick = () => this.selectProject(el.dataset.id);
      });
    } catch (e) { document.getElementById("project-tree").textContent = "加载失败"; }
  },

  async selectProject(pid) {
    this.currentProjectId = pid;
    document.querySelectorAll(".project-tree-item").forEach(el => {
      el.classList.toggle("active", el.dataset.id === pid);
    });
    try {
      const res = await API.projectFiles(pid);
      const panel = document.getElementById("file-list-panel");
      if (res.data.length === 0) {
        panel.innerHTML = "<div style='padding:12px;color:var(--text-2)'>该项目下暂无文件</div>";
        return;
      }
      panel.innerHTML = `
        <table>
          <thead><tr><th>文件名</th><th>格式</th><th>摘要</th><th>关键词</th><th>分片数</th><th>操作</th></tr></thead>
          <tbody>
            ${res.data.map(f => `
              <tr>
                <td>${escapeHtml(f.filename)}</td>
                <td><span class="tag tag-gray">${escapeHtml(f.content_type || "")}</span></td>
                <td style="max-width:300px">${escapeHtml((f.summary || "").substring(0, 80))}</td>
                <td>${(f.keywords || []).map(k => `<span class="tag tag-blue">${escapeHtml(k)}</span>`).join(" ")}</td>
                <td>${f.chunk_count}</td>
                <td><button class="btn btn-default btn-sm" data-fid="${f.file_id}">查看详情</button></td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
      panel.querySelectorAll("button[data-fid]").forEach(b => {
        b.onclick = () => this.showFileDetail(b.dataset.fid);
      });
    } catch (e) { panel.innerHTML = "加载失败"; }
  },

  async showFileDetail(fid) {
    try {
      const [chunksRes, metaRes] = await Promise.all([API.fileChunks(fid), API.fileMeta(fid)]);
      const chunks = chunksRes.data || [];
      const meta = metaRes.data || {};
      const panel = document.getElementById("file-list-panel");
      panel.innerHTML = `
        <div class="card">
          <div class="card-title">
            <span>文件详情 - 分片列表（共 ${chunks.length} 个）</span>
            <button class="btn btn-default btn-sm" id="back-btn">← 返回列表</button>
          </div>
          ${chunks.map((c, i) => `
            <div style="padding:10px;border-bottom:1px solid var(--border)">
              <div style="font-size:12px;color:var(--text-2);margin-bottom:4px">分片 #${i + 1} · chunk_id: ${escapeHtml(c.chunk_id || "")}</div>
              <div style="line-height:1.6;white-space:pre-wrap">${escapeHtml(c.text || "")}</div>
            </div>
          `).join("")}
        </div>
        <div class="card">
          <div class="card-title">元数据 (.meta.json)</div>
          <pre style="font-size:12px;overflow:auto;max-height:300px;background:#f9fafb;padding:10px;border-radius:6px">${escapeHtml(JSON.stringify(meta, null, 2))}</pre>
        </div>
      `;
      document.getElementById("back-btn").onclick = () => this.selectProject(this.currentProjectId);
    } catch (e) { toast("加载详情失败", "error"); }
  },

  // ========== 入库流程监控 ==========
  async renderFlow() {
    const content = document.getElementById("doc-content");
    content.innerHTML = `
      <div class="card">
        <div class="card-title">入库全流程</div>
        <div class="flow-steps">
          <div class="flow-step"><div class="flow-step-num">1</div><div class="flow-step-name">扫描识别</div><div class="flow-step-desc">一级目录=项目，根目录=AI聚类</div></div>
          <div class="flow-step"><div class="flow-step-num">2</div><div class="flow-step-name">格式提取</div><div class="flow-step-desc">txt/md/docx/xlsx/pptx/pdf/csv/json</div></div>
          <div class="flow-step"><div class="flow-step-num">3</div><div class="flow-step-name">AI摘要分片</div><div class="flow-step-desc">摘要+关键词+语义分片</div></div>
          <div class="flow-step"><div class="flow-step-num">4</div><div class="flow-step-name">归档写入</div><div class="flow-step-desc">原始文件+.meta.json（重试3次）</div></div>
          <div class="flow-step"><div class="flow-step-num">5</div><div class="flow-step-name">双索引写入</div><div class="flow-step-desc">MySQL索引 + Redis向量</div></div>
          <div class="flow-step"><div class="flow-step-num">6</div><div class="flow-step-name">原文件清理</div><div class="flow-step-desc">归档+索引双确认后删除</div></div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">存储架构实时数据</div>
        <div id="storage-stats">加载中...</div>
      </div>
      <div class="card">
        <div class="card-title">幂等去重规则</div>
        <p style="color:var(--text-2);line-height:1.8">
          基于「文件名 + 文件大小 + 修改时间戳」生成指纹，重复文件自动跳过。<br>
          归档写入与索引写入双确认成功后，才会删除未处理区原文件，保证数据不丢失。
        </p>
      </div>
    `;
    this.loadStorageStats();
  },

  async loadStorageStats() {
    try {
      const res = await API.indexStats();
      const d = res.data;
      const box = document.getElementById("storage-stats");
      box.innerHTML = `
        <div class="storage-arch">
          <div class="storage-layer" style="border-top:3px solid #3b82f6">
            <div class="storage-layer-title">🗄️ MySQL 主存</div>
            <div class="storage-layer-meta">项目: <strong>${d.project_count}</strong></div>
            <div class="storage-layer-meta">文件: <strong>${d.file_count}</strong></div>
            <div class="storage-layer-meta">分片: <strong>${d.chunk_count}</strong></div>
          </div>
          <div class="storage-layer" style="border-top:3px solid #ef4444">
            <div class="storage-layer-title">⚡ Redis 向量库</div>
            <div class="storage-layer-meta">向量总数: <strong>${d.redis.total_vectors || 0}</strong></div>
            <div class="storage-layer-meta">状态: <span class="tag ${d.redis.status === 'ok' ? 'tag-green' : 'tag-red'}">${d.redis.status}</span></div>
            <div class="storage-layer-meta">索引数: <strong>${(d.redis.indexes || []).length}</strong></div>
          </div>
          <div class="storage-layer" style="border-top:3px solid #10b981">
            <div class="storage-layer-title">💾 磁盘备份</div>
            <div class="storage-layer-meta">已处理区原始文件 + .meta.json</div>
            <div class="storage-layer-meta">可用于灾备导入 MySQL</div>
            <div class="storage-layer-meta">支持 <code>import_from_disk()</code></div>
          </div>
        </div>
      `;
    } catch (e) { document.getElementById("storage-stats").textContent = "加载失败"; }
  },
};
