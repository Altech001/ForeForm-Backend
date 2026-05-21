# type: ignore
"""
MoE (Mixture-of-Experts) Sequential Agent System
=================================================
An orchestrator agent that decomposes user requests into sub-tasks,
dispatches them to specialised sub-agents one at a time, and
aggregates the results into a single coherent response.

Sub-agents:
  • PexelsImageAgent  — image search via Pexels API
  • DuckDuckGoAgent   — web / news search via DuckDuckGo
  • FormAnalystAgent  — deep analysis of the user's ForeForm data
  • ReasoningAgent    — general-purpose reasoning / Q&A (NVIDIA AI)

All LLM calls go through the NVIDIA Integrate API (OpenAI-compatible).
"""

import json
import os
import logging
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx
from openai import OpenAI

logger = logging.getLogger("moe_agents")

# ═══════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Default orchestrator model — a large, smart model for planning
ORCHESTRATOR_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

# Default sub-agent model — fast and efficient for execution
SUBAGENT_MODEL = "meta/llama-3.3-70b-instruct"

PEXELS_API_URL = "https://api.pexels.com/v1/search"
DUCKDUCKGO_SEARCH_URL = "https://html.duckduckgo.com/html/"


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    PEXELS_IMAGE = "pexels_image"
    DUCKDUCKGO = "duckduckgo"
    FORM_ANALYST = "form_analyst"
    REASONING = "reasoning"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ═══════════════════════════════════════════════════════════════
#  Data structures
# ═══════════════════════════════════════════════════════════════

@dataclass
class SubTask:
    """A single unit of work assigned by the orchestrator."""
    id: int
    agent: AgentRole
    instruction: str
    depends_on: List[int] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent": self.agent.value,
            "instruction": self.instruction,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "duration_ms": (
                int((self.finished_at - self.started_at) * 1000)
                if self.started_at and self.finished_at
                else None
            ),
        }


@dataclass
class MoEResult:
    """Final aggregated result from the MoE pipeline."""
    answer: str
    sub_tasks: List[SubTask]
    total_duration_ms: int
    orchestrator_reasoning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "orchestrator_reasoning": self.orchestrator_reasoning,
            "sub_tasks": [t.to_dict() for t in self.sub_tasks],
            "total_duration_ms": self.total_duration_ms,
        }


# ═══════════════════════════════════════════════════════════════
#  NVIDIA LLM helper (shared by orchestrator + sub-agents)
# ═══════════════════════════════════════════════════════════════

def _nvidia_chat(
    api_key: str,
    messages: List[Dict[str, str]],
    *,
    model: str = SUBAGENT_MODEL,
    temperature: float = 0.4,
    max_tokens: int = 4096,
) -> str:
    """Quick fire-and-forget NVIDIA chat completion."""
    client = OpenAI(base_url=NVIDIA_BASE_URL, api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
    )
    return completion.choices[0].message.content or ""


# ═══════════════════════════════════════════════════════════════
#  SUB-AGENTS
# ═══════════════════════════════════════════════════════════════

