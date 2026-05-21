#type: ignore


from fastapi import APIRouter

router = APIRouter(tags=["models"])

AVAILABLE_MODELS = [
    # ── Meta (Llama) ──
    {"id": "meta/llama-3.1-8b-instruct", "name": "Llama 3.1 8B (Fast)", "provider": "meta", "category": "chat"},
    {"id": "meta/llama-4-maverick-17b-128e-instruct", "name": "Llama 4 Maverick", "provider": "meta", "category": "chat"},
    {"id": "meta/llama-3.3-70b-instruct", "name": "Llama 3.3 70B", "provider": "meta", "category": "chat"},
    {"id": "meta/llama-3.1-70b-instruct", "name": "Llama 3.1 70B", "provider": "meta", "category": "chat"},
    # ── DeepSeek ──
    {"id": "deepseek-ai/deepseek-v4-pro", "name": "DeepSeek V4 Pro", "provider": "deepseek", "category": "chat"},
    {"id": "deepseek-ai/deepseek-v4-flash", "name": "DeepSeek V4 Flash", "provider": "deepseek", "category": "chat"},
    # ── Google ──
    {"id": "google/gemma-4-31b-it", "name": "Gemma 4 31B", "provider": "google", "category": "chat"},
    {"id": "google/gemma-3-12b-it", "name": "Gemma 3 12B", "provider": "google", "category": "chat"},
    {"id": "google/gemma-3n-e4b-it", "name": "Gemma 3n E4B", "provider": "google", "category": "chat"},
    # ── Mistral ──
    {"id": "mistralai/mistral-large-3-675b-instruct-2512", "name": "Mistral Large 3 675B", "provider": "mistral", "category": "chat"},
    {"id": "mistralai/mistral-medium-3.5-128b", "name": "Mistral Medium 3.5 128B", "provider": "mistral", "category": "chat"},
    {"id": "mistralai/mistral-small-4-119b-2603", "name": "Mistral Small 4 119B", "provider": "mistral", "category": "chat"},
    {"id": "mistralai/mistral-nemotron", "name": "Mistral Nemotron", "provider": "mistral", "category": "chat"},
    # ── NVIDIA ──
    {"id": "nvidia/llama-3.3-nemotron-super-49b-v1.5", "name": "Nemotron Super 49B v1.5", "provider": "nvidia", "category": "chat"},
    {"id": "nvidia/nemotron-3-super-120b-a12b", "name": "Nemotron 3 Super 120B", "provider": "nvidia", "category": "chat"},
    {"id": "nvidia/nvidia-nemotron-nano-9b-v2", "name": "Nemotron Nano 9B v2", "provider": "nvidia", "category": "chat"},
    # ── Qwen ──
    {"id": "qwen/qwen3-coder-480b-a35b-instruct", "name": "Qwen3 Coder 480B", "provider": "qwen", "category": "code"},
    {"id": "qwen/qwen3.5-397b-a17b", "name": "Qwen 3.5 397B", "provider": "qwen", "category": "chat"},
    {"id": "qwen/qwen3-next-80b-a3b-instruct", "name": "Qwen3 Next 80B", "provider": "qwen", "category": "chat"},
    {"id": "qwen/qwen3.5-122b-a10b", "name": "Qwen 3.5 122B", "provider": "qwen", "category": "chat"},
    # ── Other providers ──
    {"id": "moonshotai/kimi-k2.6", "name": "Kimi K2.6", "provider": "moonshot", "category": "chat"},
    {"id": "openai/gpt-oss-120b", "name": "GPT-OSS 120B", "provider": "openai", "category": "chat"},
    {"id": "openai/gpt-oss-20b", "name": "GPT-OSS 20B (Fast)", "provider": "openai", "category": "chat"},
    {"id": "stepfun-ai/step-3.5-flash", "name": "Step 3.5 Flash", "provider": "stepfun", "category": "chat"},
    {"id": "minimaxai/minimax-m2.7", "name": "MiniMax M2.7", "provider": "minimax", "category": "chat"},
    {"id": "z-ai/glm-5.1", "name": "GLM 5.1", "provider": "zhipu", "category": "chat"},
    {"id": "bytedance/seed-oss-36b-instruct", "name": "Seed OSS 36B", "provider": "bytedance", "category": "chat"},
    # ── Vision ──
    {"id": "meta/llama-3.2-90b-vision-instruct", "name": "Llama 3.2 90B Vision", "provider": "meta", "category": "vision"},
    {"id": "meta/llama-3.2-11b-vision-instruct", "name": "Llama 3.2 11B Vision", "provider": "meta", "category": "vision"},
    {"id": "microsoft/phi-4-multimodal-instruct", "name": "Phi-4 Multimodal", "provider": "microsoft", "category": "vision"},
    {"id": "nvidia/cosmos-reason2-8b", "name": "Cosmos Reason2 8B", "provider": "nvidia", "category": "vision"},
]

# MoE recommended model pairings — orchestrator (smart planner) + sub-agent (fast executor)
MOE_MODEL_PRESETS = [
    {
        "id": "power",
        "name": "Maximum Power",
        "orchestrator": "deepseek-ai/deepseek-v4-pro",
        "subagent": "meta/llama-3.3-70b-instruct",
        "description": "DeepSeek V4 Pro plans, Llama 70B executes — best quality",
    },
    {
        "id": "balanced",
        "name": "Balanced",
        "orchestrator": "meta/llama-3.3-70b-instruct",
        "subagent": "meta/llama-3.1-8b-instruct",
        "description": "Llama 70B plans, Llama 8B executes — good quality, fast",
    },
    {
        "id": "fast",
        "name": "Ultrafast",
        "orchestrator": "meta/llama-3.1-8b-instruct",
        "subagent": "meta/llama-3.1-8b-instruct",
        "description": "Both 8B — fastest possible, for simple requests",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek Power",
        "orchestrator": "deepseek-ai/deepseek-v4-pro",
        "subagent": "meta/llama-3.3-70b-instruct",
        "description": "DeepSeek V4 Pro plans, Llama 70B executes",
    },
]


@router.get("/models")
async def list_models():
    return {"models": AVAILABLE_MODELS}


@router.get("/models/moe")
async def list_moe_presets():
    """Return recommended MoE model pairings for orchestrator + sub-agents."""
    return {"presets": MOE_MODEL_PRESETS}