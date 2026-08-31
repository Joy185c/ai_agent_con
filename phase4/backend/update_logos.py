import os

base_dir = r"d:\CONTINUUM AI V2\phase4\frontend"

# HTML files to process
html_files = ["landing.html", "app.html", "admin.html"]
favicon_link = '\n  <link rel="icon" type="image/svg+xml" href="/static/logo.svg">'

for file_name in html_files:
    path = os.path.join(base_dir, file_name)
    if not os.path.exists(path):
        continue
        
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Inject favicon
    if '<link rel="icon"' not in content:
        content = content.replace("</title>", "</title>" + favicon_link)
        
    # App.html specific
    if file_name == "app.html":
        content = content.replace(
            '<span class="dot"></span>',
            '<img src="/static/logo.svg" style="width:18px;height:18px;border-radius:5px;box-shadow:0 2px 5px rgba(214,123,90,0.5);">'
        )
        
    # Landing.html specific
    if file_name == "landing.html":
        import re
        content = re.sub(
            r'<svg.*?<path d="M12 2v20M17 5H9\.5a3\.5 3\.5 0 0 0 0 7h5a3\.5 3\.5 0 0 1 0 7H6"/>.*?</svg>',
            '<img src="/static/logo.svg" style="width:28px;height:28px;border-radius:6px;box-shadow:0 3px 10px rgba(214,123,90,0.5);">',
            content,
            flags=re.DOTALL
        )
        
    # Admin.html specific
    if file_name == "admin.html":
        import re
        content = re.sub(
            r'<div class="auth-logo-icon">.*?</div>',
            '<img src="/static/logo.svg" class="auth-logo-icon" style="background:none;box-shadow:0 8px 20px rgba(214,123,90,0.4);">',
            content,
            flags=re.DOTALL
        )
        content = re.sub(
            r'<div class="sb-logo-icon">.*?</div>',
            '<img src="/static/logo.svg" class="sb-logo-icon" style="background:none;box-shadow:0 4px 12px rgba(214,123,90,0.4);">',
            content,
            flags=re.DOTALL
        )
        
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
        
print("Successfully updated logos in HTML files.")
