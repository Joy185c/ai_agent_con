// about.js - Logic for fetching and rendering the About Continuum AI page

// Inject premium styles for About Page
const aboutStyles = document.createElement('style');
aboutStyles.innerHTML = `
  .about-screen-overlay {
    background: var(--bg);
    color: var(--text);
    font-family: inherit;
    scroll-behavior: smooth;
  }
  .about-content-wrapper {
    max-width: 760px !important;
    margin: 0 auto;
    padding: 80px 24px 120px 24px !important;
    min-height: 100vh;
  }
  
  /* Typography */
  .about-p {
    font-size: 16px;
    line-height: 1.8;
    color: var(--text-muted);
    margin-bottom: 1.2em;
  }
  .about-p strong {
    color: var(--text);
    font-weight: 600;
  }
  .about-h1 {
    font-size: 42px;
    font-weight: 800;
    letter-spacing: -0.03em;
    margin: 0 0 16px 0;
    color: var(--text);
    line-height: 1.2;
  }
  .about-subtitle {
    font-size: 20px;
    color: var(--accent);
    font-weight: 500;
    margin-bottom: 32px;
    letter-spacing: -0.01em;
  }
  .about-h2 {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.02em;
    margin: 0 0 24px 0;
    color: var(--text);
  }
  
  /* Animations */
  .about-fade-in {
    opacity: 0;
    transform: translateY(20px);
    animation: aboutFadeIn 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  }
  @keyframes aboutFadeIn {
    to { opacity: 1; transform: translateY(0); }
  }
  
  /* Sections */
  .about-section {
    margin-bottom: 80px;
  }
  .about-hero {
    text-align: center;
    margin-bottom: 100px;
    padding-top: 40px;
  }
  
  /* Cards */
  .about-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 24px;
    margin-top: 32px;
  }
  .about-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    padding: 32px;
    border-radius: 16px;
    transition: transform 0.3s ease, box-shadow 0.3s ease;
  }
  .about-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 32px rgba(0,0,0,0.06);
    border-color: var(--accent);
  }
  .about-card h3 {
    font-size: 18px;
    font-weight: 600;
    margin: 0 0 12px 0;
    color: var(--text);
  }
  .about-card p {
    font-size: 15px;
    color: var(--text-muted);
    margin: 0;
    line-height: 1.6;
  }
  
  /* Beliefs */
  .about-belief-item {
    padding: 24px 0;
    border-bottom: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .about-belief-item h3 {
    font-size: 18px;
    font-weight: 600;
    color: var(--accent);
    margin: 0;
  }
  .about-belief-item p {
    font-size: 16px;
    color: var(--text);
    margin: 0;
    line-height: 1.6;
  }
  
  /* Vision */
  .about-vision {
    text-align: center;
    padding: 64px 40px;
    background: var(--bg-card);
    border-radius: 24px;
    border: 1px solid var(--border);
    box-shadow: 0 8px 32px rgba(0,0,0,0.03);
    margin-bottom: 100px;
  }
  .about-vision .about-h2 {
    margin-bottom: 32px;
  }
  
  /* Founder */
  .about-founder-container {
    display: flex;
    flex-wrap: wrap;
    gap: 48px;
    align-items: center;
    margin-bottom: 100px;
  }
  .about-founder-img-wrapper {
    flex: 1;
    min-width: 260px;
    display: flex;
    justify-content: center;
  }
  .about-founder-img {
    width: 100%;
    max-width: 320px;
    border-radius: 20px;
    box-shadow: 0 20px 40px rgba(0,0,0,0.1);
    border: 1px solid var(--border);
    object-fit: cover;
    aspect-ratio: 1/1;
  }
  .about-founder-info {
    flex: 1.5;
    min-width: 300px;
  }
  .about-founder-name {
    font-weight: 700;
    font-size: 18px;
    color: var(--text);
    margin-bottom: 4px;
  }
  .about-founder-role {
    color: var(--accent);
    font-size: 15px;
    font-weight: 500;
  }
  .about-links {
    display: flex;
    gap: 20px;
    margin-top: 32px;
    flex-wrap: wrap;
  }
  .about-links a {
    color: var(--text);
    text-decoration: none;
    font-size: 14px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    background: var(--bg-sidebar);
    border-radius: 8px;
    border: 1px solid var(--border);
    transition: all 0.2s ease;
  }
  .about-links a:hover {
    background: var(--bg-card);
    border-color: var(--accent);
    color: var(--accent);
  }
  
  /* Closing */
  .about-closing {
    text-align: center;
    border-top: 1px solid var(--border);
    padding-top: 80px;
    margin-bottom: 40px;
  }
  .about-closing p {
    font-size: 20px;
    font-weight: 500;
    color: var(--text);
    line-height: 1.8;
  }
`;
document.head.appendChild(aboutStyles);

function openAboutPage() {
  document.getElementById('about-screen').style.display = 'block';
  document.getElementById('profile-popover').classList.remove('show');
  fetchAboutContent();
}

function closeAboutPage() {
  document.getElementById('about-screen').style.display = 'none';
}

async function fetchAboutContent() {
  const container = document.getElementById('about-content');
  container.innerHTML = '<div style="text-align:center; padding:100px 0; color:var(--text-muted);">Loading...</div>';
  
  try {
    const res = await fetch(`${window.BACKEND_URL}/about`, { headers: window.authHeaders() });
    if (!res.ok) throw new Error('Failed to load about sections');
    const sections = await res.json();
    renderAboutPage(sections);
  } catch(e) {
    container.innerHTML = `<div style="text-align:center; padding:100px 0; color:var(--danger);">Error: ${e.message}</div>`;
  }
}