class PexelsImageAgent:
    """Searches Pexels for royalty-free images."""

    def __init__(self, pexels_api_key: str, nvidia_api_key: str):
        self.pexels_key = pexels_api_key
        self.nvidia_key = nvidia_api_key

    def run(self, instruction: str, context: str = "") -> str:
        # Step 1: Extract the best search query from the instruction
        query = self._extract_query(instruction)
        if not query:
            return json.dumps({"error": "Could not determine image search query"})

        # Step 2: Call Pexels API
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    PEXELS_API_URL,
                    headers={"Authorization": self.pexels_key},
                    params={"query": query, "per_page": 6, "orientation": "landscape"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            return json.dumps({"error": f"Pexels API error: {str(e)}"})

        photos = data.get("photos", [])
        if not photos:
            return json.dumps({"query": query, "images": [], "note": "No images found"})

        results = []
        for p in photos:
            results.append({
                "id": p["id"],
                "alt": p.get("alt", ""),
                "photographer": p.get("photographer", ""),
                "src_medium": p["src"]["medium"],
                "src_large": p["src"]["large"],
                "src_original": p["src"]["original"],
                "url": p["url"],
            })

        return json.dumps({"query": query, "total_results": data.get("total_results", 0), "images": results})

    def _extract_query(self, instruction: str) -> str:
        """Use a quick LLM call to turn a natural-language instruction into a concise Pexels search query."""
        try:
            result = _nvidia_chat(
                self.nvidia_key,
                [
                    {"role": "system", "content": "Extract a short image search query (2-5 words) from the user instruction. Return ONLY the query, nothing else."},
                    {"role": "user", "content": instruction},
                ],
                model="meta/llama-3.1-8b-instruct",
                temperature=0.1,
                max_tokens=30,
            )
            return result.strip().strip('"').strip("'")
        except Exception:
            # Fallback: use the instruction directly
            return instruction[:80]


class DuckDuckGoAgent:
    """Web search via DuckDuckGo (no API key required)."""

    def __init__(self, nvidia_api_key: str):
        self.nvidia_key = nvidia_api_key

    def run(self, instruction: str, context: str = "") -> str:
        query = self._extract_query(instruction)
        if not query:
            return json.dumps({"error": "Could not determine search query"})

        try:
            results = self._search_ddg(query)
        except Exception as e:
            return json.dumps({"error": f"DuckDuckGo search error: {str(e)}"})

        if not results:
            return json.dumps({"query": query, "results": [], "note": "No results found"})

        # Summarise the results with LLM
        summary = self._summarise(instruction, results)
        return json.dumps({
            "query": query,
            "result_count": len(results),
            "results": results[:5],
            "summary": summary,
        })

    def _search_ddg(self, query: str) -> List[Dict[str, str]]:
        """Perform a DuckDuckGo HTML search and parse results."""
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=8))
            results = []
            for r in raw:
                results.append({
                    "title": r.get("title", ""),
                    "body": r.get("body", ""),
                    "href": r.get("href", ""),
                })
            return results
        except ImportError:
            # Fallback: basic HTTP search
            return self._search_ddg_http(query)

    def _search_ddg_http(self, query: str) -> List[Dict[str, str]]:
        """Basic fallback using the DuckDuckGo instant answer API."""
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": 1},
                )
                resp.raise_for_status()
                data = resp.json()

            results = []
            # Abstract text
            if data.get("AbstractText"):
                results.append({
                    "title": data.get("Heading", ""),
                    "body": data["AbstractText"],
                    "href": data.get("AbstractURL", ""),
                })
            # Related topics
            for topic in data.get("RelatedTopics", [])[:5]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title": topic.get("Text", "")[:100],
                        "body": topic.get("Text", ""),
                        "href": topic.get("FirstURL", ""),
                    })
            return results
        except Exception:
            return []

    def _extract_query(self, instruction: str) -> str:
        try:
            result = _nvidia_chat(
                self.nvidia_key,
                [
                    {"role": "system", "content": "Extract a concise web search query (2-8 words) from the user instruction. Return ONLY the query, nothing else."},
                    {"role": "user", "content": instruction},
                ],
                model="meta/llama-3.1-8b-instruct",
                temperature=0.1,
                max_tokens=40,
            )
            return result.strip().strip('"').strip("'")
        except Exception:
            return instruction[:100]

    def _summarise(self, original_question: str, results: List[Dict[str, str]]) -> str:
        """Use LLM to summarise search results into a coherent answer."""
        try:
            results_text = "\n\n".join(
                f"**{r['title']}**\n{r['body']}\nSource: {r['href']}"
                for r in results[:5]
            )
            return _nvidia_chat(
                self.nvidia_key,
                [
                    {"role": "system", "content": "Summarise the search results below into a clear, well-structured answer to the user's question. Cite sources when relevant. Use markdown formatting."},
                    {"role": "user", "content": f"Question: {original_question}\n\nSearch Results:\n{results_text}"},
                ],
                temperature=0.3,
                max_tokens=2048,
            )
        except Exception:
            return "Could not generate summary."


