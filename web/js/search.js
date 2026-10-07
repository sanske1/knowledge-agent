/**
 * 检索中心模块
 */
const SearchModule = {
  projects: [],
  outputMode: "json",

  render(container) {
    container.innerHTML = `
      <div class="card">
        <div class="search-bar">
          <input type="text" id="search-input" placeholder="输入自然语言查询，如：三级索引体系是什么？" />
          <button class="btn btn-primary" id="search-btn">🔍 检索</button>
        </div>
        <div class="search-filters">
          <select class="form-control" id="filter-project" style="width:auto">
            <option value="">全部项目</option>
          </select>
          <label style="display:flex;align-items:center;gap:6px">
            TopK: <input type="number" id="filter-topk" value="5" min="1" max="50" style="width:60px" class="form-control" />
          </label>
          <label style="display:flex;align-items:center;gap:6px">
            输出:
            <select class="form-control" id="output-mode" style="width:auto">
              <option value="json">标准JSON</option>
              <option value="tool">工具格式化文本</option>
            </select>
          </label>
        </div>
      </div>
      <div id="search-results"><p style="color:var(--text-2)">输入查询后点击检索</p></div>
    `;

    document.getElementById("search-btn").onclick = () => this.doSearch();
    document.getElementById("search-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") this.doSearch();
    });
    document.getElementById("output-mode").onchange = (e) => { this.outputMode = e.target.value; };

    this.loadProjects();
  },

  async loadProjects() {
    try {
      const res = await API.projects();
      this.projects = res.data || [];
      const sel = document.getElementById("filter-project");
      this.projects.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.name; opt.textContent = p.name;
        sel.appendChild(opt);
      });
    } catch (e) { /* 静默 */ }
  },

  async doSearch() {
    const q = document.getElementById("search-input").value.trim();
    if (!q) { toast("请输入查询内容", "error"); return; }
    const topk = parseInt(document.getElementById("filter-topk").value) || 5;
    const project = document.getElementById("filter-project").value;
    const box = document.getElementById("search-results");
    box.innerHTML = "<p style='color:var(--text-2)'>检索中...</p>";

    try {
      if (this.outputMode === "tool") {
        const res = await API.searchTool(q, topk);
        box.innerHTML = `<div class="card"><pre style="white-space:pre-wrap;font-size:13px;line-height:1.6">${escapeHtml(res.result)}</pre></div>`;
        return;
      }
      const res = await API.search(q, topk, project || null);
      if (res.data.length === 0) {
        box.innerHTML = "<p style='color:var(--text-2)'>未找到相关结果</p>";
        return;
      }
      box.innerHTML = res.data.map(r => `
        <div class="search-result">
          <div>
            <span class="search-result-score">相似度 ${(r.score).toFixed(4)}</span>
            <span class="tag tag-blue" style="margin-left:8px">${escapeHtml(r.project_name || r.project || "")}</span>
            <span class="tag tag-gray">${escapeHtml(r.filename || r.file || "")}</span>
          </div>
          <div class="search-result-meta">来源: 《${escapeHtml(r.filename || r.file || "")}》（${escapeHtml(r.project_name || r.project || "")}）</div>
          <div class="search-result-text">${escapeHtml(r.text || r.content || "").replace(/\n/g, "<br>")}</div>
        </div>
      `).join("");
    } catch (e) { box.innerHTML = "<p style='color:var(--danger)'>检索失败</p>"; }
  },
};
