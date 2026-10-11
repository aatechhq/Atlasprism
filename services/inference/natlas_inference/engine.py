"""Model loading and generation.

Kept behind a tiny interface so the HTTP layer can be tested without torch
installed and without downloading 8B parameters. Everything Hugging
Face-specific is in `TransformersEngine`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class Generation:
    text: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class Engine(Protocol):
    model_id: str

    @property
    def loaded(self) -> bool: ...

    def load(self) -> None: ...

    def generate(self, messages: list[dict[str, str]], *, max_new_tokens: int,
                 temperature: float, language: str | None = None) -> Generation: ...


class TransformersEngine:
    """Loads `MODEL_ID` with 4-bit NF4 quantization and generates from it.

    Imports torch/transformers lazily inside `load()`, so importing this module
    on a laptop costs nothing and cannot accidentally pull the model.
    """

    def __init__(self, model_id: str, *, hf_token: str = "", load_in_4bit: bool = True,
                 allow_cpu: bool = False) -> None:
        self.model_id = model_id
        self._hf_token = hf_token or None
        self._load_in_4bit = load_in_4bit
        self._allow_cpu = allow_cpu
        self._model = None
        self._tokenizer = None

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    def load(self) -> None:
        if self.loaded:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        cuda = torch.cuda.is_available()
        if not cuda and not self._allow_cpu:
            raise RuntimeError(
                "No CUDA GPU detected. This service loads an 8B model and must run on "
                "a GPU host (Colab T4 or dedicated GPU). Set ALLOW_CPU=1 only for a "
                "deliberate CPU smoke test."
            )

        quant = None
        if self._load_in_4bit and cuda:
            # 4-bit NF4 with double quantization; bfloat16 compute.
            quant = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, token=self._hf_token)
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            token=self._hf_token,
            quantization_config=quant,
            device_map="auto" if cuda else None,
            dtype=torch.bfloat16 if cuda else torch.float32,
        )
        self._model.eval()
        if self._tokenizer.pad_token_id is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

    def generate(self, messages, *, max_new_tokens: int, temperature: float,
                 language: str | None = None) -> Generation:
        if not self.loaded:
            self.load()
        import torch

        prompt = self._build_prompt(messages, language)
        inputs = self._tokenizer(prompt, return_tensors="pt")
        if hasattr(self._model, "device"):
            inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        started = time.perf_counter()
        with torch.no_grad():
            output = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=temperature > 0,
                temperature=temperature if temperature > 0 else None,
                pad_token_id=self._tokenizer.pad_token_id,
            )
        latency_ms = int((time.perf_counter() - started) * 1000)

        prompt_len = int(inputs["input_ids"].shape[-1])
        generated = output[0][prompt_len:]
        text = self._tokenizer.decode(generated, skip_special_tokens=True).strip()
        completion_tokens = int(generated.shape[-1])
        return Generation(
            text=text,
            finish_reason="length" if completion_tokens >= max_new_tokens else "stop",
            prompt_tokens=prompt_len,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )

    def _build_prompt(self, messages: list[dict[str, str]], language: str | None) -> str:
        """Use the model's own chat template when it has one."""
        msgs = list(messages)
        if language:
            # Advisory only: a hint prepended to the system turn, not a guarantee.
            hint = f"Respond in the language with ISO code '{language}'."
            if msgs and msgs[0].get("role") == "system":
                msgs[0] = {"role": "system", "content": f"{msgs[0]['content']}\n{hint}"}
            else:
                msgs.insert(0, {"role": "system", "content": hint})
        template = getattr(self._tokenizer, "chat_template", None)
        if template:
            return self._tokenizer.apply_chat_template(
                msgs, tokenize=False, add_generation_prompt=True
            )
        parts = [f"{m.get('role', 'user').upper()}: {m.get('content', '')}" for m in msgs]
        parts.append("ASSISTANT:")
        return "\n".join(parts)
