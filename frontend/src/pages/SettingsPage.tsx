import { defineComponent, ref, reactive, computed, watch, onMounted, type VNodeChild } from "vue";
import { testProvider, testConnection, type ProviderInfo } from "../api";
import { type CheckModelItem } from "../api";
import { useModelSyncStore } from "../stores/modelSync";
import { useProviderStore } from "../stores/providers";
import Card, { CardHeader } from "../components/Card";
import Button from "../components/Button";
import Input from "../components/Input";
import Tag from "../components/Tag";
import Modal from "../components/Modal";
import PageLoader from "../components/PageLoader";
import { useConfirm } from "../components/ConfirmDialog";
import gsap from "gsap";
import {
  PhBrain,
  PhSpeakerHigh,
  PhPlus,
  PhTrash,
  PhLightning,
  PhCheck,
  PhX,
  PhKey,
  PhDownloadSimple,
  PhCheckSquare,
  PhSquare,
  PhArrowsClockwise,
  PhVectorThree,
  PhPencilSimple,
} from "@phosphor-icons/vue";
import deepseekIcon from "@lobehub/icons-static-svg/icons/deepseek-color.svg";
import openaiIcon from "@lobehub/icons-static-svg/icons/openai.svg";
import claudeIcon from "@lobehub/icons-static-svg/icons/claude-color.svg";
import zhipuIcon from "@lobehub/icons-static-svg/icons/zhipu-color.svg";
import qwenIcon from "@lobehub/icons-static-svg/icons/qwen-color.svg";
import kimiIcon from "@lobehub/icons-static-svg/icons/kimi-color.svg";
import yiIcon from "@lobehub/icons-static-svg/icons/yi-color.svg";
import minimaxIcon from "@lobehub/icons-static-svg/icons/minimax-color.svg";
import volcengineIcon from "@lobehub/icons-static-svg/icons/volcengine-color.svg";
import geminiIcon from "@lobehub/icons-static-svg/icons/gemini-color.svg";
import mistralIcon from "@lobehub/icons-static-svg/icons/mistral-color.svg";
import xaiIcon from "@lobehub/icons-static-svg/icons/xai.svg";
import openrouterIcon from "@lobehub/icons-static-svg/icons/openrouter-color.svg";
import ollamaIcon from "@lobehub/icons-static-svg/icons/ollama.svg";

const PROVIDER_TYPES = [
  { value: "llm", label: "LLM 大模型", icon: PhBrain },
  { value: "tts", label: "TTS 语音合成", icon: PhSpeakerHigh },
  { value: "vector", label: "向量模型", icon: PhVectorThree },
] as const;

type ProviderType = (typeof PROVIDER_TYPES)[number]["value"];

interface LLMPreset {
  id: string;
  name: string;
  icon?: string;
  iconBg?: string;
  format: string;
  base_url: string;
  models: string[];
  hint?: string;
}

