import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import csv
import networkx as nx
from pyvis.network import Network
import time

# --- ADD YOUR EXCLUSION LIST HERE ---
# Supports exact URLs or partial path patterns (e.g., "/alphabetical", "/tags/", "/all-authors")
EXCLUDE_PATTERNS = [
    "https://www.pcc.edu/accessibility/training/knowlege-base", # Example exact URL to block
    "https://www.pcc.edu/accessibility/accessibility-knowledge-base",
    "https://www.pcc.edu/accessibility/knowledge-base/"
]

# initial physics options
options = '''options = {
  "configure": {
    "enabled": true,
    "filter": ["physics"]
  },
  "physics": {
    "barnesHut": {
      "gravitationalConstant": -5300,
      "springLength": 150,
      "springConstant": 0.015,
      "damping": 0.2,
      "avoidOverlap": 0.28
    },
    "minVelocity": 0.75
  }
}'''

def normalize_url(url):
    """Normalizes URLs by removing anchors/fragments and trailing slashes."""
    url = url.split('#')[0]  # Strip anchors/fragments
    parsed = urlparse(url)
    
    # Strip trailing slash from path (e.g., /about/ -> /about)
    path = parsed.path.rstrip('/')
    
    # Rebuild normalized URL
    normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
        
    return normalized

def is_excluded(url, exclude_patterns):
    """Checks if a URL matches any excluded pattern or URL."""
    url_lower = url.lower()
    return any(pattern.lower() in url_lower for pattern in exclude_patterns)

def get_internal_links(url, base_domain, exclude_patterns):
    """Fetches internal links from body content, omitting excluded or duplicate URLs."""
    internal_links = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Bot/1.0'}
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if 'text/html' not in response.headers.get('Content-Type', ''):
            return internal_links
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Strip structural navigation
        for nav_tag in soup.find_all(['nav', 'header', 'footer', 'aside']):
            nav_tag.decompose()
            
        nav_keywords = ['nav', 'header', 'footer', 'menu', 'sidebar']
        for element in soup.find_all(lambda tag: any(kw in ' '.join(tag.get('class', [])).lower() or kw in str(tag.get('id', '')).lower() for kw in nav_keywords)):
            element.decompose()
            
        # 2. Extract and normalize remaining links
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            
            if href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                continue
                
            full_url = normalize_url(urljoin(url, href))
            
            # Domain check, self-link check, and exclusion check
            if urlparse(full_url).netloc == base_domain and full_url != url and not is_excluded(full_url, exclude_patterns):
                internal_links.add(full_url)
                
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        
    return internal_links

def crawl_and_map(start_url, exclude_patterns, max_pages=100):
    """Crawls domain while normalizing URLs to prevent trailing-slash duplicates."""
    start_url = normalize_url(start_url)
    base_domain = urlparse(start_url).netloc
    
    visited = set()
    queue = [start_url]
    edges = set()  # Using a set to prevent duplicate (source, target) tuples
    
    print(f"Starting crawl of {base_domain} (Max pages: {max_pages})...")
    
    while queue and len(visited) < max_pages:
        current_url = queue.pop(0)
        
        if current_url in visited or is_excluded(current_url, exclude_patterns):
            continue
            
        print(f"Scraping: {current_url}")
        visited.add(current_url)
        
        links = get_internal_links(current_url, base_domain, exclude_patterns)
        
        for link in links:
            edges.add((current_url, link))
            if link not in visited and link not in queue:
                queue.append(link)
                
        time.sleep(0.5) 
        
    return list(edges)

def export_to_csv(edges, filename="website_edges.csv"):
    with open(filename, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "Target"])
        writer.writerows(edges)
    print(f"\nSaved {len(edges)} unique connections to {filename}")

def build_visual_graph(edges, start_url, output_file="site_map.html"):
    start_url = normalize_url(start_url)
    G = nx.DiGraph()
    G.add_edges_from(edges)
    
    for node in G.nodes():
        degree = G.degree(node)
        size = 10 + (degree * 2) 
        color = "#97C2FC" 
        
        node_lower = node.lower()
        if "contact" in node_lower or "about" in node_lower:
            color = "#57D9A3" 
        elif "login" in node_lower or "cart" in node_lower or "checkout" in node_lower:
            color = "#FF8F73" 
            
        if node == start_url:
            color = "#FFD700" 
            size = 40
            
        G.nodes[node]['size'] = size
        G.nodes[node]['color'] = color
        G.nodes[node]['title'] = f"{node}\nConnections: {degree}"

    net = Network(height="800px", width="100%", bgcolor="#ffffff", font_color="black", directed=True)
    net.from_nx(G)
    net.set_options(options)
    # net.show_buttons(filter_=['physics'])
    net.save_graph(output_file)
    print(f"Successfully generated interactive map: {output_file}")

if __name__ == "__main__":
    if not isinstance(options, str): raise TypeError("Variable must be a string")
    START_URL = "https://www.pcc.edu/accessibility"
    
    site_edges = crawl_and_map(START_URL, EXCLUDE_PATTERNS, max_pages=50)
    export_to_csv(site_edges)
    build_visual_graph(site_edges, START_URL)
