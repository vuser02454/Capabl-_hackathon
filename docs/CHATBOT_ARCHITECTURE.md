# Chatbot Architecture

The EcoSentinel assistant is an interface into the system that already exists — the same tools,
the same retriever, the same decision state. It is not a general chatbot with an environmental
theme, and the difference is visible in the response: every number it reports can be traced to
the tool that produced it.

---

## 1. Flow

```
USER MESSAGE
     │
     ▼
  ROUTER  ──────────────── Gemini 2.5 Flash, structured output
     │                     {intent, tool, arguments}
     │
     ├── "analysis" ──────► held decision state (services/ai/chat.py)
     │                      + the passages that grounded THAT decision
     │
     ├── "functional" ────► allow-list check ──► tool registry ──► Python result
     │                                                   │
     │                                          Gemini explains it
     │                                          (result is AUTHORITATIVE)
     │
     └── "general" ───────► secondary LLM (Groq / OpenRouter)
                            no access to the user's data
     │
     ▼
  ANSWER + tool executions + citations + evidence ids
```

## 2. The rule, and where it is enforced

> Gemini decides **which** tool to call and **with what arguments**.
> The tool decides **what the answer is**.

Gemini then explains that answer and may not change it. `calculate_environmental_risk` runs
`core/risk.py`; `get_water_sensor_data` runs a provider; `search_environmental_knowledge` runs
the retriever. **Nothing numeric in a chat response is authored by a language model.**

Two safety properties are structural rather than prompted:

1. **Only allow-listed tool names execute.** A name the router returns is checked against
   `CHAT_TOOLS` before the registry is touched. A hallucinated `delete_everything` produces an
   error, not a call. Tested.
2. **Arguments are validated by the tool's own Pydantic model** before the handler runs, by the
   same registry path every other caller uses.

### Why the chat allow-list is a subset of the 9 tools

`CHAT_TOOLS` exposes six. Excluded deliberately:

| Tool | Why not chat-callable |
| --- | --- |
| `generate_investigation_plan` | Runs the entire LangGraph. An ambiguous sentence should not be able to launch a full multi-agent re-analysis. |
| `analyze_water_image` | Needs an upload the chat transport does not carry. |
| `analyze_waste_image` | Same. |

## 3. The three routes

### `analysis` — grounded in the held decision
Questions about *this* analysis: "why is the risk high", "what evidence caused it", "what should
I verify next", "show me the sources".

Answered from `services/ai/chat.py`, which already reads decision state keyed by `analysis_id`
and already cites evidence ids. The chat agent adds the passages that grounded **that** decision,
so "show me the source" resolves to what actually informed the answer rather than a fresh search.

**An unknown `analysis_id` is refused, not answered.** Explaining River B with River A's evidence
reads perfectly and is entirely wrong — it is the single worst failure this component can have,
because it is invisible.

The router defaults here when it is unavailable or uncertain. Real evidence the user is looking
at beats a model's general knowledge.

### `functional` — a tool runs
"Get the water sensor data for Mumbai", "search the knowledge base for turbidity limits", "what
segregation category is paper waste".

Gemini names the tool and the arguments; the registry validates and executes; Gemini phrases the
result under a prompt that forbids changing any number in it.

### `general` — the secondary LLM
"What is eutrophication?", "Explain BOD and COD", "What is Grad-CAM?"

Routed to the explainability provider (Groq `openai/gpt-oss-120b`), which is told explicitly that
it has **no access to the user's analysis** and must say so if the question needs it. The UI
labels these answers *"General knowledge — not your data"*, so a general answer can never be
mistaken for a finding about this river.

## 4. What the UI shows, and what it does not

| Shown | Not shown |
| --- | --- |
| Which tools ran, and why | The router prompt |
| Whether each succeeded, and how long it took | The routing rationale |
| A one-line factual summary of each result | Any model reasoning or chain-of-thought |
| Citations: chunk id, document, section, source file, relevance, and the retrieved text | — |
| Evidence ids the answer rests on | — |
| Which route served the answer | — |

The distinction is not only about privacy. "This tool ran and returned this" is checkable by a
reader; narrated reasoning is unfalsifiable by construction. Showing the former earns the trust
that showing the latter only performs.

## 5. Degradation

Every layer fails to something honest, and the whole path is exercised by tests running with both
providers set to `none`.

| Failure | Behaviour |
| --- | --- |
| Gemini unavailable | Router defaults to `analysis`; the existing deterministic chat answers from decision state |
| Secondary LLM unavailable | General questions are declined explicitly — no answer from nowhere |
| Tool fails | The failure and its reason are shown, with retry. Nothing is assumed in its place |
| Invalid tool arguments | Rejected by the tool's model before the handler runs |
| Unknown `analysis_id` | Refused, never answered from another analysis |
| Corpus has no answer | Zero citations, and the tool says the knowledge base does not cover it |
| No analysis loaded | The panel says so and still serves general questions |

**None of this runs during an analysis**, so no chat failure can affect a risk score.

## 6. Security

- Keys stay server-side. The browser only ever calls `POST /api/chat`.
- `message` and `analysis_id` are length-validated by `ChatRequest`.
- Tool names from the model are never executed directly — allow-list, then registry.
- Tool arguments are validated by Pydantic.
- Untrusted content (the user's message, tool output) is passed to models explicitly labelled
  as data, not instructions.

## 7. API

`POST /api/chat` — `{analysisId, question}` →

```jsonc
{
  "analysisId": "a9cd787f843c",
  "answer": "...",
  "intent": "functional",            // analysis | functional | general | unavailable
  "source": "gemini+tool",
  "llmEnhanced": true,
  "toolExecutions": [
    { "tool": "search_environmental_knowledge",
      "purpose": "Retrieve documented knowledge",
      "status": "ok", "durationMs": 3, "summary": "2 passage(s) retrieved" }
  ],
  "citations": [
    { "chunkId": "water_quality_standards#turbidity",
      "documentTitle": "Water Quality Parameters and Thresholds",
      "section": "Turbidity",
      "sourceFile": "backend/agents/water_agent.py (PARAMETERS)",
      "score": 0.62, "content": "..." }
  ],
  "evidenceIds": ["air.pm25", "..."]
}
```

A tool failure still returns 200 with a structured result. Only an `analysis` question about an
analysis the backend does not hold returns 404.

## 8. Verified behaviour

Measured against the running stack:

| Message | Route | Tool | Result |
| --- | --- | --- | --- |
| "Why is the current water risk high?" | `analysis` | `get_current_analysis`, `get_retrieved_sources` | 10 evidence items, 3 passages |
| "Search the knowledge base for what turbidity BIS permissible limit means" | `functional` | `search_environmental_knowledge` | Cited `water_quality_standards#turbidity`, answered **5 NTU** from the corpus |
| "Get the water sensor data for Mumbai" | `functional` | `get_water_sensor_data` | Mithi River · Kurla, pH 7.6, turbidity 19.0 NTU |
| "What is eutrophication?" | `general` | — | Secondary LLM, no tools, no citations |

## 9. Limitations

- The router is a single Gemini call. A message spanning two intents is served as one.
- Conversation history is not sent to the model; each message is routed on its own text. This
  keeps grounding tight and prompts small, at the cost of follow-ups like "and the other one?".
- Chat cannot analyse an uploaded image — that path belongs to the Water and Waste pages.
- Tool results are summarised for display by a fixed formatter, not by a model.
