/**
 * Customer Frontend JavaScript for AI Queue Management System
 * Handles:
 * 1. Mobile Navigation Menu Toggle
 * 2. Floating AI Assistant Chatbot with live intelligent query processing
 * 3. Toast notifications auto-dismissal
 */

document.addEventListener("DOMContentLoaded", function () {
    // 1. Mobile Navigation Toggle
    const mobileMenuBtn = document.getElementById("mobileMenuBtn");
    const navLinks = document.getElementById("navLinks");

    if (mobileMenuBtn && navLinks) {
        mobileMenuBtn.addEventListener("click", function () {
            navLinks.style.display = (navLinks.style.display === "flex") ? "none" : "flex";
            if (navLinks.style.display === "flex") {
                navLinks.style.flexDirection = "column";
                navLinks.style.position = "absolute";
                navLinks.style.top = "70px";
                navLinks.style.left = "0";
                navLinks.style.width = "100%";
                navLinks.style.background = "var(--white)";
                navLinks.style.padding = "20px";
                navLinks.style.boxShadow = "var(--shadow-md)";
                navLinks.style.zIndex = "999";
            }
        });
    }

    // 2. Chatbot Drawer Toggle
    const chatbotToggle = document.getElementById("chatbotToggle");
    const chatDrawer = document.getElementById("chatDrawer");
    const chatClose = document.getElementById("chatClose");

    if (chatbotToggle && chatDrawer) {
        chatbotToggle.addEventListener("click", function () {
            chatDrawer.classList.toggle("open");
            if (chatDrawer.classList.contains("open")) {
                const input = document.getElementById("chatInput");
                if (input) input.focus();
            }
        });
    }

    if (chatClose && chatDrawer) {
        chatClose.addEventListener("click", function () {
            chatDrawer.classList.remove("open");
        });
    }

    // 3. Auto-dismiss flash toasts after 5 seconds
    const toasts = document.querySelectorAll(".flash-toast");
    toasts.forEach(toast => {
        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateX(50px)";
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    });
});

// Chatbot Send Message Handler
function submitChatMessage() {
    const input = document.getElementById("chatInput");
    if (!input) return;
    const msg = input.value.trim();
    if (!msg) return;

    appendChatBubble("user", msg);
    input.value = "";

    // Show typing indicator
    const messagesContainer = document.getElementById("chatMessages");
    const typingId = "typing-" + Date.now();
    const typingBubble = document.createElement("div");
    typingBubble.id = typingId;
    typingBubble.className = "chat-bubble ai";
    typingBubble.innerHTML = "<em>AI Assistant is typing...</em>";
    messagesContainer.appendChild(typingBubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    fetch("/api/chatbot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg })
    })
    .then(res => res.json())
    .then(data => {
        const typingEl = document.getElementById(typingId);
        if (typingEl) typingEl.remove();
        appendChatBubble("ai", data.response || "I am here to help you navigate queues!");
    })
    .catch(err => {
        const typingEl = document.getElementById(typingId);
        if (typingEl) typingEl.remove();
        appendChatBubble("ai", "Sorry, I am having trouble connecting right now. Please try again.");
    });
}

function sendChatPrompt(promptText) {
    const input = document.getElementById("chatInput");
    if (input) {
        input.value = promptText;
        submitChatMessage();
    }
}

function appendChatBubble(sender, text) {
    const messagesContainer = document.getElementById("chatMessages");
    if (!messagesContainer) return;
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender}`;
    // Simple markdown bold converter
    bubble.innerHTML = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    messagesContainer.appendChild(bubble);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}