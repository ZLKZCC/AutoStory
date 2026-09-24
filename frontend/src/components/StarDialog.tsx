import { defineComponent, onMounted, ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import Modal from "./Modal";
import Button from "./Button";
import { PhGithubLogo, PhStar } from "@phosphor-icons/vue";
import "./StarDialog.css";

const REPO_URL = "https://github.com/ZLKZCC/AutoStory";
const SHOWN_KEY = "autostory:star-dialog-shown";

const openRepo = () => {
  invoke("open_url", { url: REPO_URL }).catch(() => {
    window.open(REPO_URL, "_blank");
  });
};

export default defineComponent({
  name: "StarDialog",
  setup() {
    const open = ref(false);

    onMounted(() => {
      if (!localStorage.getItem(SHOWN_KEY)) open.value = true;
    });

    const close = () => {
      localStorage.setItem(SHOWN_KEY, "1");
      open.value = false;
    };

    return () => (
      <Modal open={open.value} onClose={close} title="关于 AutoStory" width={420}>
        {{
          default: () => (
            <div class="star-dialog">
              <div class="star-dialog-badge">
                <PhGithubLogo size={26} weight="fill" />
              </div>
              <p class="star-dialog-text">
                AutoStory 是一个开源项目，源码托管在 GitHub。如果它对你有帮助，欢迎为仓库点一个免费的
                Star，这是对开发者持续完善它的鼓励。
              </p>
              <button class="star-dialog-link" onClick={openRepo} title="打开 GitHub 仓库">
                {REPO_URL}
              </button>
            </div>
          ),
          footer: () => (
            <div class="star-dialog-footer">
              <Button size="sm" variant="ghost" onClick={close}>
                以后再说
              </Button>
              <Button
                size="sm"
                variant="primary"
                icon={<PhStar size={14} weight="fill" />}
                onClick={() => {
                  openRepo();
                  close();
                }}
              >
                给一个 Star
              </Button>
            </div>
          ),
        }}
      </Modal>
    );
  },
});
