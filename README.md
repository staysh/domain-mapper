# Domain Mapper

Static site maps and hop-finder dashboards for exploring user routes through websites.

## Install

```sh
git clone <this-repository>
cd path/to/the-repository
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Multi-Project Workflow

Create a YAML config for each site section you want to explore:

```yaml
name: Instructional Support
start_url: https://www.pcc.edu/instructional-support
max_pages: 50
delay_seconds: 0.5
allow_subdomains: false
limit_to_start_path: true

traffic:
  enabled: true
  dir: traffic-data
  internal_domains:
    - pcc.edu
  sample:
    divisor: 30
    rounding: nearest
  doors:
    enabled: true
    external_ratio_threshold: 0.5
    include_direct_in_denominator: true

graph:
  exclude:
    patterns:
      - /help-desk
  traffic:
    enabled: true
    node_heat:
      enabled: true
      scale: linear
      colors:
        - "#140B34"
        - "#84206B"
        - "#E55C30"
        - "#F6D746"
    edge_heat:
      enabled: true
      scale: linear
      colors:
        - "#140B34"
        - "#84206B"
        - "#E55C30"
        - "#F6D746"
    doors:
      enabled: true
      border_color: "#22C55E"
      border_width: 4
  colors:
    default: "#97C2FC"
    start: "#FFD700"
    rules:
      - color: "#57D9A3"
        urls:
          - https://www.pcc.edu/instructional-support/tools
        patterns:
          - /instructional-support/tools/d2lbrightspace

allow:
  patterns:
    - /instructional-support
    - /disability

exclude:
  patterns:
    - /tags/
    - /alphabetical
    - https://www.pcc.edu/example/exact-url
  strip_tags:
    - nav
    - header
    - footer
    - aside
  strip_class_or_id_keywords:
    - nav
    - header
    - footer
    - menu
    - sidebar
```

Run the mapper:

```sh
domain-mapper --project "Instructional Support" instructional-support.yaml
```

This writes a project dashboard to:

```text
projects/
  instructional-support/
    dashboard.html
    site_map.html
    hop_finder.html
    website_edges.csv
    traffic_processed.csv
    traffic_summary.json
    config.yaml
```

The root `index.html` is regenerated after each run by scanning `projects/*/config.yaml`, so GitHub Pages can show an index of every generated dashboard.

Re-running the same `--project` overwrites that project folder. Running a new project name creates a new folder.

## Options

```sh
domain-mapper [--project "Display Name"] [--output-root projects] config.yaml
domain-mapper --refresh [--project "Display Name"] config.yaml
domain-mapper --index-only
```

- `--project` overrides `name` from the YAML and controls the generated folder slug.
- `--refresh` rebuilds `site_map.html`, `hop_finder.html`, `dashboard.html`, and the saved config from the existing project `website_edges.csv` without scraping again.
- `traffic.enabled: true` enriches generated maps with pooled GA4 traffic data.
- `traffic.dir` points to a directory of GA4 CSV exports. Every `*.csv` in the directory is pooled.
- `traffic.sample.divisor` divides sampled view counts before rendering. With `30`, a GA4 row with `Views: 60` becomes `2`.
- `traffic.doors.external_ratio_threshold` marks nodes whose external incoming traffic share meets the threshold.
- `traffic.doors.include_direct_in_denominator` controls whether direct/no-referrer views count in the door ratio denominator.
- `allow_subdomains: false` only keeps links on the exact start URL host.
- `allow_subdomains: true` also keeps links from subdomains of the start URL host.
- `limit_to_start_path: true` only crawls URLs under the starting URL path.
- `limit_to_start_path: false` crawls the full allowed domain.
- `allow.patterns` limits the graph/crawl to URLs matching at least one listed pattern.
- `graph.exclude.patterns` hides matching URLs from the network map only.
- `graph.traffic.node_heat` colors nodes by total adjusted views.
- `graph.traffic.edge_heat` colors crawl edges by adjusted internal source-target views. Crawl edges without traffic are treated as `0`.
- `graph.traffic.*_heat.scale` can be `linear`, `log`, or `sqrt`. `log` compresses high-traffic outliers so more of the color range is visible.
- `graph.traffic.*_heat.colors` sets the heat palette from low to high. Older `low`/`mid`/`high` configs still work.
- `graph.traffic.doors` controls the border style for traffic door nodes.
- `graph.colors.default` sets the normal node color.
- `graph.colors.start` sets the start URL node color.
- `graph.colors.rules` colors exact `urls` or partial `patterns`, checked top to bottom.
- `graph.colors` still applies when traffic heat coloring is disabled.
- `exclude.patterns` blocks exact URLs or partial URL/path matches and wins over `allow.patterns`.
- `exclude.strip_tags` removes matching HTML tags before collecting links.
- `exclude.strip_selectors` removes matching CSS selectors before collecting links.
- `exclude.strip_class_or_id_keywords` removes elements whose class or ID contains any listed keyword.

## Legacy Scripts

The old commands still work for one-off generation in the repo root:

```sh
python mapper.py accessibility.yaml
python hop_finder_gen.py
python generate_dashboard.py
```
