// modals.js

const profilePopover = document.getElementById("profile-popover");
const globalModal = document.getElementById("global-modal");
const modalSidebar = document.getElementById("modal-sidebar");
const modalSectionsContainer = document.getElementById("modal-sections-container");

// Load user info from localStorage if available
let currentUserName = localStorage.getItem("app_user_name");
let currentUserAvatar = localStorage.getItem("app_user_avatar");

// Theme initialization
function applyTheme(theme) {
  if (theme === 'system') {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
  } else {
    document.documentElement.setAttribute('data-theme', theme);
  }
}
const currentTheme = localStorage.getItem("app_theme") || "system";
applyTheme(currentTheme);

// Re-evaluate theme if system preference changes
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
  if (localStorage.getItem("app_theme") === 'system') {
    applyTheme('system');
  }
});

// Update Profile UI in Sidebar
function updateSidebarProfile() {
  const email = localStorage.getItem("agent_email") || "";
  if (!currentUserName) {
    currentUserName = email ? email.split("@")[0] : "User";
  }
  const initial = currentUserName.charAt(0).toUpperCase();
  
  document.getElementById("user-name").textContent = currentUserName;
  const initialEl = document.getElementById("user-initial");
  
  if (currentUserAvatar) {
    initialEl.style.backgroundImage = `url(${currentUserAvatar})`;
    initialEl.style.backgroundSize = "cover";
    initialEl.style.backgroundPosition = "center";
    initialEl.textContent = "";
  } else {
    initialEl.style.backgroundImage = "none";
    initialEl.textContent = initial;
  }
}
// Run on load
document.addEventListener("DOMContentLoaded", updateSidebarProfile);

// Popover Logic
document.querySelector(".profile-wrap").addEventListener("click", (e) => {
  e.stopPropagation();
  const rect = e.currentTarget.getBoundingClientRect();
  profilePopover.style.left = rect.left + "px";
  profilePopover.style.bottom = (window.innerHeight - rect.top + 8) + "px";
  profilePopover.style.top = "auto";
  profilePopover.classList.toggle("show");
});

document.addEventListener("click", (e) => {
  if (!profilePopover.contains(e.target) && !e.target.closest(".profile-wrap")) {
    profilePopover.classList.remove("show");
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    profilePopover.classList.remove("show");
    closeModal();
  }
});

document.querySelectorAll(".popover-item").forEach(item => {
  item.addEventListener("click", () => {
    profilePopover.classList.remove("show");
    if (item.id === "popover-logout") return; // Handled separately
    openModal(item.dataset.target);
  });
});

// Logout handled from index.html (logout-btn already bound, bind popover-logout too)
document.getElementById("popover-logout").addEventListener("click", (e) => {
  e.stopPropagation();
  if (confirm("Are you sure you want to log out?")) {
    window.logout(); // relies on global logout in index.html
  }
});


// ---------------- Modal Configurations ----------------