// Enhanced Markdown Parser
function parseMarkdown(text, useParagraphs = true) {
  if (!text) return '';
  let html = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  
  // Bold
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  // Italic
  html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
  
  if (useParagraphs) {
    // Split by double newline into paragraphs
    const paragraphs = html.split(/\n\s*\n/).filter(p => p.trim());
    return paragraphs.map(p => `<p class="about-p">${p.replace(/\n/g, '<br>')}</p>`).join('');
  } else {
    return html.replace(/\n/g, '<br>');
  }
}

function renderAboutPage(sections) {
  const container = document.getElementById('about-content');
  
  if (!sections || sections.length === 0) {
    container.innerHTML = '<div style="text-align:center; padding:100px 0; color:var(--text-muted);">No content available.</div>';
    return;
  }
  
  let html = '';
  
  sections.forEach((section, index) => {
    let metadata = {};
    if (section.metadata) {
      try { metadata = JSON.parse(section.metadata); } catch(e) {}
    }
    
    // Add staggered animation delay
    const delay = index * 0.1;
    const animationStyle = `style="animation-delay: ${delay}s"`;
    
    if (section.section_type === 'hero') {
      html += `
        <div class="about-hero about-fade-in" ${animationStyle}>
          <h1 class="about-h1">${parseMarkdown(section.title, false)}</h1>
          ${section.subtitle ? `<div class="about-subtitle">${parseMarkdown(section.subtitle, false)}</div>` : ''}
          <div style="max-width: 600px; margin: 0 auto;">
            ${parseMarkdown(section.content)}
          </div>
        </div>
      `;
    } 
    else if (section.section_type === 'text') {
      html += `
        <div class="about-section about-fade-in" ${animationStyle}>
          ${section.title ? `<h2 class="about-h2">${parseMarkdown(section.title, false)}</h2>` : ''}
          <div>${parseMarkdown(section.content)}</div>
        </div>
      `;
    }
    else if (section.section_type === 'feature_grid') {
      const items = metadata.items || [];
      const gridHtml = items.map(item => `
        <div class="about-card">
          <h3>${parseMarkdown(item.title, false)}</h3>
          <p>${parseMarkdown(item.description, false)}</p>
        </div>
      `).join('');
      
      html += `
        <div class="about-section about-fade-in" ${animationStyle}>
          ${section.title ? `<h2 class="about-h2">${parseMarkdown(section.title, false)}</h2>` : ''}
          ${section.content ? `<div style="margin-bottom:24px;">${parseMarkdown(section.content)}</div>` : ''}
          <div class="about-grid">
            ${gridHtml}
          </div>
        </div>
      `;
    }
    else if (section.section_type === 'belief_grid') {
      const items = metadata.items || [];
      const gridHtml = items.map(item => `
        <div class="about-belief-item">
          <h3>${parseMarkdown(item.title, false)}</h3>
          <p>${parseMarkdown(item.description, false)}</p>
        </div>
      `).join('');
      
      html += `
        <div class="about-section about-fade-in" ${animationStyle}>
          ${section.title ? `<h2 class="about-h2">${parseMarkdown(section.title, false)}</h2>` : ''}
          <div>
            ${gridHtml}
          </div>
        </div>
      `;
    }
    else if (section.section_type === 'vision') {
      html += `
        <div class="about-vision about-fade-in" ${animationStyle}>
          ${section.title ? `<h2 class="about-h2">${parseMarkdown(section.title, false)}</h2>` : ''}
          <div style="max-width: 500px; margin: 0 auto;">
            ${parseMarkdown(section.content)}
          </div>
        </div>
      `;
    }
    else if (section.section_type === 'founder') {
      const name = metadata.name || section.title || 'Founder';
      const role = metadata.role || '';
      const links = metadata.links || [];
      
      const dbImageUrl = section.image_url || '/static/founder.jpg';
      const imageUrl = dbImageUrl.startsWith('http') ? dbImageUrl : window.BACKEND_URL + dbImageUrl;
      
      const linksHtml = links.map(l => `
        <a href="${l.url}" target="_blank">
          ${l.label}
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17l9.2-9.2M17 17V7H7"/></svg>
        </a>
      `).join('');
      
      html += `
        <div class="about-founder-container about-fade-in" ${animationStyle}>
          <div class="about-founder-img-wrapper">
            <img src="${imageUrl}" alt="${section.image_alt || name}" class="about-founder-img">
          </div>
          <div class="about-founder-info">
            ${section.title ? `<h2 class="about-h2" style="margin-bottom:16px;">${parseMarkdown(section.title, false)}</h2>` : ''}
            <div style="margin-bottom:32px;">${parseMarkdown(section.content)}</div>
            
            <div>
              <div class="about-founder-name">${name}</div>
              <div class="about-founder-role">${parseMarkdown(role, false)}</div>
            </div>
            
            <div class="about-links">${linksHtml}</div>
          </div>
        </div>
      `;
    }
    else if (section.section_type === 'closing') {
      html += `
        <div class="about-closing about-fade-in" ${animationStyle}>
          ${parseMarkdown(section.content)}
        </div>
      `;
    }
  });
  
  container.innerHTML = html;
}
