from __future__ import annotations

import sys
import types

import pytest
from homefund_embed.backends import choose_device


@pytest.fixture
def fake_torch(monkeypatch: pytest.MonkeyPatch):
    def install(cuda: bool) -> None:
        torch = types.ModuleType("torch")
        torch.cuda = types.SimpleNamespace(is_available=lambda: cuda)  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "torch", torch)

    return install


def test_auto_uses_cuda_with_fp16_when_available(fake_torch) -> None:
    fake_torch(cuda=True)
    choice = choose_device("auto", "auto")
    assert (choice.device, choice.fp16) == ("cuda:0", True)


def test_auto_falls_back_to_cpu_without_fp16(fake_torch) -> None:
    fake_torch(cuda=False)
    choice = choose_device("auto", "auto")
    assert (choice.device, choice.fp16) == ("cpu", False)


def test_auto_without_torch_is_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)
    assert choose_device().device == "cpu"


def test_explicit_device_and_fp16_override() -> None:
    assert choose_device("cuda", "auto").device == "cuda:0"
    assert choose_device("mps", "auto").fp16 is False
    assert choose_device("cpu", "on").fp16 is True
