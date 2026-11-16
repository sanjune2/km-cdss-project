import numpy as np
import torch
import torch.nn.functional as F
from huggingface_hub import snapshot_download
from transformers import AutoModel, AutoTokenizer


MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
EMBEDDING_DIM = 384
MAX_INPUT_TOKENS = 512


class E5Embedder:
    def __init__(self) -> None:
        model_path = snapshot_download(
            repo_id=MODEL_ID,
            revision=MODEL_REVISION,
            local_files_only=True,
        )

        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            use_fast=True,
            local_files_only=True,
            trust_remote_code=False,
        )
        self.model = AutoModel.from_pretrained(
            model_path,
            local_files_only=True,
            use_safetensors=True,
            trust_remote_code=False,
        )
        self.model.to(device="cpu", dtype=torch.float32)
        self.model.eval()

        if self.model.config.hidden_size != EMBEDDING_DIM:
            raise ValueError("E5 모델의 출력 차원이 384가 아닙니다.")

    def encode_query(self, symptoms: str) -> np.ndarray:
        text = symptoms.strip()
        if not text:
            raise ValueError("증상을 입력해주세요.")

        batch = self.tokenizer(
            "query: " + text,
            return_tensors="pt",
            truncation=False,
        )
        if batch["input_ids"].shape[1] > MAX_INPUT_TOKENS:
            raise ValueError("증상이 E5 입력 한도 512토큰을 초과했습니다.")

        with torch.inference_mode():
            hidden = self.model(**batch).last_hidden_state
            mask = batch["attention_mask"][..., None].bool()
            pooled = hidden.masked_fill(~mask, 0.0).sum(dim=1)
            pooled = pooled / batch["attention_mask"].sum(dim=1)[..., None]
            normalized = F.normalize(pooled, p=2, dim=1)

        vector = normalized[0].cpu().numpy()
        if vector.shape != (EMBEDDING_DIM,) or not np.isfinite(vector).all():
            raise ValueError("E5 입력 벡터 생성 결과가 올바르지 않습니다.")

        norm = float(np.linalg.norm(vector))
        if abs(norm - 1.0) > 1e-5:
            raise ValueError("E5 입력 벡터가 정상적으로 정규화되지 않았습니다.")

        return vector