const LLM_PRESETS: LLMPreset[] = [
  {
    id: "deepseek",
    name: "DeepSeek",
    icon: deepseekIcon,
    format: "OpenAI",
    base_url: "https://api.deepseek.com",
    models: ["deepseek-v4-flash", "deepseek-v4-pro"],
    hint: "platform.deepseek.com",
  },
  {
    id: "openai",
    name: "OpenAI",
    icon: openaiIcon,
    format: "OpenAI",
    base_url: "https://api.openai.com/v1",
    models: ["gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-4o", "gpt-4o-mini"],
    hint: "platform.openai.com",
  },
  {
    id: "anthropic",
    name: "Anthropic Claude",
    icon: claudeIcon,
    format: "Anthropic",
    base_url: "https://api.anthropic.com",
    models: ["claude-opus-4-5", "claude-sonnet-4-6", "claude-haiku-4-5"],
    hint: "console.anthropic.com",
  },
  {
    id: "zhipu",
    name: "智谱 GLM",
    icon: zhipuIcon,
    format: "OpenAI",
    base_url: "https://open.bigmodel.cn/api/paas/v4",
    models: ["glm-5.1", "glm-4.7", "glm-4-plus", "glm-4-flash"],
    hint: "open.bigmodel.cn",
  },
  {
    id: "qwen",
    name: "通义千问",
    icon: qwenIcon,
    format: "OpenAI",
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    models: ["qwen3.8-max", "qwen-plus", "qwen-turbo", "qwen-flash"],
    hint: "bailian.console.aliyun.com",
  },
  {
    id: "moonshot",
    name: "Moonshot Kimi",
    icon: kimiIcon,
    iconBg: "#0a0a0a",
    format: "OpenAI",
    base_url: "https://api.moonshot.cn/v1",
    models: ["kimi-k2.6", "kimi-k2.5", "moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k"],
    hint: "platform.moonshot.cn",
  },
  {
    id: "yi",
    name: "零一万物",
    icon: yiIcon,
    format: "OpenAI",
    base_url: "https://api.lingyiwanwu.com/v1",
    models: ["yi-large", "yi-medium", "yi-lightning"],
    hint: "platform.lingyiwanwu.com",
  },
  {
    id: "minimax",
    name: "MiniMax",
    icon: minimaxIcon,
    format: "OpenAI",
    base_url: "https://api.minimax.chat/v1",
    models: ["minimax-text-02", "abab6.5s-chat"],
    hint: "platform.minimaxi.com",
  },
  {
    id: "volcengine",
    name: "火山方舟",
    icon: volcengineIcon,
    format: "OpenAI",
    base_url: "https://ark.cn-beijing.volces.com/api/v3",
    models: ["doubao-seed-1-6", "doubao-1-5-pro-32k", "doubao-1-5-lite-32k"],
    hint: "console.volcengine.com/ark",
  },
  {
    id: "gemini",
    name: "Google Gemini",
    icon: geminiIcon,
    format: "Gemini",
    base_url: "https://generativelanguage.googleapis.com/v1beta/openai",
    models: ["gemini-3-pro", "gemini-3-flash"],
    hint: "aistudio.google.com",
  },
  {
    id: "mistral",
    name: "Mistral",
    icon: mistralIcon,
    format: "OpenAI",
    base_url: "https://api.mistral.ai/v1",
    models: ["mistral-large-latest", "mistral-small-latest"],
    hint: "console.mistral.ai",
  },
  {
    id: "xai",
    name: "xAI Grok",
    icon: xaiIcon,
    format: "OpenAI",
    base_url: "https://api.x.ai/v1",
    models: ["grok-4", "grok-4-mini", "grok-3"],
    hint: "console.x.ai",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    icon: openrouterIcon,
    format: "OpenAI",
    base_url: "https://openrouter.ai/api/v1",
    models: [],
    hint: "openrouter.ai（聚合多家模型）",
  },
  {
    id: "ollama",
    name: "Ollama（本地）",
    icon: ollamaIcon,
    format: "OpenAI",
    base_url: "http://localhost:11434",
    models: ["qwen3", "llama3.1", "deepseek-r1", "gemma3"],
  },
  {
    id: "custom",
    name: "自定义",
    format: "OpenAI",
    base_url: "",
    models: [],
  },
];

const labelStyle = {
  fontSize: "12px",
  fontWeight: 500,
  color: "var(--color-text-secondary)",
  marginBottom: "6px",
  display: "block",
} as const;