const MODAL_CONFIG = {
  profile: {
    title: "Profile",
    tabs: [
      { id: "profile-info", label: "Profile Information", icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>` },
      { id: "profile-keys", label: "My API Keys", icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>` },
      { id: "profile-security", label: "Security", icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>` }
    ]
  },
  settings: {
    title: "Settings",
    tabs: [
      { id: "settings-general", label: "General", icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/></svg>` },
      { id: "settings-ai", label: "AI", icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a10 10 0 1 0 10 10H12V2z"/><path d="M12 12L2.1 14.8M12 12l7.1 7.1"/></svg>` },
      { id: "settings-privacy", label: "Privacy & Data", icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>` },
      { id: "settings-keys", label: "API Keys", icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>` }
    ]
  },
  help: {
    title: "Help & Privacy",
    tabs: [
      { id: "help-center", label: "Help Center", icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>` },
      { id: "help-privacy", label: "Privacy", icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>` }
    ]
  }
};

let currentModalType = null;
let currentTabId = null;

function openModal(type) {
  currentModalType = type;
  const config = MODAL_CONFIG[type];
  if (!config) return;
  
  // Render Sidebar
  modalSidebar.innerHTML = `<h3>${config.title}</h3>`;
  config.tabs.forEach((tab, index) => {
    const btn = document.createElement("div");
    btn.className = "modal-tab";
    btn.dataset.id = tab.id;
    btn.innerHTML = `${tab.icon} ${tab.label}`;
    btn.addEventListener("click", () => switchTab(tab.id));
    modalSidebar.appendChild(btn);
  });

  // Render Sections (empty initially)
  modalSectionsContainer.innerHTML = "";
  config.tabs.forEach(tab => {
    const sec = document.createElement("div");
    sec.className = "modal-section";
    sec.id = "sec-" + tab.id;
    modalSectionsContainer.appendChild(sec);
  });

  // Show Modal
  globalModal.classList.add("show");
  
  // Initialize content
  if (type === 'profile') initProfileContent();
  if (type === 'settings') initSettingsContent();
  if (type === 'help') initHelpContent();

  // Switch to first tab
  switchTab(config.tabs[0].id);
}

function closeModal() {
  globalModal.classList.remove("show");
}

function switchTab(tabId) {
  // Update sidebar active class
  document.querySelectorAll(".modal-tab").forEach(t => t.classList.remove("active"));
  document.querySelector(`.modal-tab[data-id="${tabId}"]`)?.classList.add("active");

  // Update sections active class
  document.querySelectorAll(".modal-section").forEach(s => s.classList.remove("active"));
  document.getElementById("sec-" + tabId)?.classList.add("active");
  
  currentTabId = tabId;

  // Handle special cases (e.g. Settings -> API Keys opens Profile -> API Keys)
  if (tabId === "settings-keys") {
    closeModal();
    setTimeout(() => {
      openModal("profile");
      switchTab("profile-keys");
    }, 100);
  }
}

// ---------------- Content Renderers ----------------

function initProfileContent() {
  // Profile Info Tab
  const infoSec = document.getElementById("sec-profile-info");
  const email = localStorage.getItem("agent_email") || "";
  infoSec.innerHTML = `
    <h2>Profile Information</h2>
    
    <div class="setting-row" style="align-items: flex-start;">
      <div class="setting-info">
        <div class="setting-title">Avatar</div>
        <div class="setting-desc">Personalize your account with a photo.</div>
      </div>
      <div style="display:flex; flex-direction:column; gap:8px; align-items:center;">
        <div id="modal-avatar-preview" style="width:64px; height:64px; border-radius:50%; background:var(--accent); color:white; display:flex; align-items:center; justify-content:center; font-size:24px; font-weight:600;">
          ${currentUserName.charAt(0).toUpperCase()}
        </div>
        <div style="display:flex; gap:8px;">
          <button class="btn" onclick="document.getElementById('avatar-upload').click()">Upload</button>
          <button class="btn btn-danger" onclick="removeAvatar()">Remove</button>
          <input type="file" id="avatar-upload" style="display:none" accept="image/*" onchange="handleAvatarUpload(event)">
        </div>
      </div>
    </div>

    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Name</div>
        <div class="setting-desc">Your display name.</div>
      </div>
      <div style="display:flex; gap:8px;">
        <input type="text" id="modal-name-input" class="setting-input" value="${currentUserName}">
        <button class="btn btn-primary" onclick="saveProfileName()">Save</button>
      </div>
    </div>

    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Email</div>
        <div class="setting-desc">Your account email address. (Read-only)</div>
      </div>
      <div style="color:var(--text-muted); font-size:13.5px;">${email}</div>
    </div>
  `;
  
  if (currentUserAvatar) {
    const preview = document.getElementById("modal-avatar-preview");
    preview.style.backgroundImage = `url(${currentUserAvatar})`;
    preview.style.backgroundSize = "cover";
    preview.textContent = "";
  }

  // API Keys Tab
  const keysSec = document.getElementById("sec-profile-keys");
  keysSec.innerHTML = `
    <h2>My API Keys</h2>
    <p>Create and manage your API keys. Keys are stored securely in your account.</p>
    
    <div style="margin-bottom: 24px;">
      <button class="btn btn-primary" onclick="showCreateKeyUI()">+ Create API Key</button>
    </div>
    
    <div id="create-key-ui" style="display:none; margin-bottom: 24px; padding: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--bg);">
      <h4 style="margin-top:0">New API Key</h4>
      <div style="display:flex; gap:12px; flex-direction:column;">
        <select id="new-key-provider" class="setting-select" style="max-width:100%">
          <option value="groq">Groq</option>
          <option value="gemini">Google Gemini</option>
          <option value="openrouter">OpenRouter</option>
        </select>
        <input type="text" id="new-key-value" class="setting-input" style="max-width:100%" placeholder="Paste secret key here (sk-...)">
        <div style="display:flex; gap:8px;">
          <button class="btn btn-primary" onclick="submitCreateKey()" id="submit-key-btn">Save Key</button>
          <button class="btn" onclick="document.getElementById('create-key-ui').style.display='none'">Cancel</button>
        </div>
        <div id="new-key-error" style="color:var(--danger); font-size:12px; display:none;"></div>
      </div>
    </div>

    <div id="api-keys-list" style="display:flex; flex-direction:column; gap:12px;">
      <div style="font-size:13px; color:var(--text-muted);">Loading keys...</div>
    </div>
  `;
  loadUserKeys();

  // Security Tab
  const secSec = document.getElementById("sec-profile-security");
  secSec.innerHTML = `
    <h2>Security</h2>
    
    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Change Password</div>
        <div class="setting-desc">Update your account password.</div>
      </div>
      <button class="btn" onclick="showPasswordUI()">Change Password</button>
    </div>
    
    <div id="password-ui" style="display:none; margin-top: 16px; padding: 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--bg);">
      <h4 style="margin-top:0">Change Password</h4>
      <div style="display:flex; flex-direction:column; gap:12px;">
        <input type="password" id="pw-current" class="setting-input" style="max-width:100%" placeholder="Current password">
        <input type="password" id="pw-new" class="setting-input" style="max-width:100%" placeholder="New password (min 6 chars)">
        <input type="password" id="pw-confirm" class="setting-input" style="max-width:100%" placeholder="Confirm new password">
        <div style="display:flex; gap:8px;">
          <button class="btn btn-primary" onclick="submitPasswordChange()" id="submit-pw-btn">Update Password</button>
          <button class="btn" onclick="document.getElementById('password-ui').style.display='none'">Cancel</button>
        </div>
        <div id="pw-error" style="color:var(--danger); font-size:13px; display:none;"></div>
        <div id="pw-success" style="color:#4CAF50; font-size:13px; display:none;">Password updated successfully!</div>
      </div>
    </div>

    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Account Created</div>
        <div class="setting-desc">When you joined the platform.</div>
      </div>
      <div style="font-size:13.5px;">August 30, 2026</div>
    </div>
    
    <div style="margin-top: 40px;">
      <h4 style="color:var(--danger);">Danger Zone</h4>
      <div class="setting-row" style="border: 1px solid #F8D7D2; padding: 16px; border-radius: 12px; background: #FFF5F4;">
        <div class="setting-info">
          <div class="setting-title" style="color:var(--danger);">Delete account</div>
          <div class="setting-desc" style="color:var(--danger);">Permanently delete your account and associated data.</div>
        </div>
        <button class="btn btn-danger" onclick="deleteAccountPlaceholder()">Delete Account</button>
      </div>
    </div>
  `;
}

function initSettingsContent() {
  const genSec = document.getElementById("sec-settings-general");
  genSec.innerHTML = `
    <h2>General</h2>
    
    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Appearance</div>
        <div class="setting-desc">Choose your preferred theme.</div>
      </div>
      <select class="setting-select" id="theme-select" onchange="changeTheme(this.value)">
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </div>

    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Language</div>
        <div class="setting-desc">Application language.</div>
      </div>
      <select class="setting-select">
        <option>Auto</option>
        <option>English</option>
        <option>বাংলা</option>
      </select>
    </div>

    <h4>Chat Preferences</h4>
    
    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Enter to send</div>
        <div class="setting-desc">Send messages with Enter instead of Shift+Enter.</div>
      </div>
      <div class="toggle-switch on" onclick="this.classList.toggle('on')"></div>
    </div>
    
    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Show timestamps</div>
        <div class="setting-desc">Display time next to messages.</div>
      </div>
      <div class="toggle-switch" onclick="this.classList.toggle('on')"></div>
    </div>
  `;
  document.getElementById("theme-select").value = currentTheme;

  const aiSec = document.getElementById("sec-settings-ai");
  aiSec.innerHTML = `
    <h2>AI Settings</h2>
    
    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Default Model</div>
        <div class="setting-desc">The model used when starting a new chat.</div>
      </div>
      <select class="setting-select">
        <option>Groq (Llama 3 8B)</option>
        <option>Gemini 1.5 Flash</option>
        <option>OpenRouter Auto</option>
      </select>
    </div>

    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Response Style</div>
        <div class="setting-desc">How you prefer the AI to respond.</div>
      </div>
      <select class="setting-select">
        <option>Balanced</option>
        <option>Concise</option>
        <option>Detailed</option>
      </select>
    </div>
    
    <div style="margin-top: 16px;">
      <div class="setting-title">Additional Instructions</div>
      <div class="setting-desc" style="margin-bottom: 8px;">Custom instructions sent with every message.</div>
      <textarea class="setting-input" style="width:100%; max-width:100%; height:80px; resize:vertical;" placeholder="e.g. Explain technical topics in simple English."></textarea>
    </div>
  `;

  const privSec = document.getElementById("sec-settings-privacy");
  privSec.innerHTML = `
    <h2>Privacy & Data</h2>
    
    <div class="setting-row">
      <div class="setting-info">
        <div class="setting-title">Save chat history</div>
        <div class="setting-desc">Save conversations to your account so you can access them later.</div>
      </div>
      <div class="toggle-switch on" onclick="this.classList.toggle('on')"></div>
    </div>

    <div class="setting-row" style="margin-top: 24px;">
      <div class="setting-info">
        <div class="setting-title">Clear all conversations</div>
        <div class="setting-desc">Delete all conversations from your account permanently.</div>
      </div>
      <button class="btn btn-danger" onclick="clearAllConversations()" id="clear-conv-btn">Clear all conversations</button>
    </div>
  `;
}

function initHelpContent() {
  const helpSec = document.getElementById("sec-help-center");
  helpSec.innerHTML = `
    <h2>Help Center</h2>
    <p>Welcome to the Help Center. Here you can find guides on how to use the platform.</p>
    
    <h4>Getting Started</h4>
    <p>To start a new chat, click the "New chat" button in the top left corner of the sidebar. You can select your preferred AI model before sending your first message.</p>
    
    <h4>Models & AI</h4>
    <p><strong>Fast Models (e.g. Groq):</strong> Best for quick, everyday answers and drafting text.<br>
    <strong>Reasoning Models (e.g. Gemini):</strong> Better for complex logic, file analysis, and deep coding problems.</p>
    
    <h4>API Keys</h4>
    <p>If you run out of your daily free quota, you can add your own API key in the Profile > My API Keys section. This allows you to continue chatting using your own provider account without limits.</p>

    <div style="margin-top: 32px; padding-top: 24px; border-top: 1px solid var(--border);">
      <h4>Report a problem</h4>
      <textarea class="setting-input" style="width:100%; max-width:100%; height:80px; margin-bottom:12px;" placeholder="Describe the issue..."></textarea>
      <button class="btn">Submit report</button>
    </div>
  `;

  const privSec = document.getElementById("sec-help-privacy");
  privSec.innerHTML = `
    <h2>Privacy & Terms</h2>
    <p>We take your privacy seriously. Your data is encrypted and stored securely.</p>
    
    <h4>Data Usage</h4>
    <p>We collect only the information necessary to provide the service. Chat data is stored in your account so you can access your history across devices. If you use your own API keys, they are encrypted in the database before storage.</p>
    
    <h4>Terms of Service</h4>
    <p style="color:var(--text-muted);">Terms of service document is pending review.</p>
  `;
}

// ---------------- Action Handlers ----------------

function handleAvatarUpload(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (event) => {
    currentUserAvatar = event.target.result;
    localStorage.setItem("app_user_avatar", currentUserAvatar);
    
    const preview = document.getElementById("modal-avatar-preview");
    preview.style.backgroundImage = `url(${currentUserAvatar})`;
    preview.style.backgroundSize = "cover";
    preview.textContent = "";
    
    updateSidebarProfile();
  };
  reader.readAsDataURL(file);
}

function removeAvatar() {
  currentUserAvatar = null;
  localStorage.removeItem("app_user_avatar");
  const preview = document.getElementById("modal-avatar-preview");
  preview.style.backgroundImage = "none";
  preview.textContent = currentUserName.charAt(0).toUpperCase();
  updateSidebarProfile();
}

function saveProfileName() {
  const input = document.getElementById("modal-name-input").value.trim();
  if (input) {
    currentUserName = input;
    localStorage.setItem("app_user_name", input);
    if (!currentUserAvatar) {
      document.getElementById("modal-avatar-preview").textContent = currentUserName.charAt(0).toUpperCase();
    }
    updateSidebarProfile();
    const btn = event.target;
    btn.textContent = "Saved!";
    setTimeout(() => btn.textContent = "Save", 2000);
  }
}

function changeTheme(theme) {
  localStorage.setItem("app_theme", theme);
  applyTheme(theme);
}

async function deleteAccountPlaceholder() {
  if (confirm("Are you sure you want to delete your account? This action CANNOT be undone and all your data will be permanently erased.")) {
    try {
      const res = await fetch(`${window.BACKEND_URL}/user`, {
        method: "DELETE",
        headers: window.authHeaders()
      });
      if (!res.ok) throw new Error("Failed to delete account");
      alert("Account successfully deleted.");
      window.logout();
    } catch (err) {
      alert("Error deleting account. Please try again.");
    }
  }
}

async function clearAllConversations() {
  if (confirm("Clear all conversations? This action CANNOT be undone.")) {
    const btn = document.getElementById("clear-conv-btn");
    btn.disabled = true;
    btn.textContent = "Clearing...";
    try {
      const res = await fetch(`${window.BACKEND_URL}/conversations`, {
        method: "DELETE",
        headers: window.authHeaders()
      });
      if (!res.ok) throw new Error("Failed to clear conversations");
      alert("All conversations cleared successfully.");
      if(window.loadConversations) window.loadConversations();
      if(window.clearChatArea) window.clearChatArea();
    } catch (err) {
      alert("Error clearing conversations.");
    } finally {
      btn.disabled = false;
      btn.textContent = "Clear all conversations";
    }
  }
}

function showPasswordUI() {
  document.getElementById("password-ui").style.display = "block";
  document.getElementById("pw-current").value = "";
  document.getElementById("pw-new").value = "";
  document.getElementById("pw-confirm").value = "";
  document.getElementById("pw-error").style.display = "none";
  document.getElementById("pw-success").style.display = "none";
}

async function submitPasswordChange() {
  const current = document.getElementById("pw-current").value;
  const newPw = document.getElementById("pw-new").value;
  const confirmPw = document.getElementById("pw-confirm").value;
  const errorEl = document.getElementById("pw-error");
  const successEl = document.getElementById("pw-success");
  const btn = document.getElementById("submit-pw-btn");
  
  errorEl.style.display = "none";
  successEl.style.display = "none";
  
  if (!current || !newPw || !confirmPw) {
    errorEl.textContent = "Please fill in all fields";
    errorEl.style.display = "block";
    return;
  }
  if (newPw !== confirmPw) {
    errorEl.textContent = "New passwords do not match";
    errorEl.style.display = "block";
    return;
  }
  if (newPw.length < 6) {
    errorEl.textContent = "New password must be at least 6 characters";
    errorEl.style.display = "block";
    return;
  }
  
  btn.disabled = true;
  btn.textContent = "Updating...";
  
  try {
    const res = await fetch(`${window.BACKEND_URL}/user/password`, {
      method: "PUT",
      headers: { ...window.authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: current, new_password: newPw })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to update password");
    
    successEl.style.display = "block";
    document.getElementById("pw-current").value = "";
    document.getElementById("pw-new").value = "";
    document.getElementById("pw-confirm").value = "";
    setTimeout(() => {
        document.getElementById("password-ui").style.display = "none";
    }, 2000);
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = "Update Password";
  }
}

// ---------------- API Keys Integration ----------------

async function loadUserKeys() {
  const container = document.getElementById("api-keys-list");
  try {
    const res = await fetch(`${window.BACKEND_URL}/user/keys`, { headers: window.authHeaders() });
    if (!res.ok) throw new Error("Failed to load");
    const data = await res.json();
    const keys = Array.isArray(data) ? data : (data.keys || []);
    
    if (keys.length === 0) {
      container.innerHTML = `<div style="font-size:13px; color:var(--text-muted);">No API keys added yet.</div>`;
      return;
    }
    
    container.innerHTML = "";
    keys.forEach(k => {
      const el = document.createElement("div");
      el.className = "api-key-box";
      
      const created = new Date(k.created_at).toLocaleDateString();
      const labels = window.PROVIDER_LABELS || { groq: "Groq", gemini: "Gemini", openrouter: "OpenRouter" };
      const providerLabel = labels[k.provider] || k.provider;
      
      el.innerHTML = `
        <div class="api-key-header">
          <div class="api-key-name">${providerLabel} Key</div>
          <button class="btn btn-danger" style="padding: 4px 8px; font-size:12px;" onclick="deleteUserKey(${k.id})">Delete</button>
        </div>
        <div class="api-key-value">${k.key_masked || 'sk-...'}</div>
        <div class="api-key-meta">
          <span>Created: ${created}</span>
          <span>Status: <span style="color: ${k.status==='active'?'#4CAF50':'var(--danger)'}">${k.status}</span></span>
        </div>
      `;
      container.appendChild(el);
    });
  } catch (err) {
    container.innerHTML = `<div style="color:var(--danger); font-size:13px;">Error loading keys.</div>`;
  }
}

function showCreateKeyUI() {
  document.getElementById("create-key-ui").style.display = "block";
  document.getElementById("new-key-value").value = "";
  document.getElementById("new-key-error").style.display = "none";
}

async function submitCreateKey() {
  const provider = document.getElementById("new-key-provider").value;
  const keyVal = document.getElementById("new-key-value").value.trim();
  const errorEl = document.getElementById("new-key-error");
  const btn = document.getElementById("submit-key-btn");
  
  if (!keyVal) {
    errorEl.textContent = "Please enter an API key";
    errorEl.style.display = "block";
    return;
  }
  
  btn.disabled = true;
  btn.textContent = "Saving...";
  
  try {
    const res = await fetch(`${window.BACKEND_URL}/user/keys`, {
      method: "POST",
      headers: { ...window.authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ provider: provider, api_key: keyVal })
    });
    
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Failed to save key");
    }
    
    document.getElementById("create-key-ui").style.display = "none";
    loadUserKeys();
  } catch (err) {
    errorEl.textContent = err.message || "Error saving API key";
    errorEl.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Key";
  }
}

async function deleteUserKey(id) {
  if (!confirm("Are you sure you want to delete this API key?")) return;
  try {
    await fetch(`${window.BACKEND_URL}/user/keys/${id}`, {
      method: "DELETE",
      headers: window.authHeaders()
    });
    loadUserKeys();
  } catch (err) {
    alert("Failed to delete key");
  }
}
