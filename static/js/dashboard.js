/**
 * Organization Dashboard JavaScript for AI Queue Management System
 * Handles:
 * 1. Live Queue Operator Actions (Call Next, Complete, Skip)
 * 2. Walk-in token generator modal
 * 3. Dynamic Counter activation / pausing
 * 4. Applying AI Capacity Recommendations
 * 5. Sidebar Toggle
 */

document.addEventListener("DOMContentLoaded", function () {
    const sidebarToggle = document.getElementById("sidebarToggleBtn");
    const dashSidebar = document.getElementById("dashSidebar");

    if (sidebarToggle && dashSidebar) {
        sidebarToggle.addEventListener("click", function () {
            dashSidebar.classList.toggle("open");
        });
    }
});

// Call Next Customer according to AI Priority
function callNextCustomer(slug) {
    const counterSelect = document.getElementById("activeOperatingCounter");
    const counterId = counterSelect ? parseInt(counterSelect.value) : null;

    fetch(`/api/org/${slug}/call-next`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ counter_id: counterId })
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) {
            alert("⚠️ " + data.error);
            return;
        }
        if (data.token) {
            playChimeSound();
        }
        window.location.reload();
    })
    .catch(err => {
        console.error("Failed to call next customer", err);
        alert("An error occurred while calling next token.");
    });
}

// Complete Service for Token
function completeCustomerToken(slug, tokenId) {
    fetch(`/api/org/${slug}/complete-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token_id: tokenId })
    })
    .then(res => res.json())
    .then(data => {
        window.location.reload();
    })
    .catch(err => console.error("Error completing token", err));
}

// Skip Token
function skipCustomerToken(slug, tokenId) {
    if (!confirm("Are you sure you want to mark this token as Skipped?")) return;

    fetch(`/api/org/${slug}/skip-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token_id: tokenId })
    })
    .then(res => res.json())
    .then(data => {
        window.location.reload();
    })
    .catch(err => console.error("Error skipping token", err));
}

// Serve a specific waiting token directly
function callSpecificCustomer(slug, tokenId) {
    const counterSelect = document.getElementById("activeOperatingCounter");
    const counterId = counterSelect ? parseInt(counterSelect.value) : null;

    fetch(`/api/org/${slug}/call-next`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ counter_id: counterId, specific_token_id: tokenId })
    })
    .then(res => res.json())
    .then(data => {
        if (data.error) {
            alert("⚠️ " + data.error);
            return;
        }
        if (data.token) {
            playChimeSound();
        }
        window.location.reload();
    })
    .catch(err => {
        console.error("Error calling token", err);
        alert("An error occurred while serving token.");
    });
}

// Toggle Counter Active / Paused / Closed
function toggleCounterStatus(slug, counterId, status) {
    fetch(`/api/org/${slug}/toggle-counter`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ counter_id: counterId, status: status })
    })
    .then(res => res.json())
    .then(data => {
        window.location.reload();
    })
    .catch(err => console.error("Error toggling counter", err));
}

// Apply AI Capacity Recommendation (e.g. Open Counter 3)
function applyAiRecommendation(slug, actionType, targetCounter) {
    fetch(`/api/org/${slug}/apply-ai-rec`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_type: actionType, target_counter: targetCounter })
    })
    .then(res => res.json())
    .then(data => {
        alert("🧠 AI Recommendation Applied: Counter " + targetCounter + " activated!");
        window.location.reload();
    })
    .catch(err => console.error("Error applying AI recommendation", err));
}

// Walk-in Modal Handlers
function openWalkinModal() {
    const modal = document.getElementById("walkinModal");
    if (modal) modal.classList.add("open");
}

function closeWalkinModal() {
    const modal = document.getElementById("walkinModal");
    if (modal) modal.classList.remove("open");
}

function submitWalkin(event, slug) {
    event.preventDefault();
    const name = document.getElementById("walkinName").value.trim();
    const serviceId = document.getElementById("walkinService").value;
    const priority = document.getElementById("walkinPriority").value;

    fetch(`/api/org/${slug}/add-walkin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name: name,
            service_id: parseInt(serviceId),
            priority: priority
        })
    })
    .then(res => res.json())
    .then(data => {
        closeWalkinModal();
        alert(`✓ Walk-in token created: #${data.token_str}`);
        window.location.reload();
    })
    .catch(err => console.error("Error creating walk-in", err));
}

// Web Audio API Chime for Calling Tokens
function playChimeSound() {
    try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        const ctx = new AudioContext();

        const osc = ctx.createOscillator();
        const gain = ctx.createGain();

        osc.type = "sine";
        osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
        osc.frequency.setValueAtTime(880, ctx.currentTime + 0.15); // A5

        gain.gain.setValueAtTime(0.3, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);

        osc.connect(gain);
        gain.connect(ctx.destination);

        osc.start();
        osc.stop(ctx.currentTime + 0.8);
    } catch (e) {
        // Fallback gracefully
    }
}