export default defineComponent({
  name: "SettingsPage",
  setup() {
    const { confirm } = useConfirm();
    const providerStore = useProviderStore();
    const providers = computed(() => providerStore.providers);
    const activeType = ref<ProviderType>("llm");
    const showForm = ref(false);
    const editingId = ref<number | null>(null);
    const testing = ref<string | null>(null);
    const testResult = ref<{
      name: string;
      success: boolean;
      error?: string;
      models?: string[];
    } | null>(null);
    const form = reactive({
      name: "",
      provider_type: "llm" as string,
      base_url: "",
      api_key: "",
      model: "",
      is_default: true,
      context_length: "" as string,
    });
    const selectedPreset = ref<string>("");

    const modalTesting = ref(false);
    const modalTestResult = ref<{
      success: boolean;
      error?: string;
      models?: string[];
    } | null>(null);

    const providerModels = ref<Record<string, string[]>>({});

    const selectMode = ref(false);
    const selectedNames = ref<Set<string>>(new Set());

    const modelSync = useModelSyncStore();
    const { refreshLocalModels, startSync } = modelSync;

    const tabEls: (HTMLButtonElement | null)[] = [];
    const tabIndicatorEl = ref<HTMLDivElement | null>(null);

    const pageLoading = ref(true);

    const modelGroupOf = (category: string) =>
      modelSync.localModels.filter(
        (m) =>
          m.category === category ||
          (category === "tts" && m.id.toLowerCase().includes("tts")),
      );

    const maskKey = (key: string) =>
      key ? `${key.slice(0, 5)}****${key.slice(-4)}` : "";

    const providersLoading = computed(() => providerStore.loading);
    const providerTotal = computed(() => providerStore.total);
    const loadProviders = providerStore.loadProviders;

    const handleListScroll = (e: Event) => {
      const el = e.target as HTMLElement;
      if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40)
        loadProviders(false);
    };

    onMounted(() => {
      Promise.all([loadProviders(true), Promise.resolve(refreshLocalModels())]).finally(
        () => (pageLoading.value = false),
      );
    });

    watch(activeType, (t) => {
      refreshLocalModels();
      const idx = PROVIDER_TYPES.findIndex((p) => p.value === t);
      const btn = tabEls[idx];
      const indicator = tabIndicatorEl.value;
      if (btn && indicator) {
        gsap.to(indicator, {
          x: btn.offsetLeft,
          width: btn.offsetWidth,
          duration: 0.3,
          ease: "power2.out",
        });
      }
    });

    const handleSubmit = async () => {
      if (!form.name) return;
      const preset = LLM_PRESETS.find((p) => p.id === selectedPreset.value);

      if (editingId.value !== null) {
        const payload: Record<string, unknown> = {
          provider_name: form.name,
          kind: preset?.id ?? "custom",
          model_id: form.model,
          context_length: form.context_length ? parseInt(form.context_length) : 0,
          active: form.is_default,
          api_url: form.base_url,
        };
        if (form.api_key) payload.api_key = form.api_key;
        await providerStore.update(editingId.value, payload);
      } else {
        if (!form.api_key) return;
        await providerStore.create({
          provider_name: form.name,
          kind: preset?.id ?? "custom",
          model_id: form.model,
          context_length: form.context_length ? parseInt(form.context_length) : 0,
          active: form.is_default,
          api_url: form.base_url,
          api_key: form.api_key,
        });
      }

      if (modalTestResult.value?.success && modalTestResult.value.models) {
        providerModels.value = {
          ...providerModels.value,
          [form.name]: modalTestResult.value.models,
        };
      }
      showForm.value = false;
      editingId.value = null;
      Object.assign(form, {
        name: "",
        provider_type: "llm",
        base_url: "",
        api_key: "",
        model: "",
        is_default: true,
        context_length: "",
      });
      modalTestResult.value = null;
    };

    const handleTest = async (name: string, apiUrl: string, apiKey: string) => {
      testing.value = name;
      testResult.value = null;
      try {
        const r = await testProvider(apiUrl, apiKey);
        const result = r.data ?? { success: false, error: "无响应数据" };
        testResult.value = { name, ...result };
        if (result.success && result.models) {
          providerModels.value = { ...providerModels.value, [name]: result.models };
        }
      } catch (e: any) {
        testResult.value = { name, success: false, error: e.message };
      }
      testing.value = null;
    };

    const handleDelete = async (provider: ProviderInfo) => {
      const ok = await confirm({
        title: "删除供应商",
        message: `确定要删除供应商「${provider.provider_name}」吗？其模型配置将一并删除，不可恢复。`,
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      await providerStore.remove(provider.id);
    };

    const handleBatchDelete = async () => {
      if (selectedNames.value.size === 0) return;
      const count = selectedNames.value.size;
      const ok = await confirm({
        title: "批量删除供应商",
        message: `确定要删除选中的 ${count} 个供应商吗？其模型配置将一并删除，不可恢复。`,
        danger: true,
        confirmText: "确认删除",
      });
      if (!ok) return;
      const ids = providers.value
        .filter((p) => selectedNames.value.has(p.provider_name))
        .map((p) => p.id);
      if (ids.length > 0) {
        await providerStore.batchRemove(ids);
      }
      exitSelectMode();
    };

    const handleActivate = async (providerId: number) => {
      await providerStore.activate(providerId);
    };

    const handleModelChange = async (
      providerId: number,
      kind: string,
      baseUrl: string,
      newModel: string,
      isDefault: boolean,
    ) => {
      try {
        await providerStore.update(providerId, {
          kind,
          api_url: baseUrl,
          model_id: newModel,
          active: isDefault,
        });
      } catch (e) {
        console.error(e);
      }
    };

    const openAddModal = () => {
      Object.assign(form, {
        name: "",
        provider_type: activeType.value,
        base_url: "",
        api_key: "",
        model: "",
        is_default: false,
        context_length: "",
      });
      selectedPreset.value = "";
      modalTestResult.value = null;
      modalTesting.value = false;
      editingId.value = null;
      showForm.value = true;
    };

    const openEditModal = (p: ProviderInfo) => {
      const preset = LLM_PRESETS.find((x) => x.id === p.kind);
      Object.assign(form, {
        name: p.provider_name,
        provider_type: "llm",
        base_url: p.api_url,
        api_key: "", // 留空 → 后端不覆盖原 key
        model: p.model_id,
        is_default: p.active,
        context_length: p.context_length ? String(p.context_length) : "",
      });
      selectedPreset.value = preset?.id ?? (p.kind || "");
      modalTestResult.value = null;
      modalTesting.value = false;
      editingId.value = p.id;
      showForm.value = true;
    };

    const handleModalTest = async () => {
      if (!form.base_url || !form.api_key) return;
      modalTesting.value = true;
      modalTestResult.value = null;
      try {
        const r = await testConnection(form.base_url, form.api_key, selectedPreset.value || undefined);
        const result = r.data ?? { success: false, error: "无响应数据" };
        modalTestResult.value = result;
        if (result.success && result.models && result.models.length > 0) {
          if (!form.model) {
            form.model = result.models[0];
          }
        }
      } catch (e: any) {
        modalTestResult.value = { success: false, error: e.message };
      }
      modalTesting.value = false;
    };

    const handlePresetChange = (presetId: string) => {
      selectedPreset.value = presetId;
      const preset = LLM_PRESETS.find((p) => p.id === presetId);
      if (preset && preset.id === "custom") {
        Object.assign(form, { name: "", base_url: "", model: "" });
      } else if (preset) {
        Object.assign(form, { name: preset.name, base_url: preset.base_url, model: "" });
      }
      modalTestResult.value = null;
    };

    const toggleSelect = (name: string) => {
      const next = new Set(selectedNames.value);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      selectedNames.value = next;
    };

    const exitSelectMode = () => {
      selectMode.value = false;
      selectedNames.value = new Set();
    };

    return () => {
      const filtered = providers.value;

      const selectAll = () => {
        selectedNames.value = new Set(filtered.map((p) => p.provider_name));
      };

      const deselectAll = () => {
        selectedNames.value = new Set();
      };

      const renderModelItem = (m: CheckModelItem): VNodeChild => {
        const dl = modelSync.downloading[m.id];
        const isDownloading = dl?.status === "pending" || dl?.status === "running";
        const isError = dl?.status === "error";
        const isReady = m.exists || modelSync.downloadedIds.has(m.id);
        return (
          <div key={m.id} class="provider-item">
            <div class="provider-item-left">
              <div class="provider-item-info">
                <span class="provider-item-name">{m.name}</span>
              </div>
              <div
                style={{
                  fontSize: "11px",
                  color: "var(--color-text-muted)",
                  marginTop: "1px",
                }}
              >
                {m.description}
                <span style={{ marginLeft: "4px", opacity: 0.7 }}>· {m.size}</span>
              </div>
              {isDownloading && dl && (
                <div style={{ marginTop: "4px" }}>
                  <div
                    class="download-item-progress"
                    style={{ width: "120px" }}
                  >
                    <div
                      class="download-item-progress-fill"
                      style={{ width: `${dl.progress}%` }}
                    />
                  </div>
                  <span
                    style={{
                      fontSize: "10px",
                      color: "var(--color-text-muted)",
                    }}
                  >
                    {dl.progress}%{dl.speed ? ` · ${dl.speed}` : ""}
                  </span>
                </div>
              )}
              {isError && dl?.error && (
                <span
                  style={{
                    fontSize: "11px",
                    color: "var(--color-error)",
                  }}
                >
                  下载失败: {dl.error}
                </span>
              )}
            </div>
            <div class="provider-item-actions">
              {isReady ? (
                <Tag variant="success" size="sm">
                  已下载
                </Tag>
              ) : isDownloading ? (
                <Tag variant="info" size="sm">
                  下载中
                </Tag>
              ) : isError ? (
                <Tag variant="error" size="sm">
                  失败
                </Tag>
              ) : (
                <Tag size="sm">未下载</Tag>
              )}
            </div>
          </div>
        );
      };

      const renderLocalModelSection = (
        category: "tts" | "vector",
        icon: VNodeChild,
        title: string,
        desc: string,
        listLabel: string,
      ) => {
        const groupModels = modelGroupOf(category);
        const groupPending = groupModels.filter(
          (m) => !m.exists && !modelSync.downloadedIds.has(m.id),
        );
        const groupDownloading =
          modelSync.syncing ||
          groupModels.some((m) => {
            const s = modelSync.downloading[m.id]?.status;
            return s === "pending" || s === "running";
          });
        const hasGroupError = groupModels.some(
          (m) => modelSync.downloading[m.id]?.status === "error",
        );
        const groupProgress = groupModels.length
          ? Math.round(
              groupModels.reduce((s, m) => {
                if (m.exists || modelSync.downloadedIds.has(m.id)) return s + 100;
                return s + (modelSync.downloading[m.id]?.progress ?? 0);
              }, 0) / groupModels.length,
            )
          : 0;
        const groupSpeed =
          groupModels
            .map((m) => modelSync.downloading[m.id]?.speed)
            .find(Boolean) || "";
        const firstChecking =
          modelSync.checking && modelSync.localModels.length === 0;
        return (
        <div style={{ marginBottom: "16px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              padding: "10px 14px",
              borderRadius: "var(--radius-md)",
              background: "rgba(217, 104, 48, 0.06)",
              border: "1px solid rgba(217, 104, 48, 0.15)",
              marginBottom: "16px",
            }}
          >
            {icon}
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 500, fontSize: "13px" }}>{title}</div>
              <div
                style={{
                  fontSize: "11px",
                  color: "var(--color-text-secondary)",
                  marginTop: "2px",
                }}
              >
                {desc}
              </div>
            </div>
            {firstChecking ? (
              <Tag variant="default" size="sm">
                检测中
              </Tag>
            ) : groupPending.length === 0 ? (
              <Tag variant="success" size="sm">
                已内置
              </Tag>
            ) : (
              <Button
                size="sm"
                variant="secondary"
                loading={modelSync.syncing}
                disabled={groupDownloading}
                onClick={startSync}
              >
                {!modelSync.syncing && (
                  <PhDownloadSimple size={14} weight="light" />
                )}
                {modelSync.syncing
                  ? "连接中"
                  : groupDownloading
                    ? `下载中 ${groupProgress}%${groupSpeed ? ` · ${groupSpeed}` : ""}`
                    : hasGroupError
                      ? "重试下载"
                      : `下载 ${groupPending.length} 个模型`}
              </Button>
            )}
          </div>

          <div style={{ marginTop: "8px" }}>
            <div
              style={{
                fontSize: "12px",
                fontWeight: 500,
                marginBottom: "8px",
                color: "var(--color-text-secondary)",
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              {listLabel}
              <button
                class="icon-btn"
                onClick={refreshLocalModels}
                title="刷新检测"
                disabled={modelSync.checking}
                style={{
                  padding: "2px",
                  ...(modelSync.checking
                    ? { opacity: 0.5, cursor: "not-allowed" }
                    : {}),
                }}
              >
                <PhArrowsClockwise
                  size={12}
                  weight="light"
                  style={
                    modelSync.checking
                      ? { animation: "spin 1s linear infinite" }
                      : undefined
                  }
                />
              </button>
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "6px",
              }}
            >
              {firstChecking ? (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "18px 0",
                  }}
                >
                  <div class="checking-dots">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              ) : (
                groupModels.map((m) => renderModelItem(m))
              )}
            </div>
          </div>
        </div>
        );
      };

      return (
        <PageLoader loading={pageLoading.value} text="加载设置...">
          <div class="page-container">
            <div class="page-header">
              <h1 class="page-title">模型设置</h1>
            </div>

            <Card hover={false}>
              <CardHeader
                title="模型管理"
                action={
                  <div
                    style={{
                      display: "flex",
                      gap: "var(--space-sm)",
                      alignItems: "center",
                    }}
                  >
                    {selectMode.value ? (
                      <>
                        <button class="provider-batch-btn" onClick={selectAll}>
                          <PhCheckSquare size={13} weight="light" /> 全选
                        </button>
                        <button class="provider-batch-btn" onClick={deselectAll}>
                          <PhSquare size={13} weight="light" /> 取消
                        </button>
                        <button
                          class="provider-batch-btn provider-batch-delete"
                          onClick={handleBatchDelete}
                          disabled={selectedNames.value.size === 0}
                        >
                          <PhTrash size={13} weight="light" /> 删除(
                          {selectedNames.value.size})
                        </button>
                        <button
                          class="provider-batch-btn"
                          onClick={exitSelectMode}
                        >
                          取消选择
                        </button>
                      </>
                    ) : (
                      <>
                        {activeType.value === "llm" && filtered.length > 0 && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => (selectMode.value = true)}
                          >
                            批量管理
                          </Button>
                        )}
                        {activeType.value === "llm" && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={openAddModal}
                          >
                            <PhPlus size={14} weight="bold" />
                            添加供应商
                          </Button>
                        )}
                      </>
                    )}
                  </div>
                }
              />

              <div
                style={{
                  display: "flex",
                  gap: "2px",
                  padding: "0 0 16px",
                  borderBottom: "1px solid var(--color-border-light)",
                  marginBottom: "16px",
                  position: "relative",
                }}
              >
                {PROVIDER_TYPES.map((t, i) => {
                  const Icon = t.icon;
                  const count =
                    t.value === "llm"
                      ? providerTotal.value
                      : modelGroupOf(t.value).length;
                  return (
                    <button
                      key={t.value}
                      ref={(el) => {
                        tabEls[i] = el as HTMLButtonElement;
                      }}
                      class={`provider-type-tab ${activeType.value === t.value ? "active" : ""}`}
                      onClick={() => {
                        activeType.value = t.value;
                        exitSelectMode();
                      }}
                    >
                      <Icon size={15} weight="light" />
                      <span>{t.label}</span>
                      {count > 0 && (
                        <span class="provider-type-count">{count}</span>
                      )}
                    </button>
                  );
                })}
                <div
                  ref={tabIndicatorEl}
                  style={{
                    position: "absolute",
                    bottom: 0,
                    height: "2px",
                    background: "var(--color-accent)",
                    borderRadius: "1px",
                  }}
                />
              </div>

              {activeType.value === "tts" &&
                renderLocalModelSection(
                  "tts",
                  <PhSpeakerHigh
                    size={18}
                    weight="light"
                    style={{ color: "var(--color-accent)" }}
                  />,
                  "内置 TTS 引擎",
                  "基于 Qwen3-TTS 的语音合成引擎，需下载模型后使用",
                  "TTS 模型",
                )}

              {activeType.value === "vector" &&
                renderLocalModelSection(
                  "vector",
                  <PhVectorThree
                    size={18}
                    weight="light"
                    style={{ color: "var(--color-accent)" }}
                  />,
                  "内置向量引擎",
                  "素材库向量嵌入模型，需下载模型后使用",
                  "向量模型",
                )}

              {activeType.value === "llm" && (
                <div
                  style={{
                    fontSize: "12px",
                    fontWeight: 500,
                    marginBottom: "8px",
                    color: "var(--color-text-secondary)",
                    display: "flex",
                    alignItems: "center",
                    gap: "6px",
                  }}
                >
                  外部供应商
                </div>
              )}
              {activeType.value === "llm" && filtered.length === 0 && (
                <div class="empty-state">
                  <PhKey size={28} weight="light" style={{ opacity: 0.25 }} />
                  <div>暂无外部 LLM 供应商</div>
                </div>
              )}
              {activeType.value === "llm" && filtered.length > 0 && (
                <div class="provider-scroll-area" onScroll={handleListScroll}>
                  {filtered.map((p) => {
                    const isSelected = selectedNames.value.has(p.provider_name);
                    return (
                      <div
                        key={p.id}
                        class={`provider-item ${p.active ? "provider-item-default" : ""} ${selectMode.value && isSelected ? "provider-item-selected" : ""}`}
                        onClick={() => selectMode.value && toggleSelect(p.provider_name)}
                        style={selectMode.value ? { cursor: "pointer" } : undefined}
                      >
                        {selectMode.value && (
                          <span style={{ marginRight: "8px", flexShrink: 0 }}>
                            {isSelected ? (
                              <PhCheckSquare
                                size={16}
                                weight="fill"
                                style={{ color: "var(--color-accent)" }}
                              />
                            ) : (
                              <PhSquare size={16} weight="light" />
                            )}
                          </span>
                        )}
                        <div class="provider-item-left">
                          <div class="provider-item-info">
                            <span class="provider-item-name">{p.provider_name}</span>
                            {providerModels.value[p.provider_name] &&
                            providerModels.value[p.provider_name].length > 0 ? (
                              <select
                                class="provider-item-model-select"
                                value={p.model_id}
                                onChange={(e) =>
                                  handleModelChange(
                                    p.id,
                                    p.kind,
                                    p.api_url,
                                    (e.target as HTMLSelectElement).value,
                                    p.active,
                                  )
                                }
                                onClick={(e) => e.stopPropagation()}
                              >
                                {providerModels.value[p.provider_name].map((m) => (
                                  <option key={m} value={m}>
                                    {m}
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <span class="provider-item-model">
                                {p.model_id || "未指定模型"}
                              </span>
                            )}
                          </div>
                          <div class="provider-item-meta">
                            <span class="provider-item-key">
                              {maskKey(p.api_key)}
                            </span>
                            {p.api_url && (
                              <span class="provider-item-url">{p.api_url}</span>
                            )}
                          </div>
                          {testResult.value?.name === p.provider_name && (
                            <div
                              class={`provider-test-result ${testResult.value.success ? "success" : "error"}`}
                            >
                              {testResult.value.success ? (
                                <>
                                  <PhCheck size={12} weight="bold" /> 连接成功
                                  {testResult.value.models &&
                                    testResult.value.models.length > 0 && (
                                      <span style={{ opacity: 0.7, marginLeft: "4px" }}>
                                        ({testResult.value.models.length} 个模型可用)
                                      </span>
                                    )}
                                </>
                              ) : (
                                <>
                                  <PhX size={12} weight="bold" /> {testResult.value.error}
                                </>
                              )}
                            </div>
                          )}
                        </div>
                        {!selectMode.value && (
                          <div class="provider-item-actions">
                            {p.active && (
                              <Tag variant="success" size="sm">
                                默认
                              </Tag>
                            )}
                            {!p.active && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => handleActivate(p.id)}
                                title="设为默认"
                              >
                                设为默认
                              </Button>
                            )}
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => openEditModal(p)}
                              title="编辑"
                            >
                              <PhPencilSimple size={14} weight="light" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => handleTest(p.provider_name, p.api_url, p.api_key)}
                              title="测试连接"
                              style={
                                testing.value === p.provider_name
                                  ? { opacity: 0.5, pointerEvents: "none" as const }
                                  : undefined
                              }
                            >
                              <PhLightning size={14} weight="light" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => handleDelete(p)}
                              title="删除"
                            >
                              <PhTrash size={14} weight="light" />
                            </Button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {providersLoading.value && (
                    <div class="provider-load-hint">加载中...</div>
                  )}
                </div>
              )}
            </Card>

            {activeType.value === "llm" && (
              <Modal
                open={showForm.value}
                onClose={() => { showForm.value = false; editingId.value = null; }}
                title={editingId.value !== null ? "编辑 LLM 供应商" : "添加 LLM 供应商"}
              >
                {{
                default: () => (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "var(--space-md)",
                  }}
                >
                  <div>
                    <label style={labelStyle}>选择供应商</label>
                    <div
                      style={{
                        display: "flex",
                        flexWrap: "wrap",
                        gap: "8px",
                      }}
                    >
                      {LLM_PRESETS.map((p) => (
                        <button
                          key={p.id}
                          class={`provider-preset-chip ${selectedPreset.value === p.id ? "active" : ""}`}
                          onClick={() => handlePresetChange(p.id)}
                          title={
                            p.hint ? `获取 API Key：${p.hint}` : undefined
                          }
                        >
                          {p.icon ? (
                            <img
                              src={p.icon}
                              alt={p.name}
                              class="provider-preset-logo"
                              style={p.iconBg ? { backgroundColor: p.iconBg, padding: "5px" } : undefined}
                            />
                          ) : (
                            <span class="provider-preset-logo provider-preset-logo-fallback">
                              +
                            </span>
                          )}
                          <span class="provider-preset-name">{p.name}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <Input
                    label="供应商 / 平台"
                    placeholder="如 DeepSeek、OpenAI、Moonshot Kimi"
                    value={form.name}
                    onUpdate:value={(v: string) => (form.name = v)}
                  />
                  <Input
                    label="Base URL"
                    placeholder="https://api.deepseek.com"
                    value={form.base_url}
                    onUpdate:value={(v: string) => (form.base_url = v)}
                  />
                  <Input
                    label="API Key"
                    placeholder={editingId.value !== null ? "留空不修改原 Key" : "sk-..."}
                    type="password"
                    value={form.api_key}
                    onUpdate:value={(v: string) => (form.api_key = v)}
                  />

                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                    }}
                  >
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={modalTesting.value}
                      disabled={!form.base_url || !form.api_key}
                      onClick={handleModalTest}
                    >
                      <PhLightning size={14} weight="light" />
                      测试连接
                    </Button>
                    {modalTestResult.value && (
                      <span
                        style={{
                          fontSize: "12px",
                          color: modalTestResult.value.success
                            ? "var(--color-success)"
                            : "var(--color-error)",
                        }}
                      >
                        {modalTestResult.value.success
                          ? `连接成功${modalTestResult.value.models?.length ? ` (${modalTestResult.value.models.length} 个模型可用)` : ""}`
                          : modalTestResult.value.error}
                      </span>
                    )}
                  </div>

                  {modalTestResult.value?.success &&
                  modalTestResult.value.models &&
                  modalTestResult.value.models.length > 0 ? (
                    <div>
                      <label style={labelStyle}>模型 ID</label>
                      <select
                        class="provider-model-select"
                        value={form.model}
                        onChange={(e) =>
                          (form.model = (e.target as HTMLSelectElement).value)
                        }
                      >
                        {modalTestResult.value.models.map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <Input
                      label="模型 ID"
                      placeholder="如 deepseek-chat、gpt-4.1、kimi-k2.6"
                      value={form.model}
                      onUpdate:value={(v: string) => (form.model = v)}
                    />
                  )}

                  <Input
                    label="上下文长度"
                    placeholder="留空则自动检测"
                    type="number"
                    value={form.context_length}
                    onUpdate:value={(v: string) => (form.context_length = v)}
                  />
                  <span
                    style={{
                      fontSize: "11px",
                      color: "var(--color-text-muted)",
                      marginTop: "-8px",
                    }}
                  >
                    仅在自动检测失败时手动填写（如私有部署模型）
                  </span>

                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      fontSize: "12px",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={form.is_default}
                      onChange={(e) =>
                        (form.is_default = (e.target as HTMLInputElement).checked)
                      }
                      style={{ accentColor: "var(--color-accent)" }}
                    />
                    设为默认供应商
                  </label>
                </div>
                ),
                footer: () => (
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "flex-end",
                      gap: "var(--space-sm)",
                    }}
                  >
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => { showForm.value = false; editingId.value = null; }}
                    >
                      取消
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleSubmit}
                      disabled={editingId.value === null ? (!form.name || !form.api_key) : !form.name}
                    >
                      {editingId.value !== null ? "保存修改" : "保存"}
                    </Button>
                  </div>
                ),
                }}
              </Modal>
            )}
          </div>
        </PageLoader>
      );
    };
  },
});
