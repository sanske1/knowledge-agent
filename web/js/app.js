/**
 * 主应用：路由、布局、全局状态
 */
const App = {
  currentRoute: "chat",
  currentSessionId: null,

  init() {
    this.bindNav();
    this.handleRoute();
    this.refreshServiceStatus();
    setInterval(() => this.refreshServiceStatus(), 15000);
    window.addEventListener("hashchange", () => this.handleRoute());
  },

  bindNav() {
    document.querySelectorAll(".nav-item").forEach(item => {
      item.addEventListener("click", (e) => {
        e.preventDefault();
        const route = item.dataset.route;
        location.hash = "#/" + route;
      });
    });
  },

  handleRoute() {
    const hash = location.hash.replace("#/", "") || "chat";
    const [route, ...parts] = hash.split("/");
    this.currentRoute = route;

    // 高亮导航
    document.querySelectorAll(".nav-item").forEach(el => {
      el.classList.toggle("active", el.dataset.route === route);
    });

    // 面包屑
    const names = { chat: "智能对话", documents: "文档中心", search: "检索中心", system: "系统管理" };
    document.getElementById("breadcrumb").textContent = names[route] || "";

    const main = document.getElementById("main-content");
    if (route === "chat") ChatModule.render(main);
    else if (route === "documents") DocumentsModule.render(main);
    else if (route === "search") SearchModule.render(main);
    else if (route === "system") SystemModule.render(main);
    else { main.innerHTML = "<div class='card'><p>页面不存在</p></div>"; }
  },

  async refreshServiceStatus() {
    try {
      const res = await API.statusServices();
      const map = { mysql: res.data.mysql, redis: res.data.redis, mcp: res.data.mcp };
      document.querySelectorAll(".service-status .dot").forEach(dot => {
        const svc = dot.dataset.svc;
        dot.classList.toggle("ok", map[svc]?.status === "ok");
        dot.classList.toggle("error", map[svc]?.status === "error");
      });
    } catch (e) { /* 静默 */ }
  },
};

document.addEventListener("DOMContentLoaded", () => App.init());
