"""Wire models for POST /embed and POST /rerank. Shared by the server and the client."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

DENSE_DIM = 1024
MAX_TEXTS = 256  # per request; EmbedClient splits larger inputs into batches


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SparseWeights(_Model):
    """BGE-M3 lexical weights: vocabulary token ids and their weights, ids ascending."""

    indices: list[int]
    values: list[float]

    @model_validator(mode="after")
    def _same_length(self) -> SparseWeights:
        if len(self.indices) != len(self.values):
            raise ValueError("indices and values must have the same length")
        return self

    @classmethod
    def from_mapping(cls, weights: dict[int, float]) -> SparseWeights:
        items = sorted(weights.items())
        return cls(indices=[i for i, _ in items], values=[v for _, v in items])

    def as_dict(self) -> dict[int, float]:
        return dict(zip(self.indices, self.values, strict=True))


class EmbedRequest(_Model):
    texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)
    sparse: bool = Field(default=False, description="Also return BGE-M3 lexical weights")


class EmbedResponse(_Model):
    model: str
    dim: int = DENSE_DIM
    dense: list[list[float]] = Field(description="One L2-normalised 1024-d vector per text")
    sparse: list[SparseWeights] | None = Field(
        default=None, description="One entry per text when the request asked for sparse"
    )


class RerankRequest(_Model):
    query: str = Field(min_length=1)
    passages: list[str] = Field(min_length=1, max_length=MAX_TEXTS)


class RerankResponse(_Model):
    model: str
    scores: list[float] = Field(description="Sigmoid-normalised relevance, one per passage")


class Health(_Model):
    status: str
    device: str
    fp16: bool
    embed_model: str
    rerank_model: str
