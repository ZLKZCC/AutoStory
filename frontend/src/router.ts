import { createRouter, createWebHistory } from "vue-router";
import HomePage from "./pages/HomePage";
import ProjectPage from "./pages/ProjectPage";
import SettingsPage from "./pages/SettingsPage";
import ResourcesPage from "./pages/ResourcesPage";
import KnowledgeBasePage from "./pages/KnowledgeBasePage";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", component: HomePage },
    { path: "/project/:id", component: ProjectPage },
    { path: "/settings", component: SettingsPage },
    { path: "/resources", component: ResourcesPage },
    { path: "/knowledge-base", component: KnowledgeBasePage },
    // 桌面壳以 /index.html 路径加载页面，未知路径一律回到主页
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});
