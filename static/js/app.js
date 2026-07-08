// Tab Switching
function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelectorAll('.nav-links li').forEach(link => {
        link.classList.remove('active');
    });

    document.getElementById(tabId).classList.add('active');
    event.currentTarget.classList.add('active');
}

// Trigger Action from side tabs
function triggerAction(promptText) {
    switchTab('chat');
    // Highlight the chat tab in the sidebar visually
    document.querySelectorAll('.nav-links li').forEach(link => link.classList.remove('active'));
    document.querySelector('.nav-links li:first-child').classList.add('active');
    
    const inputField = document.getElementById('user-input');
    inputField.value = promptText;
    sendMessage();
}

function handleKeyPress(event) {
    if (event.key === 'Enter') {
        sendMessage();
    }
}

// Agent Trail Animation Helper
async function animateAgentTrail() {
    const router = document.getElementById('trail-router');
    const tool = document.getElementById('trail-tool');
    const llm = document.getElementById('trail-llm');

    // Reset
    [router, tool, llm].forEach(el => el.classList.remove('active'));

    // Step 1: Router decides
    router.classList.add('active');
    await new Promise(r => setTimeout(r, 600));
    
    // Step 2: Tool triggers
    router.classList.remove('active');
    tool.classList.add('active');
    await new Promise(r => setTimeout(r, 800));

    // Step 3: LLM formats
    tool.classList.remove('active');
    llm.classList.add('active');
}

function resetAgentTrail() {
    document.querySelectorAll('.trail-step').forEach(el => el.classList.remove('active'));
}

// Core Message Logic
async function sendMessage() {
    const inputField = document.getElementById('user-input');
    const message = inputField.value.trim();
    if (!message) return;

    // Determine intent for styling the stamp BEFORE sending
    const msgLower = message.toLowerCase();
    let agentName = "Scheme Guide Agent";
    let stampClass = "stamp-scheme";

    if (msgLower.includes("job") || msgLower.includes("work") || msgLower.includes("hire") || msgLower.includes("gig")) {
        agentName = "Job Mentor Agent";
        stampClass = "stamp-jobs";
    } else if (msgLower.includes("audit") || msgLower.includes("expense") || msgLower.includes("receipt") || msgLower.includes("ledger")) {
        agentName = "Compliance & Audit Agent";
        stampClass = "stamp-audit";
    } else if (msgLower.includes("document") || msgLower.includes("checklist")) {
        agentName = "Document Prep Agent";
        stampClass = "stamp-doc";
    }

    // Append User Message
    appendMessage(message, 'user-message');
    inputField.value = '';

    // Start Trail Animation
    const trailPromise = animateAgentTrail();

    // Add loading message
    const loadingId = appendMessage("Agent routing...", 'bot-message', "Router Tool");

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message })
        });

        const data = await response.json();
        
        // Wait for animation to hit LLM step if it hasn't already
        await trailPromise; 
        
        document.getElementById(loadingId).remove();
        resetAgentTrail();

        if (response.ok) {
            appendMessage(data.response, 'bot-message', agentName, stampClass);
        } else {
            appendMessage("Error: " + data.error, 'bot-message', "System Error", "stamp-scheme");
        }
    } catch (error) {
        document.getElementById(loadingId).remove();
        resetAgentTrail();
        appendMessage("Network error. Verify server connection.", 'bot-message', "System Error", "stamp-scheme");
    }
}

// Append Message UI (Now supports dynamic stamps)
function appendMessage(text, className, agentTitle = null, stampClass = null) {
    const chatHistory = document.getElementById('chat-history');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${className}`;
    
    // Add colored stamp for bot messages
    let stampHTML = '';
    if (className === 'bot-message' && agentTitle) {
        stampHTML = `<span class="agent-stamp ${stampClass}">${agentTitle}</span>`;
    }
    
    // Format text
    const formattedText = text.replace(/\n/g, '<br>');
    messageDiv.innerHTML = stampHTML + formattedText;
    
    const id = 'msg-' + Date.now();
    messageDiv.id = id;
    
    chatHistory.appendChild(messageDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight; 
    
    return id;
}