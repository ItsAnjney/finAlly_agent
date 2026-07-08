# FinAlly — AI Agent for Gig Work & Government Financial Schemes

FinAlly is an agentic assistant that routes user queries between a **Job Mentor**
pathway (local job listings) and a **Financial Scheme** pathway (PM SVANidhi,
Mudra Yojana), backed by a local RAG knowledge base and IBM watsonx.ai.

## 🔴 Live Demo
**[https://finally-agent.onrender.com](https://finally-agent.onrender.com)**

Just open the link — no setup needed. Note: the free hosting tier sleeps after
~15 minutes of inactivity, so the first request after idle time may take
30–50 seconds to respond while the server wakes up.

## Architecture
- **Router Agent** — lightweight keyword classifier decides intent (eligibility,
  checklist, job search, general scheme info) with zero LLM calls.
- **Tool Layer** — pulls a focused slice of context: local `jobs.json` for job
  search, or a specific section of `knowledge/schemes.txt` for eligibility/
  document questions.
- **Generation Agent** — IBM watsonx.ai (configurable model via env var) turns
  the retrieved context into a natural-language answer.
- **Session memory** — Flask session tracks the last resolved intent so
  follow-up replies (e.g. answering a clarifying question) stay on-topic
  instead of re-triggering the generic router prompt.

## Running Locally
This repo does **not** include API credentials (by design — `.env` is
gitignored). To run it yourself:

1. Clone the repo
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your **own** IBM watsonx.ai
   credentials (API key, project ID, model ID)
4. `python app.py`

You'll need your own IBM Cloud account with a Watson Machine Learning
service instance associated to a watsonx.ai project.

## Tech Stack
Flask · IBM watsonx.ai (`ibm-watsonx-ai` SDK) · vanilla JS/CSS frontend ·
deployed on Render
