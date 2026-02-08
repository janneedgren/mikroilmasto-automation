#!/usr/bin/env python3
"""
HTTP server for serving CFD analysis results via Cloudflare Tunnel
"""
import http.server
import socketserver
import os
from pathlib import Path

# Configuration
PORT = 8080
RESULTS_DIR = Path("/srv/simulations")  # Serve customer results from /srv/simulations

class MyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(RESULTS_DIR), **kwargs)

    def end_headers(self):
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        super().end_headers()

    def do_GET(self):
        # Custom index page for root
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()

            # List available projects
            projects = []
            if RESULTS_DIR.exists():
                for item in RESULTS_DIR.iterdir():
                    if item.is_dir():
                        projects.append(item.name)

            html = f"""
            <!DOCTYPE html>
            <html lang="fi">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>MikroilmastoCFD - Analyysit</title>
                <style>
                    body {{
                        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                        max-width: 1200px;
                        margin: 0 auto;
                        padding: 20px;
                        background: #f5f5f5;
                    }}
                    h1 {{
                        color: #2c3e50;
                        border-bottom: 3px solid #3498db;
                        padding-bottom: 10px;
                    }}
                    .project-list {{
                        display: grid;
                        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                        gap: 20px;
                        margin-top: 30px;
                    }}
                    .project-card {{
                        background: white;
                        border-radius: 8px;
                        padding: 20px;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                        transition: transform 0.2s;
                    }}
                    .project-card:hover {{
                        transform: translateY(-5px);
                        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
                    }}
                    .project-card a {{
                        text-decoration: none;
                        color: #2c3e50;
                        font-weight: bold;
                        font-size: 1.1em;
                    }}
                    .project-card a:hover {{
                        color: #3498db;
                    }}
                    .info {{
                        background: #e8f4f8;
                        padding: 15px;
                        border-radius: 5px;
                        margin-top: 20px;
                    }}
                </style>
            </head>
            <body>
                <h1>MikroilmastoCFD - Tuulianalyysit</h1>
                <p>Rakennusten ympäristön CFD-simulaatiot ja mikroilmastoanalyysit</p>

                <div class="info">
                    <strong>Projektit:</strong> {len(projects)} kpl
                </div>

                <div class="project-list">
                    {"".join([f'<div class="project-card"><a href="/{p}/">{p.replace("_", " ").title()}</a></div>' for p in sorted(projects)])}
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode())
            return

        # Serve files normally
        return super().do_GET()

if __name__ == "__main__":
    os.chdir(RESULTS_DIR.parent)

    with socketserver.TCPServer(("", PORT), MyHTTPRequestHandler) as httpd:
        print(f"✅ Serving results at http://localhost:{PORT}")
        print(f"📁 Directory: {RESULTS_DIR}")
        print(f"🌐 Accessible via: https://microclimateanalysis.com")
        print(f"\nPress Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n👋 Server stopped")