class FormAnalystAgent:
    """Analyses ForeForm workspace data (forms, responses, analytics)."""

    def __init__(self, nvidia_api_key: str):
        self.nvidia_key = nvidia_api_key

    def run(self, instruction: str, context: str = "") -> str:
        if not context:
            return json.dumps({"note": "No workspace data available for analysis."})

        try:
            result = _nvidia_chat(
                self.nvidia_key,
                [
                    {
                        "role": "system",
                        "content": (
                            "You are ForeForm's expert data analyst. Analyse the workspace data below and answer the question. "
                            "Use tables, charts descriptions, and statistics. Be precise — reference actual numbers from the data. "
                            "Format your response in clean markdown."
                        ),
                    },
                    {"role": "user", "content": f"## Workspace Data\n{context}\n\n## Question\n{instruction}"},
                ],
                model=SUBAGENT_MODEL,
                temperature=0.3,
                max_tokens=4096,
            )
            return result
        except Exception as e:
            return json.dumps({"error": f"Form analysis failed: {str(e)}"})


class ReasoningAgent:
    """General-purpose reasoning and Q&A agent."""

    def __init__(self, nvidia_api_key: str, model: str = SUBAGENT_MODEL):
        self.nvidia_key = nvidia_api_key
        self.model = model

    def run(self, instruction: str, context: str = "") -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are Maxxie, ForeForm's intelligent AI assistant. "
                    "Answer the user's question thoroughly, accurately, and in well-formatted markdown. "
                    "Be helpful, concise, and proactive."
                ),
            },
        ]
        if context:
            messages.append({"role": "user", "content": f"Context:\n{context}"})
            messages.append({"role": "assistant", "content": "Got it, I have the context. What would you like to know?"})

        messages.append({"role": "user", "content": instruction})

        try:
            return _nvidia_chat(
                self.nvidia_key,
                messages,
                model=self.model,
                temperature=0.5,
                max_tokens=4096,
            )
        except Exception as e:
            return json.dumps({"error": f"Reasoning failed: {str(e)}"})


# ═══════════════════════════════════════════════════════════════
#  ORCHESTRATOR — The brain that plans and dispatches
# ═══════════════════════════════════════════════════════════════

PLANNING_PROMPT = """You are the MoE Orchestrator for ForeForm's AI system.

Your job is to decompose a user request into a sequence of sub-tasks, each assigned to a specialist agent. The sub-tasks will be executed **sequentially**, one at a time.

Available agents:
1. **pexels_image** — Searches for royalty-free images via Pexels. Use when the user needs images, photos, or visual assets.
2. **duckduckgo** — Web search via DuckDuckGo. Use when the user needs current information, research, definitions, or facts from the internet.
3. **form_analyst** — Analyses the user's ForeForm workspace data (forms, responses, analytics). Use when the question is about their forms or data.
4. **reasoning** — General-purpose reasoning, writing, coding, Q&A. Use for anything that doesn't need external tools.

Rules:
- Return a JSON array of sub-task objects.
- Each sub-task has: {"id": <int>, "agent": "<agent_name>", "instruction": "<what this agent should do>"}
- Keep it minimal — don't create unnecessary sub-tasks.
- If the request is simple, use only 1 sub-task.
- If the request needs research + images, use 2 sub-tasks (duckduckgo first, then pexels_image).
- Maximum 5 sub-tasks.
- The instruction for each sub-task should be specific and actionable.

Return ONLY the JSON array — no markdown fences, no explanation.

Examples:

User: "Find me some beautiful sunset images"
[{"id": 1, "agent": "pexels_image", "instruction": "Search for beautiful sunset landscape images"}]

User: "What's the latest on AI regulations and show me some AI robot images"
[{"id": 1, "agent": "duckduckgo", "instruction": "Search for latest AI regulation news 2025"}, {"id": 2, "agent": "pexels_image", "instruction": "Search for AI robot futuristic images"}]

User: "How many responses did my forms get last week?"
[{"id": 1, "agent": "form_analyst", "instruction": "Analyse form response counts for the past 7 days across all user forms"}]

User: "Write me a poem about the ocean"
[{"id": 1, "agent": "reasoning", "instruction": "Write a creative poem about the ocean"}]
"""

AGGREGATION_PROMPT = """You are the MoE Aggregator for ForeForm's AI assistant (Maxxie).

You have received results from multiple specialist sub-agents. Your job is to combine them into a single, polished, well-formatted response for the user.

Rules:
- Use clean markdown formatting.
- If images were found, embed them using markdown image syntax: ![alt](url)
- If web search results are included, cite sources naturally.
- If form data analysis was done, present it clearly with tables if appropriate.
- The response should feel like it comes from ONE intelligent assistant, not multiple.
- Be concise but thorough. Don't mention the sub-agents or internal pipeline.
- Start the response directly — no "Here's what I found" preamble unless it fits naturally.
"""


