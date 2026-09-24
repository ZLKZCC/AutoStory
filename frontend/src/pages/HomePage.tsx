import { defineComponent, ref, onMounted, onBeforeUnmount } from "vue";
import { useRouter } from "vue-router";
import { createProject } from "../api";
import { useProjectList } from "../App";
import Button from "../components/Button";
import Tag from "../components/Tag";
import PageLoader from "../components/PageLoader";
import { useConfirm } from "../components/ConfirmDialog";
import gsap from "gsap";
import { PhPlus, PhTrash, PhBookOpen } from "@phosphor-icons/vue";

export default defineComponent({
  name: "HomePage",
  setup() {
    const { projects, refreshProjects, removeProject, addProject } = useProjectList();
    const { confirm } = useConfirm();
    const newName = ref("");
    const loading = ref(true);
    const nav = useRouter();
    const brandEl = ref<HTMLDivElement | null>(null);
    let brandAnim: gsap.core.Tween | null = null;

    onMounted(() => {
      refreshProjects().finally(() => (loading.value = false));

      if (brandEl.value) {
        brandAnim = gsap.to(brandEl.value, {
          backgroundPosition: "200% center",
          duration: 3,
          ease: "none",
          repeat: -1,
        });
      }
    });

    onBeforeUnmount(() => {
      brandAnim?.kill();
    });

    const handleCreate = async () => {
      if (!newName.value.trim()) return;
      try {
        const created = await createProject(newName.value.trim());
        newName.value = "";
        addProject(created);
      } catch (e: any) {
        alert(e.message);
      }
    };

    const handleDelete = async (id: number, displayName: string) => {
      const ok = await confirm({
        title: "删除作品",
        message: `确定要删除作品「${displayName}」吗？该项目下全部章节、角色、音频与数据将一并删除，不可恢复。`,
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      await removeProject(id);
    };

    return () => (
      <PageLoader loading={loading.value} text="加载作品...">
        <div class="home-page">
          <div class="home-hero">
            <div class="home-brand" ref={brandEl}>
              <span class="home-brand-auto">Auto</span>
              <span class="home-brand-story">Story{"\u200B"}</span>
            </div>
            <div class="home-subtitle">一个AI驱动的故事创作平台</div>
          </div>

          <div class="home-create-bar">
            <div style={{ flex: 1, position: "relative" }}>
              <input
                class="input-field home-create-input"
                placeholder="输入作品名称，开始新对话..."
                value={newName.value}
                onInput={(e) => (newName.value = (e.target as HTMLInputElement).value)}
                onKeydown={(e) => e.key === "Enter" && handleCreate()}
              />
              {newName.value.length > 0 && (
                <span class="input-char-count">{newName.value.length}</span>
              )}
            </div>
            <Button size="md" onClick={handleCreate}>
              <PhPlus size={16} weight="bold" />
              新建作品
            </Button>
          </div>

          {loading.value ? (
            <div class="empty-state">加载中...</div>
          ) : projects.value.length === 0 ? (
            <div class="empty-state">
              <PhBookOpen
                size={36}
                weight="light"
                style={{ opacity: 0.25, marginBottom: "8px" }}
              />
              <div
                style={{
                  fontSize: "14px",
                  fontWeight: 500,
                  marginBottom: "4px",
                  color: "var(--color-text-secondary)",
                }}
              >
                还没有作品
              </div>
              <div>输入名称并点击「新建作品」开始创作</div>
            </div>
          ) : (
            <div class="home-project-grid">
              {projects.value.map((p) => (
                <div
                  key={p.id}
                  class="project-card"
                  onClick={() => nav.push(`/project/${p.id}`)}
                >
                  <div class="project-card-inner">
                    <div class="project-card-main">
                      <div class="project-card-text">
                        <div class="project-card-name">{p.name}</div>
                        {p.description && (
                          <div class="project-card-desc">{p.description}</div>
                        )}
                      </div>
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "var(--space-sm)",
                        flexShrink: 0,
                      }}
                    >
                      {p.chapter_count > 0 && (
                        <Tag size="sm">共 {p.chapter_count} 章</Tag>
                      )}
                      {p.character_count > 0 && (
                        <Tag size="sm">共 {p.character_count} 个角色</Tag>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e: MouseEvent) => {
                          e.stopPropagation();
                          handleDelete(p.id!, p.name);
                        }}
                      >
                        <PhTrash size={14} weight="light" />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </PageLoader>
    );
  },
});
