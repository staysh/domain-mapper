import csv
import json

def generate_interactive_hop_finder(csv_file="website_edges.csv", output_html="hop_finder.html"):
    edges = []
    nodes = set()
    
    # Read edges and collect unique nodes
    with open(csv_file, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            edges.append({"source": row["Source"], "target": row["Target"]})
            nodes.add(row["Source"])
            nodes.add(row["Target"])
            
    sorted_nodes = sorted(list(nodes))
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Interactive Hop & Path Finder</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 900px; margin: 30px auto; padding: 0 20px; color: #333; line-height: 1.5; }}
        .card {{ background: #ffffff; border: 1px solid #e0e0e0; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        label {{ font-weight: bold; display: block; margin-top: 10px; }}
        select, button {{ width: 100%; padding: 10px; margin-top: 5px; border-radius: 4px; border: 1px solid #ccc; font-size: 14px; box-sizing: border-box; }}
        button {{ background: #0066cc; color: white; font-weight: bold; cursor: pointer; border: none; transition: background 0.2s; }}
        button:hover {{ background: #0052a3; }}
        
        /* Blocked Pills Styling */
        .blocked-container {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
        .pill {{ background: #ffebe9; border: 1px solid #ffc1c0; color: #cf222e; padding: 4px 10px; border-radius: 16px; font-size: 13px; display: inline-flex; align-items: center; gap: 6px; word-break: break-all; }}
        .pill-remove {{ cursor: pointer; font-weight: bold; background: #cf222e; color: white; border-radius: 50%; width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; border: none; padding: 0; }}
        .clear-btn {{ background: #6e7781; width: auto; padding: 6px 12px; font-size: 12px; margin-top: 10px; }}
        
        /* Path Results Styling */
        .result {{ padding: 15px 20px; background: #f0f7ff; border-left: 5px solid #0066cc; border-radius: 4px; }}
        .path-list {{ list-style-type: none; padding: 0; margin-top: 15px; }}
        .path-step {{ display: flex; align-items: center; justify-content: space-between; padding: 10px; background: #ffffff; border: 1px solid #e1e4e8; border-radius: 6px; margin-bottom: 8px; word-break: break-all; }}
        .exclude-btn {{ width: auto; padding: 4px 10px; font-size: 12px; background: #cf222e; margin: 0 0 0 10px; flex-shrink: 0; }}
        .exclude-btn:hover {{ background: #a40e26; }}
        .step-num {{ font-weight: bold; margin-right: 10px; color: #57606a; flex-shrink: 0; }}
        .no-path {{ background: #fff0f0; border-left-color: #cf222e; }}
    </style>
</head>
<body>

    <h2>Website Path Finder & Alternative Route Simulator</h2>
    
    <div class="card">
        <label for="startNode">Starting Page (Source):</label>
        <select id="startNode" onchange="calculateHops()"></select>

        <label for="targetNode">Target Page (Destination):</label>
        <select id="targetNode" onchange="calculateHops()"></select>
    </div>

    <!-- Interactive Exclusions Panel -->
    <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3 style="margin: 0;">Excluded Pages (<span id="blockedCount">0</span>)</h3>
            <button class="clear-btn" id="clearBtn" onclick="clearBlocked()" style="display:none;">Clear All Exclusions</button>
        </div>
        <p style="font-size: 13px; color: #666; margin: 5px 0 0 0;">Pages listed here are bypassed when finding paths.</p>
        <div id="blockedBadges" class="blocked-container">
            <em style="color: #888; font-size: 13px; margin-top: 5px;">No pages excluded yet. Click "✕ Exclude" on any path result below to test alternative routes.</em>
        </div>
    </div>

    <div id="output"></div>

    <script>
        const nodes = {json.dumps(sorted_nodes)};
        const edges = {json.dumps(edges)};
        let blockedNodes = new Set();

        // Safe HTML String Escaper
        function escapeHtml(str) {{
            return str
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }}

        // Populate Select Dropdowns
        const startSelect = document.getElementById('startNode');
        const targetSelect = document.getElementById('targetNode');

        nodes.forEach(node => {{
            startSelect.add(new Option(node, node));
            targetSelect.add(new Option(node, node));
        }});

        // Pre-build Graph Adjacency List
        const graph = {{}};
        edges.forEach(edge => {{
            if (!graph[edge.source]) graph[edge.source] = [];
            graph[edge.source].push(edge.target);
        }});

        // Fixed Exclude Handler (Proper Decoding)
        function blockNode(encodedUrl) {{
            const url = decodeURIComponent(encodedUrl);
            blockedNodes.add(url);
            updateBlockedUI();
            calculateHops();
        }}

        // Fixed Unblock Handler (Proper Decoding)
        function unblockNode(encodedUrl) {{
            const url = decodeURIComponent(encodedUrl);
            blockedNodes.delete(url);
            updateBlockedUI();
            calculateHops();
        }}

        function clearBlocked() {{
            blockedNodes.clear();
            updateBlockedUI();
            calculateHops();
        }}

        function updateBlockedUI() {{
            const badgesDiv = document.getElementById('blockedBadges');
            const countSpan = document.getElementById('blockedCount');
            const clearBtn = document.getElementById('clearBtn');
            
            countSpan.innerText = blockedNodes.size;
            
            if (blockedNodes.size === 0) {{
                badgesDiv.innerHTML = '<em style="color: #888; font-size: 13px; margin-top: 5px;">No pages excluded yet. Click "✕ Exclude" on any path result below to test alternative routes.</em>';
                clearBtn.style.display = 'none';
                return;
            }}

            clearBtn.style.display = 'inline-block';
            let html = '';
            blockedNodes.forEach(url => {{
                const encoded = encodeURIComponent(url);
                const safeUrl = escapeHtml(url);
                html += `
                    <div class="pill">
                        <span>${{safeUrl}}</span>
                        <button class="pill-remove" onclick="unblockNode('${{encoded}}')" title="Remove exclusion">✕</button>
                    </div>
                `;
            }});
            badgesDiv.innerHTML = html;
        }}

        function calculateHops() {{
            const start = startSelect.value;
            const target = targetSelect.value;
            const output = document.getElementById('output');

            if (start === target) {{
                output.innerHTML = '<div class="result"><strong>0 Hops:</strong> Source and Target are the same URL.</div>';
                return;
            }}

            if (blockedNodes.has(start) || blockedNodes.has(target)) {{
                output.innerHTML = `
                    <div class="result no-path">
                        <strong>Path Blocked:</strong> Either the starting page or target page is currently in your excluded list.
                    </div>`;
                return;
            }}

            // Breadth-First Search (BFS) strictly skipping blocked nodes
            const queue = [[start]];
            const visited = new Set([start]);
            let shortestPath = null;

            while (queue.length > 0) {{
                const path = queue.shift();
                const current = path[path.length - 1];

                if (current === target) {{
                    shortestPath = path;
                    break;
                }}

                const neighbors = graph[current] || [];
                for (const neighbor of neighbors) {{
                    // STRICT CHECK: Skip visited nodes AND blocked nodes
                    if (!visited.has(neighbor) && !blockedNodes.has(neighbor)) {{
                        visited.add(neighbor);
                        queue.push([...path, neighbor]);
                    }}
                }}
            }}

            if (shortestPath) {{
                const hops = shortestPath.length - 1;
                
                let stepsHtml = '<ul class="path-list">';
                shortestPath.forEach((url, index) => {{
                    const isEndNode = (index === 0 || index === shortestPath.length - 1);
                    const encoded = encodeURIComponent(url);
                    const safeUrl = escapeHtml(url);

                    stepsHtml += `
                        <li class="path-step">
                            <div>
                                <span class="step-num">[${{index}}]</span>
                                <a href="${{safeUrl}}" target="_blank" style="color:#0066cc;">${{safeUrl}}</a>
                            </div>
                            ${{!isEndNode ? `<button class="exclude-btn" onclick="blockNode('${{encoded}}')">✕ Exclude</button>` : '<span style="font-size:11px; color:#888;">(Terminal)</span>'}}
                        </li>
                    `;
                }});
                stepsHtml += '</ul>';

                output.innerHTML = `
                    <div class="result">
                        <h3 style="margin-top:0;">Shortest Path Found: ${{hops}} Hop${{hops > 1 ? 's' : ''}}</h3>
                        ${{stepsHtml}}
                    </div>
                `;
            }} else {{
                output.innerHTML = `
                    <div class="result no-path">
                        <h3 style="margin-top:0; color:#cf222e;">No Path Exists</h3>
                        <p>There are no remaining link routes connecting these two pages without using your excluded pages.</p>
                    </div>
                `;
            }}
        }}

        // Initial trigger
        calculateHops();
    </script>
</body>
</html>"""

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"Generated fixed interactive hop finder: {output_html}")

if __name__ == "__main__":
    generate_interactive_hop_finder()