class MoEOrchestrator:
    """
    Mixture-of-Experts orchestrator that:
      1. Plans sub-tasks with an LLM call
      2. Executes sub-agents sequentially
      3. Aggregates results into a final response
    """

    def __init__(
        self,
        nvidia_api_key: str,
        pexels_api_key: str = "",
        workspace_context: str = "",
        model: str = ORCHESTRATOR_MODEL,
        subagent_model: str = SUBAGENT_MODEL,
    ):
        self.nvidia_key = nvidia_api_key
        self.pexels_key = pexels_api_key
        self.workspace_context = workspace_context
        self.model = model
        self.subagent_model = subagent_model

        # Initialise sub-agents
        self.agents: Dict[AgentRole, Any] = {
            AgentRole.REASONING: ReasoningAgent(nvidia_api_key, model=subagent_model),
            AgentRole.FORM_ANALYST: FormAnalystAgent(nvidia_api_key),
            AgentRole.DUCKDUCKGO: DuckDuckGoAgent(nvidia_api_key),
        }
        if pexels_api_key:
            self.agents[AgentRole.PEXELS_IMAGE] = PexelsImageAgent(pexels_api_key, nvidia_api_key)

    def run(self, user_message: str, history: List[Dict[str, str]] = None) -> MoEResult:
        """Execute the full MoE pipeline."""
        start_time = time.time()

        # ── Step 1: Plan ──
        sub_tasks = self._plan(user_message, history or [])
        logger.info(f"MoE planned {len(sub_tasks)} sub-tasks: {[t.agent.value for t in sub_tasks]}")

        # ── Step 2: Execute sequentially ──
        for task in sub_tasks:
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

            # Gather results from previously completed tasks as context
            prior_context = self._gather_prior_results(sub_tasks, task.id)

            try:
                agent = self.agents.get(task.agent)
                if agent is None:
                    # Agent not available (e.g. no Pexels key)
                    task.status = TaskStatus.SKIPPED
                    task.result = f"Agent '{task.agent.value}' is not configured."
                    task.finished_at = time.time()
                    continue

                # Run the sub-agent
                context = self.workspace_context if task.agent == AgentRole.FORM_ANALYST else prior_context
                task.result = agent.run(task.instruction, context=context)
                task.status = TaskStatus.COMPLETED

            except Exception as e:
                logger.error(f"Sub-agent {task.agent.value} failed: {traceback.format_exc()}")
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.result = f"Error: {str(e)}"

            task.finished_at = time.time()

        # ── Step 3: Aggregate ──
        orchestrator_reasoning = None
        final_answer = self._aggregate(user_message, sub_tasks)

        total_ms = int((time.time() - start_time) * 1000)

        return MoEResult(
            answer=final_answer,
            sub_tasks=sub_tasks,
            total_duration_ms=total_ms,
            orchestrator_reasoning=orchestrator_reasoning,
        )

    def _plan(self, user_message: str, history: List[Dict[str, str]]) -> List[SubTask]:
        """Use the orchestrator LLM to decompose the request into sub-tasks."""
        messages = [
            {"role": "system", "content": PLANNING_PROMPT},
        ]

        # Add available agents info
        available = list(self.agents.keys())
        available_str = ", ".join(a.value for a in available)
        messages.append({
            "role": "system",
            "content": f"Currently available agents: {available_str}. Only use these agents."
        })

        # Add conversation history for context (last 4 messages)
        if history:
            for msg in history[-4:]:
                messages.append(msg)

        # Add workspace context hint
        if self.workspace_context:
            messages.append({
                "role": "system",
                "content": "Note: the user has form workspace data available. Use 'form_analyst' if the question relates to their forms/data."
            })

        messages.append({"role": "user", "content": user_message})

        try:
            raw = _nvidia_chat(
                self.nvidia_key,
                messages,
                model=self.model,
                temperature=0.2,
                max_tokens=1024,
            )

            # Parse the JSON plan
            plan = self._parse_plan(raw)
            return plan

        except Exception as e:
            logger.error(f"Planning failed: {e}. Falling back to single reasoning task.")
            return [SubTask(id=1, agent=AgentRole.REASONING, instruction=user_message)]

    def _parse_plan(self, raw: str) -> List[SubTask]:
        """Parse the LLM planning output into SubTask objects."""
        import re

        # Try to extract JSON from the response
        raw = raw.strip()

        # Remove markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```", "", raw)

        try:
            tasks_data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to find JSON array in the text
            match = re.search(r"\[[\s\S]*\]", raw)
            if match:
                try:
                    tasks_data = json.loads(match.group())
                except json.JSONDecodeError:
                    return [SubTask(id=1, agent=AgentRole.REASONING, instruction="Please answer the user's question.")]
            else:
                return [SubTask(id=1, agent=AgentRole.REASONING, instruction="Please answer the user's question.")]

        if not isinstance(tasks_data, list):
            tasks_data = [tasks_data]

        sub_tasks = []
        for t in tasks_data[:5]:  # Cap at 5
            agent_str = t.get("agent", "reasoning")
            try:
                agent_role = AgentRole(agent_str)
            except ValueError:
                agent_role = AgentRole.REASONING

            # Skip agents that aren't available
            if agent_role not in self.agents:
                if agent_role == AgentRole.PEXELS_IMAGE:
                    agent_role = AgentRole.REASONING
                    t["instruction"] = f"Note: Pexels API is not configured. {t.get('instruction', '')}"
                else:
                    agent_role = AgentRole.REASONING

            sub_tasks.append(SubTask(
                id=t.get("id", len(sub_tasks) + 1),
                agent=agent_role,
                instruction=t.get("instruction", ""),
            ))

        return sub_tasks if sub_tasks else [SubTask(id=1, agent=AgentRole.REASONING, instruction="Please help.")]

    def _gather_prior_results(self, all_tasks: List[SubTask], current_id: int) -> str:
        """Gather results from completed prior tasks as context for the current task."""
        parts = []
        for t in all_tasks:
            if t.id < current_id and t.status == TaskStatus.COMPLETED and t.result:
                parts.append(f"[{t.agent.value} result]: {t.result[:2000]}")
        return "\n\n".join(parts) if parts else ""

    def _aggregate(self, user_message: str, sub_tasks: List[SubTask]) -> str:
        """Aggregate all sub-task results into a single response."""
        completed = [t for t in sub_tasks if t.status == TaskStatus.COMPLETED]

        if not completed:
            failed = [t for t in sub_tasks if t.status == TaskStatus.FAILED]
            if failed:
                return f"I encountered errors while processing your request:\n\n" + "\n".join(
                    f"- **{t.agent.value}**: {t.error}" for t in failed
                )
            return "I wasn't able to process your request. Please try again."

        # If only one task, return its result directly
        if len(completed) == 1 and len(sub_tasks) == 1:
            result = completed[0].result
            # If it's JSON, try to extract meaningful content
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "summary" in parsed:
                    return parsed["summary"]
                if isinstance(parsed, dict) and "error" in parsed:
                    return f"⚠️ {parsed['error']}"
            except (json.JSONDecodeError, TypeError):
                pass
            return result

        # Multiple tasks — aggregate with LLM
        results_text = ""
        for t in sub_tasks:
            status_icon = "✅" if t.status == TaskStatus.COMPLETED else "❌" if t.status == TaskStatus.FAILED else "⏭️"
            results_text += f"\n\n### {status_icon} Agent: {t.agent.value}\n"
            results_text += f"**Task**: {t.instruction}\n"
            results_text += f"**Result**:\n{t.result or t.error or 'No result'}\n"

        try:
            return _nvidia_chat(
                self.nvidia_key,
                [
                    {"role": "system", "content": AGGREGATION_PROMPT},
                    {"role": "user", "content": f"User's original request: {user_message}\n\n---\n\nSub-agent results:{results_text}"},
                ],
                model=self.model,
                temperature=0.4,
                max_tokens=4096,
            )
        except Exception as e:
            logger.error(f"Aggregation LLM failed: {e}. Returning raw results.")
            # Fallback: concatenate results
            parts = []
            for t in completed:
                parts.append(f"**{t.agent.value}**:\n{t.result}")
            return "\n\n---\n\n".join(parts)
