import os
import re
import json
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

from ibm_watsonx_ai import Credentials
from ibm_watsonx_ai.foundation_models import ModelInference
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams
from ibm_watsonx_ai.foundation_models.utils.enums import DecodingMethods

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "finally_production_key_2026")

def get_watsonx_model():
    try:
        creds = Credentials(
            url=os.getenv("IBM_WATSONX_URL"),
            api_key=os.getenv("IBM_API_KEY")
        )
        parameters = {
            GenParams.DECODING_METHOD: DecodingMethods.GREEDY,
            GenParams.MAX_NEW_TOKENS: 1024,
            GenParams.REPETITION_PENALTY: 1.05
        }
        model = ModelInference(
            model_id=os.getenv("WATSONX_MODEL_ID", "meta-llama/llama-3-3-70b-instruct"),
            credentials=creds,
            project_id=os.getenv("IBM_PROJECT_ID"),
            params=parameters
        )
        model.get_details()
        return model
    except Exception as e:
        print(f"Watsonx Initialization Error: {e}")
        return None

watsonx_model = get_watsonx_model()

SCHEMES_PATH = os.path.join("knowledge", "schemes.txt")
JOBS_PATH = os.path.join("knowledge", "jobs.json")

# ==========================================
# 📚 KNOWLEDGE HELPERS
# ==========================================

_schemes_cache = None

def load_schemes_text():
    """Loads schemes.txt once and caches it in memory."""
    global _schemes_cache
    if _schemes_cache is None:
        if os.path.exists(SCHEMES_PATH):
            with open(SCHEMES_PATH, "r", encoding="utf-8") as f:
                _schemes_cache = f.read()
        else:
            _schemes_cache = ""
    return _schemes_cache

