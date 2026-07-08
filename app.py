import os
import re
import json
from flask import Flask, render_template, request, jsonify, session
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

LEDGER_KEYWORDS = ["ledger", "bahi-khata", "bahi khata", "bookkeeping", "record keeping", "track income"]
AMOUNT_PATTERN = re.compile(r'(?:₹|rs\.?|inr)\s?([\d,]+)|([\d,]+)\s?(?:rupees|rs\b)', re.IGNORECASE)

def tool_audit_expense(user_query):
    """
    Tool 5: Lightweight expense/ledger audit helper for the Expense Audit tab.

    - If the message mentions a purchase amount, pulls the matching scheme's
      Loan Amount / Loan Categories section so the model can reason about how
      that spend relates to tranche/category structure (without inventing
      numbers that aren't in schemes.txt).
    - If the message is about record-keeping instead, returns practical
      bahi-khata guidance for informal small-business bookkeeping.
    """
    amount_match = AMOUNT_PATTERN.search(user_query)
    is_ledger_question = any(k in user_query.lower() for k in LEDGER_KEYWORDS)

    if amount_match:
        amount = (amount_match.group(1) or amount_match.group(2)).replace(",", "")
        scheme = detect_scheme(user_query)
        if scheme:
            loan_section = extract_section(scheme, "Loan") or ""
            return (
                f"EXPENSE AUDIT CONTEXT:\n"
                f"User-reported purchase amount: ₹{amount}\n"
                f"Relevant scheme: {scheme}\n"
                f"{loan_section}\n\n"
                f"Task: Explain in simple terms how this purchase relates to the loan "
                f"tranche/category structure above. Do NOT invent numbers not present in "
                f"the context. Clarify that moving to a higher tranche/category usually "
                f"depends on timely repayment history, not spending amount, unless the "
                f"context explicitly states otherwise."
            )
        return (
            f"EXPENSE AUDIT CONTEXT:\n"
            f"User-reported purchase amount: ₹{amount}\n"
            f"No specific scheme was mentioned. Ask the user which scheme "
            f"(PM SVANidhi or Mudra Yojana) their loan falls under, since "
            f"tranche/category rules differ between schemes."
        )

    if is_ledger_question:
        return (
            "LEDGER GUIDANCE CONTEXT:\n"
            "Practical bahi-khata (informal ledger) tips for small vendors/entrepreneurs:\n"
            "- Record every sale and purchase daily, even small cash transactions.\n"
            "- Keep personal and business expenses in separate pages or columns.\n"
            "- Keep purchase receipts/bills, even handwritten ones, as proof of expenditure.\n"
            "- Note loan repayments and dates separately to build a clean repayment record.\n"
            "- A consistent ledger is often what banks look at when assessing repayment "
            "capacity for a higher loan tranche or renewal.\n"
            "Task: Turn this into simple, encouraging, jargon-free advice."
        )

    return (
        "AUDIT CONTEXT: The user seems to be asking about an expense, purchase, or "
        "record-keeping question, but no specific amount or clear ledger topic was "
        "detected. Ask them to share the purchase amount and which scheme they're "
        "asking about, or clarify if they want general bookkeeping tips."
    )

# ==========================================
# 🧠 AGENT ROUTER LOGIC (two-stage)
# ==========================================

# Stage 1: cheap keyword classification, no API call.
INTENT_KEYWORDS = {
    "audit":       ["audit", "expense", "receipt", "ledger", "bahi-khata", "bahi khata",
                     "bookkeeping", "invoice", "purchase", "bought", "spent", "tranche"],
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
    # Multiple matches: apply priority order (most specific tool wins).
    # "audit" goes first so a message like "I bought ₹5000 of materials,
    # does this help my eligibility?" routes to the audit tool instead of
    # the generic eligibility one.
    priority = ["audit", "eligibility", "checklist", "job", "scheme"]
    for p in priority:
        if p in matched:
            return p
    return "unclear"

TOOL_MAP = {
    "audit": (
        tool_audit_expense,
        "You are 'FinAlly'. Use the EXPENSE AUDIT CONTEXT or LEDGER GUIDANCE CONTEXT to give "
        "the user simple, practical advice about their purchase or record-keeping question. "
        "Be encouraging, never invent numbers that aren't in the context, and ask exactly "
        "one clarifying question if something important is missing."
    ),
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

    # Conversation stickiness: if this message has no routing keywords of
    # its own (e.g. a plain answer to a clarifying question we just asked,
    # like "I am a farmer in haryana"), stay on whatever intent the last
    # turn resolved to instead of re-triggering the generic clarify prompt.
    if intent == "unclear" and session.get("last_intent"):
        intent = session["last_intent"]

    if intent == "unclear":
        return jsonify({"response": CLARIFY_RESPONSE, "agent": "router"})

    tool_fn, system_prompt = TOOL_MAP[intent]

    # Give tools a little short-term memory: combine the previous turn's
    # message with this one so keyword-based tools (like scheme detection)
    # have a better chance of picking up context from a multi-turn reply.
    last_user_message = session.get("last_user_message", "")
    combined_query = f"{last_user_message} {user_message}".strip()
    agent_context = tool_fn(combined_query)

    session["last_intent"] = intent
    session["last_user_message"] = user_message

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