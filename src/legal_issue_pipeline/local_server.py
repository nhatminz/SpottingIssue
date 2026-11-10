"""Real Transformers + CUDA OpenAI-compatible smoke server, no simulated responses.

Single-GPU serial generation; vLLM/SGLang should be used for production throughput.
Optional dependencies are isolated from the normal API-only pipeline.
"""
from __future__ import annotations
import asyncio
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4


def main():
    import torch
    import uvicorn
    from fastapi import FastAPI, HTTPException
    from lmformatenforcer import JsonSchemaParser
    from lmformatenforcer.characterlevelparser import CharacterLevelParserConfig
    from lmformatenforcer.consts import COMPLETE_ALPHABET
    from lmformatenforcer.integrations.transformers import build_transformers_prefix_allowed_tokens_fn, build_token_enforcer_tokenizer_data
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(int(os.environ.get("QWEN_CPU_THREADS", "4")))
    model_path = os.environ["QWEN_MODEL_PATH"]
    model_id = os.environ.get("QWEN_SERVED_MODEL", "qwen3-4b")
    max_context = int(os.environ.get("QWEN_MAX_MODEL_LEN", "32768"))
    lock = asyncio.Lock()
    state = {}

    @asynccontextmanager
    async def lifespan(app):
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable; local smoke server requires GPU")
        state["tokenizer"] = AutoTokenizer.from_pretrained(model_path,local_files_only=True,trust_remote_code=False)
        state["tokenizer_data"] = build_token_enforcer_tokenizer_data(state["tokenizer"])
        state["model"] = AutoModelForCausalLM.from_pretrained(model_path,local_files_only=True,trust_remote_code=False,
            dtype=getattr(torch,os.environ.get("QWEN_DTYPE","bfloat16")),device_map="cuda",attn_implementation="sdpa").eval()
        print(f"Loaded {model_id} on {torch.cuda.get_device_name(0)}; context={max_context}", flush=True)
        yield
        state.clear()
        torch.cuda.empty_cache()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"loaded": bool(state), "model":model_id}

    @app.get("/v1/models")
    async def models():
        return {"object":"list", "data":[{"id":model_id,"object":"model","owned_by":"local"}]}

    def generate(body):
        tokenizer,model = state["tokenizer"],state["model"]
        thinking = body.get("chat_template_kwargs",{}).get("enable_thinking",True)
        encoded = tokenizer.apply_chat_template(body["messages"],tokenize=True,add_generation_prompt=True,
            return_tensors="pt",return_dict=True,enable_thinking=thinking).to(model.device)
        input_tokens = encoded["input_ids"].shape[-1]
        max_tokens = int(body.get("max_tokens",4096))
        if input_tokens+max_tokens > max_context:
            raise ValueError("Input plus output budget exceeds local server context")
        kwargs = {"max_new_tokens":max_tokens,"do_sample":body.get("temperature",0)>0,
                  "pad_token_id":tokenizer.eos_token_id,"repetition_penalty":float(body.get("repetition_penalty",1.0))}
        if kwargs["do_sample"]:
            kwargs.update(temperature=body["temperature"],top_p=body.get("top_p",1.0))
        if body.get("seed") is not None:
            torch.manual_seed(body["seed"])
        fmt = body.get("response_format",{})
        if fmt.get("type") in ["json_schema","json_object"] and not thinking:
            schema = fmt["json_schema"]["schema"] if fmt["type"] == "json_schema" else None
            # LMFE's default alphabet is ASCII: explicitly include Vietnamese and
            # all printable source characters, otherwise accented tokens dead-end.
            unicode_chars = "".join(chr(n) for n in list(range(0xA0,0x250))+list(range(0x1E00,0x1F00))+list(range(0x2000,0x2070)) if chr(n).isprintable())
            source_chars = "".join(c for m in body["messages"] for c in m["content"] if c.isprintable())
            alphabet = "".join(sorted(set(COMPLETE_ALPHABET+unicode_chars+source_chars)))
            parser_config = CharacterLevelParserConfig(alphabet=alphabet,max_json_array_length=0)
            kwargs["prefix_allowed_tokens_fn"] = build_transformers_prefix_allowed_tokens_fn(state["tokenizer_data"],JsonSchemaParser(schema,config=parser_config))
        stop = body.get("stop")
        if stop:
            kwargs.update(stop_strings=stop,tokenizer=tokenizer)
        start = time.monotonic()
        from transformers import StoppingCriteria,StoppingCriteriaList
        class Progress(StoppingCriteria):
            def __call__(self,input_ids,scores,**kwargs):
                generated = input_ids.shape[-1]-input_tokens
                if generated and generated % 512 == 0:
                    print(f"generation progress tokens={generated}/{max_tokens} seconds={time.monotonic()-start:.1f}",flush=True)
                return False
        kwargs["stopping_criteria"] = StoppingCriteriaList([Progress()])
        with torch.inference_mode():
            result = model.generate(**encoded,**kwargs)
        new = result[0,input_tokens:]
        content = tokenizer.decode(new,skip_special_tokens=True)
        finish = "length" if len(new) >= max_tokens else "stop"
        print(f"request tokens={input_tokens}+{len(new)} seconds={time.monotonic()-start:.2f} finish={finish}",flush=True)
        return {"id":"chatcmpl-"+uuid4().hex,"object":"chat.completion","created":int(time.time()),"model":model_id,
                "choices":[{"index":0,"message":{"role":"assistant","content":content},"finish_reason":finish}],
                "usage":{"prompt_tokens":input_tokens,"completion_tokens":len(new),"total_tokens":input_tokens+len(new)}}

    @app.post("/v1/chat/completions")
    async def completions(body: dict):
        if body.get("model") != model_id:
            raise HTTPException(404,"Unknown served model ID")
        if body.get("stream"):
            raise HTTPException(400,"This smoke server supports non-streaming requests")
        try:
            async with lock:
                return await asyncio.to_thread(generate,body)
        except (ValueError,KeyError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from None

    uvicorn.run(app,host=os.environ.get("QWEN_HOST","127.0.0.1"),port=int(os.environ.get("QWEN_PORT","8001")),access_log=False)


if __name__ == "__main__":
    main()