def split_scheme_blocks(text):
    """Splits schemes.txt into top-level scheme blocks by '# ' headers."""
    blocks = {}
    parts = re.split(r"\n# ", text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not part.startswith("#"):
            part = "# " + part
        title_line = part.splitlines()[0].lstrip("#").strip()
        blocks[title_line] = part
    return blocks

def extract_section(scheme_title_keyword, section_keyword):
    """
    Pulls just one '## Section' out of one scheme block.
    Falls back to the whole block if the section isn't found.
    """
    text = load_schemes_text()
    blocks = split_scheme_blocks(text)

    matched_block = None
    for title, block in blocks.items():
        if scheme_title_keyword.lower() in title.lower():
            matched_block = block
            break
    if not matched_block:
        return None

    sections = re.split(r"\n## ", matched_block)
    for sec in sections:
        if sec.strip().lower().startswith(section_keyword.lower()):
            return "## " + sec.strip()

    return matched_block  # fallback: whole scheme block

def detect_scheme(user_query):
    """Very lightweight scheme detector based on keywords in the user's message."""
    q = user_query.lower()
    if any(w in q for w in ["svanidhi", "street vendor", "vendor", "cart", "hawker", "footpath"]):
        return "PM SVANidhi"
    if any(w in q for w in ["mudra", "shishu", "kishore", "tarun", "shop", "manufactur", "salon", "business loan"]):
        return "Mudra"
    return None  # ambiguous — caller should handle both

# ==========================================
# 🛠️ AGENT TOOLS
# ==========================================

def tool_read_schemes(user_query=None):
    """Tool 1: Full financial knowledge dump (used for general scheme questions)."""
    text = load_schemes_text()
    if text:
        return f"FINANCIAL CONTEXT:\n{text}"
    return "No financial scheme documents found."

def tool_search_jobs(user_query):
    """Tool 2: Searches the local JSON database for job matches."""
    query_lower = user_query.lower()

    if os.path.exists(JOBS_PATH):
        with open(JOBS_PATH, "r", encoding="utf-8") as f:
            jobs_db = json.load(f)

            if "delivery" in query_lower or "drive" in query_lower:
                return f"JOB DATA FOUND:\n{json.dumps(jobs_db['delivery'], indent=2)}"
            elif "construct" in query_lower or "build" in query_lower or "site" in query_lower:
                return f"JOB DATA FOUND:\n{json.dumps(jobs_db['construction'], indent=2)}"
            elif "retail" in query_lower or "shop" in query_lower or "store" in query_lower:
                return f"JOB DATA FOUND:\n{json.dumps(jobs_db['retail'], indent=2)}"

    return "JOB DATA FOUND: No specific jobs found right now, but tell the user to visit local employment exchanges."

def tool_check_eligibility(user_query):
    """
    Tool 3: Matches the user's situation to a specific scheme and pulls
    just that scheme's Eligibility + Loan Amount sections, so the model
    reasons over a focused slice instead of the whole document.
    """
    scheme = detect_scheme(user_query)
    if scheme is None:
        text = load_schemes_text()
        blocks = split_scheme_blocks(text)
        combined = []
        for title in blocks:
            elig = extract_section(title, "Eligibility")
            if elig:
                combined.append(f"### {title}\n{elig}")
        return "ELIGIBILITY CONTEXT (multiple schemes):\n" + "\n\n".join(combined)

    eligibility = extract_section(scheme, "Eligibility") or ""
    loan_amount = extract_section(scheme, "Loan") or ""
    return f"ELIGIBILITY CONTEXT for {scheme}:\n{eligibility}\n\n{loan_amount}"

def tool_application_checklist(user_query):
    """
    Tool 4: Pulls just the 'Required Documents' section for the relevant
    scheme, so the AI can generate a clean checklist.
    """
    scheme = detect_scheme(user_query)
    if scheme is None:
        text = load_schemes_text()
        blocks = split_scheme_blocks(text)
        combined = []
        for title in blocks:
            docs = extract_section(title, "Documents") or extract_section(title, "Required Documents")
            if docs:
                combined.append(f"### {title}\n{docs}")
        return "DOCUMENT CONTEXT (multiple schemes):\n" + "\n\n".join(combined)

    docs = extract_section(scheme, "Documents") or extract_section(scheme, "Required Documents") or ""
    return f"DOCUMENT CONTEXT for {scheme}:\n{docs}"

# ==========================================
# 🧠 AGENT ROUTER LOGIC (two-stage)
# ==========================================

# Stage 1: cheap keyword classification, no API call.
INTENT_KEYWORDS = {
    "eligibility": ["eligible", "eligibility", "qualify", "can i get", "am i able", "do i qualify"],
    "checklist":   ["document", "documents", "papers", "checklist", "what do i need", "kyc"],
    "job":         ["job", "work", "hire", "vacancy", "employment", "salary", "hiring"],
    "scheme":      ["scheme", "loan", "subsidy", "svanidhi", "mudra", "yojana", "credit", "interest"],
}

def classify_intent(message):
    """
    Returns the single best-matching intent, or 'unclear' if zero
    categories match (so we can ask instead of guess).
    """
    msg = message.lower()
    matched = [intent for intent, kws in INTENT_KEYWORDS.items() if any(kw in msg for kw in kws)]

    if len(matched) == 1:
        return matched[0]
    if len(matched) == 0:
        return "unclear"
    # Multiple matches: apply priority order (most specific tool wins)
    priority = ["eligibility", "checklist", "job", "scheme"]
    for p in priority:
        if p in matched:
            return p
    return "unclear"

TOOL_MAP = {
    "eligibility": (
        tool_check_eligibility,
        "You are 'FinAlly'. Use the ELIGIBILITY CONTEXT to tell the user clearly whether they "
        "are likely eligible, what conditions apply, and what loan amount they could expect. "
        "Be simple, jargon-free, and encouraging. If ambiguous, ask one clarifying question."
    ),
    "checklist": (
        tool_application_checklist,
        "You are 'FinAlly'. Use the DOCUMENT CONTEXT to give the user a clear numbered checklist "
        "of documents they need to apply. Keep it short and practical."
    ),
    "job": (
        tool_search_jobs,
        "You are 'FinAlly'. Use the JOB DATA provided to suggest real local jobs to the user. "
        "Format the jobs nicely using bullet points. Be encouraging."
    ),
    "scheme": (
        tool_read_schemes,
        "You are 'FinAlly'. Use the FINANCIAL CONTEXT provided to explain government subsidies "
        "and loans. Be simple and jargon-free."
    ),
}

CLARIFY_RESPONSE = (
    "I want to make sure I point you the right way — are you looking for "
    "(1) local job opportunities, or (2) information about a government "
    "financial scheme like PM SVANidhi or Mudra Yojana? You can also ask "
    "things like 'am I eligible for a loan' or 'what documents do I need'."
)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    if not watsonx_model:
        return jsonify({"error": "AI Engine offline."}), 500

    data = request.json
    user_message = data.get("message", "")

    # 1. STAGE 1 ROUTER (no API call)
    intent = classify_intent(user_message)

    if intent == "unclear":
        return jsonify({"response": CLARIFY_RESPONSE, "agent": "router"})

    tool_fn, system_prompt = TOOL_MAP[intent]
    agent_context = tool_fn(user_message)

    # 2. STAGE 2: THE AGENT GENERATES THE RESPONSE
    full_prompt = (
        f"<|system|>\n{system_prompt}\n\n"
        f"{agent_context}\n"
        f"<|user|>\n{user_message}\n"
        f"<|assistant|>\n"
    )

    try:
        response = watsonx_model.generate_text(prompt=full_prompt)
        return jsonify({"response": response.strip(), "agent": intent})
    except Exception as e:
        return jsonify({"error": f"Model inference failure: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)