import torch
from sentence_transformers import SentenceTransformer
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings


class EmbeddingModel(EmbeddingFunction):
    def __init__(self, model_path: str):  # type: ignore
        super().__init__()

        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.model_path = model_path
        print(f"正在加载模型: {model_path} 到设备: {device}...")
        try:
            self.model = SentenceTransformer(model_path, device=device)
            self.model.eval()
            print(f"模型 {model_path} 加载完成。")
        except Exception as e:
            print(e)
            self.model = None
            print(f"模型 {model_path} 加载失败。")



    def __call__(self, input_documents: Documents) -> Embeddings:
        if not self.model:
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            self.model = SentenceTransformer(self.model_path, device=device)
            self.model.eval()
        embeddings = self.model.encode(
            input_documents,
            convert_to_numpy=True,
            show_progress_bar=False
        )
        return embeddings.tolist()
