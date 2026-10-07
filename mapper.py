import argparse
import copy
import csv
import json
import math
import re
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import networkx as nx
import requests
import yaml
from bs4 import BeautifulSoup
from pyvis.network import Network


DEFAULT_EXCLUDE_PATTERNS = [
    "https://www.pcc.edu/accessibility/training/knowlege-base",
    "https://www.pcc.edu/accessibility/accessibility-knowledge-base",
    "https://www.pcc.edu/accessibility/knowledge-base/",
]

DEFAULT_STRIP_TAGS = ["nav", "header", "footer", "aside"]
DEFAULT_STRIP_KEYWORDS = ["nav", "header", "footer", "menu", "sidebar"]
DEFAULT_OUTPUT_ROOT = "projects"
DEFAULT_GRAPH_COLORS = {
    "default": "#97C2FC",
    "start": "#FFD700",
    "rules": [],
}
DEFAULT_GRAPH_TRAFFIC = {
    "enabled": True,
    "node_heat": {
        "enabled": True,
        "scale": "linear",
        "colors": ["#140B34", "#84206B", "#E55C30", "#F6D746"],
    },
    "edge_heat": {
        "enabled": True,
        "scale": "linear",
        "colors": ["#140B34", "#84206B", "#E55C30", "#F6D746"],
    },
    "doors": {
        "enabled": True,
        "border_color": "#22C55E",
        "border_width": 4,
    },
}
DEFAULT_TRAFFIC_TRACKING_PREFIXES = ["utm_"]
DEFAULT_TRAFFIC_TRACKING_PARAMS = [
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
]

PHYSICS_OPTIONS = """options = {
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
}"""


@dataclass
class TrafficConfig:
    enabled: bool = False
    dir: str | None = None
    resolved_dir: str | None = None
    processed_output: str = "traffic_processed.csv"
    summary_output: str = "traffic_summary.json"
    internal_domains: list[str] | None = None
    views_column: str = "Views"
    sample_divisor: float = 30.0
    rounding: str = "nearest"
    strip_fragment: bool = True
    strip_trailing_slash: bool = True
    strip_tracking_params: bool = True
    strip_all_query: bool = False
    tracking_param_prefixes: list[str] | None = None
    tracking_params: list[str] | None = None
    doors_enabled: bool = True
    door_external_ratio_threshold: float = 0.5
    door_include_direct_in_denominator: bool = True

    def __post_init__(self):
        if self.internal_domains is None:
            self.internal_domains = ["pcc.edu"]
        if self.tracking_param_prefixes is None:
            self.tracking_param_prefixes = list(DEFAULT_TRAFFIC_TRACKING_PREFIXES)
        if self.tracking_params is None:
            self.tracking_params = list(DEFAULT_TRAFFIC_TRACKING_PARAMS)

    def to_yaml_data(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "dir": self.dir,
            "processed_output": self.processed_output,
            "summary_output": self.summary_output,
            "internal_domains": self.internal_domains,
            "sample": {
                "divisor": self.sample_divisor,
                "rounding": self.rounding,
            },
            "urls": {
                "strip_fragment": self.strip_fragment,
                "strip_trailing_slash": self.strip_trailing_slash,
                "strip_tracking_params": self.strip_tracking_params,
                "strip_all_query": self.strip_all_query,
                "tracking_param_prefixes": self.tracking_param_prefixes,
                "tracking_params": self.tracking_params,
            },
            "doors": {
                "enabled": self.doors_enabled,
                "external_ratio_threshold": self.door_external_ratio_threshold,
                "include_direct_in_denominator": self.door_include_direct_in_denominator,
            },
        }


@dataclass
class TrafficDataset:
    records: list[dict[str, Any]]
    edge_views: dict[tuple[str, str], int]
    node_total_views: dict[str, int]
    node_internal_views: dict[str, int]
    node_external_views: dict[str, int]
    node_direct_views: dict[str, int]
    warnings: list[str]
    file_ranges: dict[str, str | None]


@dataclass
class MapperConfig:
    name: str
    start_url: str
    max_pages: int = 50
    delay_seconds: float = 0.5
    allow_subdomains: bool = False
    limit_to_start_path: bool = True
    allow_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    strip_tags: list[str] | None = None
    strip_selectors: list[str] | None = None
    strip_class_or_id_keywords: list[str] | None = None
    graph_colors: dict[str, Any] | None = None
    graph_traffic: dict[str, Any] | None = None
    graph_exclude_patterns: list[str] | None = None
    traffic: TrafficConfig | None = None

    def __post_init__(self):
        if self.allow_patterns is None:
            self.allow_patterns = []
        if self.exclude_patterns is None:
            self.exclude_patterns = []
        if self.strip_tags is None:
            self.strip_tags = list(DEFAULT_STRIP_TAGS)
        if self.strip_selectors is None:
            self.strip_selectors = []
        if self.strip_class_or_id_keywords is None:
            self.strip_class_or_id_keywords = list(DEFAULT_STRIP_KEYWORDS)
        if self.graph_colors is None:
            self.graph_colors = dict(DEFAULT_GRAPH_COLORS)
        if self.graph_traffic is None:
            self.graph_traffic = copy.deepcopy(DEFAULT_GRAPH_TRAFFIC)
        if self.graph_exclude_patterns is None:
            self.graph_exclude_patterns = []
        if self.traffic is None:
            self.traffic = TrafficConfig()

    def to_yaml_data(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start_url": self.start_url,
            "max_pages": self.max_pages,
            "delay_seconds": self.delay_seconds,
            "allow_subdomains": self.allow_subdomains,
            "limit_to_start_path": self.limit_to_start_path,
            "allow": {
                "patterns": self.allow_patterns,
            },
            "exclude": {
                "patterns": self.exclude_patterns,
                "strip_tags": self.strip_tags,
                "strip_selectors": self.strip_selectors,
                "strip_class_or_id_keywords": self.strip_class_or_id_keywords,
            },
            "graph": {
                "exclude": {
                    "patterns": self.graph_exclude_patterns,
                },
                "colors": self.graph_colors,
                "traffic": self.graph_traffic,
            },
            "traffic": (
                self.traffic.to_yaml_data()
                if self.traffic
                else TrafficConfig().to_yaml_data()
            ),
        }


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise ValueError("Project name must contain at least one letter or number.")
    return slug


def deep_merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_traffic_config(raw: dict[str, Any], config_file: Path) -> TrafficConfig:
    traffic = raw.get("traffic") or {}
    sample = traffic.get("sample") or {}
    urls = traffic.get("urls") or {}
    doors = traffic.get("doors") or {}
    traffic_dir = traffic.get("dir") or traffic.get("directory")
    resolved_dir = None

    if traffic_dir:
        traffic_path = Path(str(traffic_dir))
        if not traffic_path.is_absolute():
            traffic_path = config_file.parent / traffic_path
        resolved_dir = str(traffic_path)

    return TrafficConfig(
        enabled=bool(traffic.get("enabled", bool(traffic_dir))),
        dir=str(traffic_dir) if traffic_dir else None,
        resolved_dir=resolved_dir,
        processed_output=str(traffic.get("processed_output", "traffic_processed.csv")),
        summary_output=str(traffic.get("summary_output", "traffic_summary.json")),
        internal_domains=list(traffic.get("internal_domains", ["pcc.edu"])),
        views_column=str(traffic.get("views_column", "Views")),
        sample_divisor=float(sample.get("divisor", traffic.get("sample_divisor", 30))),
        rounding=str(sample.get("rounding", traffic.get("rounding", "nearest"))),
        strip_fragment=bool(urls.get("strip_fragment", True)),
        strip_trailing_slash=bool(urls.get("strip_trailing_slash", True)),
        strip_tracking_params=bool(urls.get("strip_tracking_params", True)),
        strip_all_query=bool(urls.get("strip_all_query", False)),
        tracking_param_prefixes=list(
            urls.get("tracking_param_prefixes", DEFAULT_TRAFFIC_TRACKING_PREFIXES)
        ),
        tracking_params=list(urls.get("tracking_params", DEFAULT_TRAFFIC_TRACKING_PARAMS)),
        doors_enabled=bool(doors.get("enabled", True)),
        door_external_ratio_threshold=float(
            doors.get("external_ratio_threshold", 0.5)
        ),
        door_include_direct_in_denominator=bool(
            doors.get("include_direct_in_denominator", True)
        ),
    )


def load_config(config_file: Path, project_name: str | None = None) -> MapperConfig:
    with config_file.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    name = project_name or raw.get("name")
    start_url = raw.get("start_url")
    if not name:
        raise ValueError("Config must include 'name' unless --project is provided.")
    if not start_url:
        raise ValueError("Config must include 'start_url'.")

    allow = raw.get("allow") or {}
    exclude = raw.get("exclude") or {}
    limit_to_start_path = raw.get("limit_to_start_path")
    if limit_to_start_path is None:
        scope = str(raw.get("scope", "path"))
        if scope not in {"path", "domain"}:
            raise ValueError("Config value 'scope' must be either 'path' or 'domain'.")
        limit_to_start_path = scope == "path"

    graph = raw.get("graph") or {}
    graph_colors = dict(DEFAULT_GRAPH_COLORS)
    graph_colors.update(graph.get("colors") or {})
    graph_colors["rules"] = list(graph_colors.get("rules") or [])
    graph_traffic = deep_merge(DEFAULT_GRAPH_TRAFFIC, graph.get("traffic") or {})

    return MapperConfig(
        name=name,
        start_url=start_url,
        max_pages=int(raw.get("max_pages", 50)),
        delay_seconds=float(raw.get("delay_seconds", 0.5)),
        allow_subdomains=bool(raw.get("allow_subdomains", False)),
        limit_to_start_path=bool(limit_to_start_path),
        allow_patterns=list(allow.get("patterns", [])),
        exclude_patterns=list(exclude.get("patterns", [])),
        strip_tags=list(exclude.get("strip_tags", DEFAULT_STRIP_TAGS)),
        strip_selectors=list(exclude.get("strip_selectors", [])),
        strip_class_or_id_keywords=list(
            exclude.get("strip_class_or_id_keywords", DEFAULT_STRIP_KEYWORDS)
        ),
        graph_colors=graph_colors,
        graph_traffic=graph_traffic,
        graph_exclude_patterns=list((graph.get("exclude") or {}).get("patterns", [])),
        traffic=load_traffic_config(raw, config_file),
    )


def normalize_url(url: str) -> str:
    """Normalize URLs by removing anchors/fragments and trailing slashes."""
    url = url.split("#")[0]
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
    if parsed.query:
        normalized += f"?{parsed.query}"

    return normalized


def normalize_traffic_url(url: str, traffic_config: TrafficConfig) -> str:
    """Normalize traffic URLs so GA4 rows can match crawl URLs."""
    url = url.strip()
    if not url:
        return ""

    if traffic_config.strip_fragment:
        url = url.split("#")[0]

    parsed = urlparse(url)
    query = parsed.query

    if traffic_config.strip_all_query:
        query = ""
    elif traffic_config.strip_tracking_params and query:
        tracking_params = {param.lower() for param in traffic_config.tracking_params or []}
        tracking_prefixes = [
            prefix.lower() for prefix in traffic_config.tracking_param_prefixes or []
        ]
        query_pairs = []
        for key, value in parse_qsl(query, keep_blank_values=True):
            key_lower = key.lower()
            is_tracking = key_lower in tracking_params or any(
                key_lower.startswith(prefix) for prefix in tracking_prefixes
            )
            if not is_tracking:
                query_pairs.append((key, value))
        query = urlencode(query_pairs, doseq=True)

    path = parsed.path
    if traffic_config.strip_trailing_slash:
        path = path.rstrip("/")

    normalized = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            parsed.params,
            query,
            "",
        )
    )
    return normalize_url(normalized)


def link_join_base(url: str) -> str:
    """Return a URL base that resolves extensionless paths like directories."""
    parsed = urlparse(url)
    path = parsed.path

    if path and not path.endswith("/") and "." not in Path(path).name:
        path = f"{path}/"

    return urlunparse(
        (parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, "")
    )


def resolve_link(page_url: str, href: str) -> str:
    return normalize_url(urljoin(link_join_base(page_url), href))


def is_excluded(url: str, exclude_patterns: list[str]) -> bool:
    url_lower = url.lower()
    return any(pattern.lower() in url_lower for pattern in exclude_patterns)


def is_allowed_by_patterns(url: str, start_url: str, allow_patterns: list[str]) -> bool:
    if normalize_url(url) == normalize_url(start_url):
        return True
    if not allow_patterns:
        return True

    url_lower = url.lower()
    return any(pattern.lower() in url_lower for pattern in allow_patterns)


def is_allowed_domain(url: str, base_domain: str, allow_subdomains: bool) -> bool:
    netloc = urlparse(url).netloc.lower()
    base = base_domain.lower()
    if netloc == base:
        return True
    return allow_subdomains and netloc.endswith(f".{base}")


def is_allowed_scope(url: str, start_url: str, config: MapperConfig) -> bool:
    if not config.limit_to_start_path:
        return True

    start_path = urlparse(normalize_url(start_url)).path.rstrip("/")
    if not start_path:
        return True

    path = urlparse(normalize_url(url)).path.rstrip("/")
    return path == start_path or path.startswith(f"{start_path}/")


def strip_configured_elements(soup: BeautifulSoup, config: MapperConfig) -> None:
    for tag_name in config.strip_tags:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for selector in config.strip_selectors:
        for element in soup.select(selector):
            element.decompose()

    keywords = [keyword.lower() for keyword in config.strip_class_or_id_keywords]
    if not keywords:
        return

    def matches_keywords(tag):
        classes_attr = tag.get("class", [])
        if isinstance(classes_attr, str):
            classes = classes_attr.lower()
        else:
            classes = " ".join(classes_attr).lower()
        element_id = str(tag.get("id", "")).lower()
        return any(keyword in classes or keyword in element_id for keyword in keywords)

    for element in soup.find_all(matches_keywords):
        element.decompose()


def parse_date_range(value: str) -> str | None:
    match = re.search(r"(\d{8})-(\d{8})", value)
    return match.group(0) if match else None


def find_ga4_header(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        row = next(csv.reader([line]))
        if row[:4] == ["Page location", "Page referrer", "Views", "Sessions"]:
            return index
    return None


def parse_views(value: str) -> int:
    cleaned = str(value or "").replace(",", "").strip()
    if not cleaned:
        return 0
    return int(float(cleaned))


def adjust_sampled_views(raw_views: int, traffic_config: TrafficConfig) -> int:
    if traffic_config.sample_divisor == 0:
        raise ValueError("traffic.sample.divisor cannot be 0.")

    adjusted = raw_views / traffic_config.sample_divisor
    if traffic_config.rounding == "floor":
        return math.floor(adjusted)
    if traffic_config.rounding == "ceil":
        return math.ceil(adjusted)
    if traffic_config.rounding != "nearest":
        raise ValueError("traffic.sample.rounding must be nearest, floor, or ceil.")
    return math.floor(adjusted + 0.5)


def is_internal_referrer(referrer: str, internal_domains: list[str]) -> bool:
    parsed = urlparse(referrer)
    netloc = parsed.netloc.lower()
    if not netloc:
        return False

    for domain in internal_domains:
        normalized_domain = domain.lower().lstrip(".")
        if netloc == normalized_domain or netloc.endswith(f".{normalized_domain}"):
            return True
    return False


def classify_referrer(referrer: str, traffic_config: TrafficConfig) -> str:
    if not referrer.strip():
        return "direct"
    if is_internal_referrer(referrer, traffic_config.internal_domains or []):
        return "internal"
    return "external"


def empty_traffic_dataset(warnings: list[str] | None = None) -> TrafficDataset:
    return TrafficDataset(
        records=[],
        edge_views={},
        node_total_views={},
        node_internal_views={},
        node_external_views={},
        node_direct_views={},
        warnings=warnings or [],
        file_ranges={},
    )


def load_traffic_dataset(config: MapperConfig) -> TrafficDataset:
    traffic_config = config.traffic or TrafficConfig()
    if not traffic_config.enabled:
        return empty_traffic_dataset()
    if not traffic_config.resolved_dir:
        return empty_traffic_dataset(["Traffic is enabled but traffic.dir is not set."])

    traffic_dir = Path(traffic_config.resolved_dir)
    if not traffic_dir.exists():
        return empty_traffic_dataset([f"Traffic directory does not exist: {traffic_dir}"])

    csv_files = sorted(traffic_dir.glob("*.csv"))
    if not csv_files:
        return empty_traffic_dataset([f"No traffic CSV files found in {traffic_dir}"])

    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    file_ranges: dict[str, str | None] = {}
    edge_views: dict[tuple[str, str], int] = defaultdict(int)
    node_total_views: dict[str, int] = defaultdict(int)
    node_internal_views: dict[str, int] = defaultdict(int)
    node_external_views: dict[str, int] = defaultdict(int)
    node_direct_views: dict[str, int] = defaultdict(int)

    for csv_file in csv_files:
        lines = csv_file.read_text(encoding="utf-8-sig").splitlines()
        line_four_range = parse_date_range(lines[3]) if len(lines) >= 4 else None
        filename_range = parse_date_range(csv_file.name)
        file_ranges[csv_file.name] = line_four_range

        if not line_four_range:
            warnings.append(
                f"Traffic warning: {csv_file.name} line 4 does not contain a YYYYMMDD-YYYYMMDD date range."
            )
        if filename_range and line_four_range and filename_range != line_four_range:
            warnings.append(
                f"Traffic warning: {csv_file.name} filename range {filename_range} differs from header range {line_four_range}."
            )

        header_index = find_ga4_header(lines)
        if header_index is None:
            warnings.append(
                f"Traffic warning: {csv_file.name} does not contain a Page location/Page referrer/Views/Sessions header."
            )
            continue

        reader = csv.DictReader(lines[header_index:])
        for row in reader:
            raw_target = (row.get("Page location") or "").strip()
            if not raw_target:
                continue

            raw_referrer = (row.get("Page referrer") or "").strip()
            raw_views = parse_views(row.get(traffic_config.views_column, "0"))
            adjusted_views = adjust_sampled_views(raw_views, traffic_config)
            source_type = classify_referrer(raw_referrer, traffic_config)
            target = normalize_traffic_url(raw_target, traffic_config)
            source = (
                normalize_traffic_url(raw_referrer, traffic_config)
                if source_type == "internal"
                else raw_referrer
            )

            record = {
                "file": csv_file.name,
                "source": source,
                "target": target,
                "source_type": source_type,
                "raw_views": raw_views,
                "adjusted_views": adjusted_views,
            }
            records.append(record)
            node_total_views[target] += adjusted_views

            if source_type == "internal":
                edge_views[(source, target)] += adjusted_views
                node_internal_views[target] += adjusted_views
            elif source_type == "external":
                node_external_views[target] += adjusted_views
            else:
                node_direct_views[target] += adjusted_views

    unique_ranges = {date_range for date_range in file_ranges.values() if date_range}
    if len(unique_ranges) > 1:
        warnings.append(
            "Traffic warning: traffic CSVs contain multiple header date ranges: "
            + ", ".join(sorted(unique_ranges))
            + "."
        )

    return TrafficDataset(
        records=records,
        edge_views=dict(edge_views),
        node_total_views=dict(node_total_views),
        node_internal_views=dict(node_internal_views),
        node_external_views=dict(node_external_views),
        node_direct_views=dict(node_direct_views),
        warnings=warnings,
        file_ranges=file_ranges,
    )


def project_output_path(project_dir: Path, configured_path: str) -> Path:
    output_path = Path(configured_path)
    if output_path.is_absolute():
        return output_path
    return project_dir / output_path


def write_traffic_outputs(
    traffic_data: TrafficDataset,
    project_dir: Path,
    config: MapperConfig,
    edges: list[tuple[str, str]],
) -> None:
    traffic_config = config.traffic or TrafficConfig()
    processed_file = project_output_path(project_dir, traffic_config.processed_output)
    summary_file = project_output_path(project_dir, traffic_config.summary_output)
    graph_edge_set = {(normalize_url(source), normalize_url(target)) for source, target in edges}

    processed_file.parent.mkdir(parents=True, exist_ok=True)
    with processed_file.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "File",
            "Source",
            "Target",
            "Source Type",
            "Raw Views",
            "Adjusted Views",
            "Matched Graph Edge",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in traffic_data.records:
            source = str(record["source"])
            target = str(record["target"])
            matched_graph_edge = (
                record["source_type"] == "internal" and (source, target) in graph_edge_set
            )
            writer.writerow(
                {
                    "File": record["file"],
                    "Source": source,
                    "Target": target,
                    "Source Type": record["source_type"],
                    "Raw Views": record["raw_views"],
                    "Adjusted Views": record["adjusted_views"],
                    "Matched Graph Edge": "yes" if matched_graph_edge else "no",
                }
            )

    totals_by_source_type: dict[str, int] = defaultdict(int)
    raw_totals_by_source_type: dict[str, int] = defaultdict(int)
    for record in traffic_data.records:
        source_type = str(record["source_type"])
        totals_by_source_type[source_type] += int(record["adjusted_views"])
        raw_totals_by_source_type[source_type] += int(record["raw_views"])

    unmatched_internal_edges = sorted(
        [
            {
                "source": source,
                "target": target,
                "adjusted_views": views,
            }
            for (source, target), views in traffic_data.edge_views.items()
            if (source, target) not in graph_edge_set
        ],
        key=lambda row: (-row["adjusted_views"], row["source"], row["target"]),
    )
    door_nodes = []
    for node, total_views in traffic_data.node_total_views.items():
        stats = get_node_traffic_stats(node, traffic_data)
        external_ratio = get_external_ratio(stats, traffic_config)
        if node_is_door(stats, traffic_config):
            door_nodes.append(
                {
                    "url": node,
                    "total_views": total_views,
                    "external_views": stats["external"],
                    "external_ratio": round(external_ratio, 4),
                }
            )
    door_nodes.sort(key=lambda row: (-row["external_ratio"], -row["external_views"], row["url"]))

    summary = {
        "traffic_dir": traffic_config.dir,
        "files": traffic_data.file_ranges,
        "warnings": traffic_data.warnings,
        "records": len(traffic_data.records),
        "raw_views_by_source_type": dict(sorted(raw_totals_by_source_type.items())),
        "adjusted_views_by_source_type": dict(sorted(totals_by_source_type.items())),
        "matched_internal_edge_count": sum(
            1 for edge in traffic_data.edge_views if edge in graph_edge_set
        ),
        "unmatched_internal_edge_count": len(unmatched_internal_edges),
        "unmatched_internal_edges": unmatched_internal_edges,
        "door_nodes": door_nodes,
    }
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Saved processed traffic data: {processed_file}")
    print(f"Saved traffic summary: {summary_file}")


def prepare_traffic_data(
    config: MapperConfig,
    project_dir: Path,
    edges: list[tuple[str, str]],
) -> TrafficDataset | None:
    traffic_config = config.traffic or TrafficConfig()
    if not traffic_config.enabled:
        return None

    traffic_data = load_traffic_dataset(config)
    for warning in traffic_data.warnings:
        print(warning)
    write_traffic_outputs(traffic_data, project_dir, config, edges)
    print(
        "Traffic rows processed: "
        f"{len(traffic_data.records)} from {len(traffic_data.file_ranges)} file(s)"
    )
    return traffic_data


def get_internal_links(
    url: str,
    base_domain: str,
    start_url: str,
    config: MapperConfig,
) -> tuple[set[str], bool]:
    """Fetch internal links from page content, omitting excluded and duplicate URLs."""
    internal_links = set()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; DomainMapper/1.0)"}

    try:
        response = requests.get(url, headers=headers, timeout=5)
        if "text/html" not in response.headers.get("Content-Type", ""):
            return internal_links, True

        page_url = response.url or url
        soup = BeautifulSoup(response.text, "html.parser")
        strip_configured_elements(soup, config)

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue

            full_url = resolve_link(page_url, href)
            if (
                is_allowed_domain(full_url, base_domain, config.allow_subdomains)
                and is_allowed_scope(full_url, start_url, config)
                and is_allowed_by_patterns(full_url, start_url, config.allow_patterns)
                and full_url != url
                and not is_excluded(full_url, config.exclude_patterns)
            ):
                internal_links.add(full_url)

    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return internal_links, False

    return internal_links, True


def crawl_and_map(config: MapperConfig) -> list[tuple[str, str]]:
    """Crawl a site while normalizing URLs to prevent trailing-slash duplicates."""
    start_url = normalize_url(config.start_url)
    base_domain = urlparse(start_url).netloc

    visited = set()
    queue = [start_url]
    edges = set()

    print(f"Starting crawl of {base_domain} (max pages: {config.max_pages})...")

    while queue and len(visited) < config.max_pages:
        current_url = queue.pop(0)

        if (
            current_url in visited
            or is_excluded(current_url, config.exclude_patterns)
            or not is_allowed_by_patterns(current_url, start_url, config.allow_patterns)
        ):
            continue

        print(f"Scraping: {current_url}")
        visited.add(current_url)

        links, fetched = get_internal_links(current_url, base_domain, start_url, config)
        if current_url == start_url and not fetched:
            raise RuntimeError(f"Could not fetch start URL: {start_url}")

        for link in links:
            edges.add((current_url, link))
            if link not in visited and link not in queue:
                queue.append(link)

        time.sleep(config.delay_seconds)

    return sorted(edges)


def export_to_csv(edges: list[tuple[str, str]], filename: Path | str = "website_edges.csv") -> None:
    with Path(filename).open(mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "Target"])
        writer.writerows(edges)
    print(f"Saved {len(edges)} unique connections to {filename}")


def get_node_color(node: str, start_url: str, graph_colors: dict[str, Any]) -> str:
    node = normalize_url(node)
    start_url = normalize_url(start_url)

    if node == start_url:
        return str(graph_colors.get("start") or DEFAULT_GRAPH_COLORS["start"])

    for rule in graph_colors.get("rules") or []:
        color = rule.get("color")
        if not color:
            continue

        exact_urls = [normalize_url(url) for url in rule.get("urls") or []]
        if node in exact_urls:
            return str(color)

        node_lower = node.lower()
        patterns = [str(pattern).lower() for pattern in rule.get("patterns") or []]
        if any(pattern in node_lower for pattern in patterns):
            return str(color)

    return str(graph_colors.get("default") or DEFAULT_GRAPH_COLORS["default"])


def parse_hex_color(color: str) -> tuple[int, int, int]:
    color = color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(part * 2 for part in color)
    if len(color) != 6:
        raise ValueError(f"Expected a hex color like #140B34, got {color!r}.")
    return tuple(int(color[index : index + 2], 16) for index in (0, 2, 4))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def interpolate_color(low_color: str, high_color: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    low = parse_hex_color(low_color)
    high = parse_hex_color(high_color)
    rgb = tuple(round(low[index] + ((high[index] - low[index]) * ratio)) for index in range(3))
    return rgb_to_hex(rgb)


def get_heat_ratio(value: int, max_value: int, heat_config: dict[str, Any]) -> float:
    if max_value <= 0:
        return 0.0

    scale = str(heat_config.get("scale") or "linear").lower()
    if scale == "linear":
        return value / max_value
    if scale == "log":
        return math.log1p(value) / math.log1p(max_value)
    if scale == "sqrt":
        return math.sqrt(value) / math.sqrt(max_value)

    raise ValueError("graph.traffic heat scale must be linear, log, or sqrt.")


def get_heat_color(value: int, max_value: int, heat_config: dict[str, Any]) -> str:
    color_stops = heat_config.get("colors")
    if not color_stops:
        color_stops = [
            color
            for color in [
                heat_config.get("low") or "#140B34",
                heat_config.get("mid"),
                heat_config.get("high") or "#F6D746",
            ]
            if color
        ]
    color_stops = [str(color) for color in color_stops]
    if len(color_stops) < 2:
        raise ValueError("graph.traffic heat colors must include at least two colors.")

    ratio = get_heat_ratio(value, max_value, heat_config)

    if ratio <= 0:
        return color_stops[0]
    if ratio >= 1:
        return color_stops[-1]

    segment_count = len(color_stops) - 1
    segment_position = ratio * segment_count
    segment_index = min(math.floor(segment_position), segment_count - 1)
    segment_ratio = segment_position - segment_index
    return interpolate_color(
        color_stops[segment_index],
        color_stops[segment_index + 1],
        segment_ratio,
    )


def get_node_traffic_stats(node: str, traffic_data: TrafficDataset | None) -> dict[str, int]:
    if not traffic_data:
        return {"total": 0, "internal": 0, "external": 0, "direct": 0}
    return {
        "total": traffic_data.node_total_views.get(node, 0),
        "internal": traffic_data.node_internal_views.get(node, 0),
        "external": traffic_data.node_external_views.get(node, 0),
        "direct": traffic_data.node_direct_views.get(node, 0),
    }


def get_external_ratio(stats: dict[str, int], traffic_config: TrafficConfig | None) -> float:
    if not traffic_config:
        return 0.0
    if traffic_config.door_include_direct_in_denominator:
        denominator = stats["total"]
    else:
        denominator = stats["internal"] + stats["external"]
    if denominator <= 0:
        return 0.0
    return stats["external"] / denominator


def node_is_door(stats: dict[str, int], traffic_config: TrafficConfig | None) -> bool:
    if not traffic_config or not traffic_config.doors_enabled:
        return False
    return get_external_ratio(stats, traffic_config) >= traffic_config.door_external_ratio_threshold


def get_traffic_edge_views(
    source: str,
    target: str,
    traffic_data: TrafficDataset | None,
) -> int:
    if not traffic_data:
        return 0
    return traffic_data.edge_views.get((source, target), 0)


def filter_graph_edges(
    edges: list[tuple[str, str]],
    start_url: str,
    graph_exclude_patterns: list[str],
) -> list[tuple[str, str]]:
    if not graph_exclude_patterns:
        return edges

    start_url = normalize_url(start_url)
    filtered_edges = []

    for source, target in edges:
        source = normalize_url(source)
        target = normalize_url(target)

        source_excluded = source != start_url and is_excluded(source, graph_exclude_patterns)
        target_excluded = target != start_url and is_excluded(target, graph_exclude_patterns)

        if not source_excluded and not target_excluded:
            filtered_edges.append((source, target))

    return filtered_edges


def build_visual_graph(
    edges: list[tuple[str, str]],
    config: MapperConfig | str,
    output_file: Path | str = "site_map.html",
    traffic_data: TrafficDataset | None = None,
) -> None:
    if isinstance(config, MapperConfig):
        start_url = normalize_url(config.start_url)
        graph_colors = config.graph_colors or DEFAULT_GRAPH_COLORS
        graph_traffic = config.graph_traffic or DEFAULT_GRAPH_TRAFFIC
        graph_exclude_patterns = config.graph_exclude_patterns
        traffic_config = config.traffic
    else:
        start_url = normalize_url(config)
        graph_colors = DEFAULT_GRAPH_COLORS
        graph_traffic = DEFAULT_GRAPH_TRAFFIC
        graph_exclude_patterns = []
        traffic_config = None

    graph = nx.DiGraph()
    graph.add_node(start_url)
    edges = filter_graph_edges(edges, start_url, graph_exclude_patterns)
    graph.add_edges_from(edges)
    traffic_enabled = bool(
        traffic_data
        and traffic_config
        and traffic_config.enabled
        and graph_traffic.get("enabled", True)
    )
    node_heat = graph_traffic.get("node_heat") or {}
    edge_heat = graph_traffic.get("edge_heat") or {}
    door_style = graph_traffic.get("doors") or {}
    node_heat_enabled = traffic_enabled and bool(node_heat.get("enabled", True))
    edge_heat_enabled = traffic_enabled and bool(edge_heat.get("enabled", True))
    door_borders_enabled = traffic_enabled and bool(door_style.get("enabled", True))
    max_node_views = max(
        (traffic_data.node_total_views.get(node, 0) for node in graph.nodes()),
        default=0,
    ) if traffic_data else 0
    max_edge_views = max(
        (
            get_traffic_edge_views(source, target, traffic_data)
            for source, target in graph.edges()
        ),
        default=0,
    ) if traffic_data else 0

    for node in graph.nodes():
        degree = graph.degree(node)
        size = 10 + (degree * 2)
        stats = get_node_traffic_stats(node, traffic_data)
        external_ratio = get_external_ratio(stats, traffic_config)

        if node_heat_enabled:
            background_color = get_heat_color(stats["total"], max_node_views, node_heat)
        else:
            background_color = get_node_color(node, start_url, graph_colors)

        is_door = door_borders_enabled and node_is_door(stats, traffic_config)
        if is_door:
            border_color = str(door_style.get("border_color") or "#22C55E")
            border_width = int(door_style.get("border_width") or 4)
            color: str | dict[str, Any] = {
                "background": background_color,
                "border": border_color,
                "highlight": {
                    "background": background_color,
                    "border": border_color,
                },
            }
            graph.nodes[node]["borderWidth"] = border_width
        else:
            color = background_color

        graph.nodes[node]["size"] = size
        graph.nodes[node]["color"] = color
        graph.nodes[node]["title"] = (
            f"{escape(node)}<br>"
            f"Connections: {degree}<br>"
            f"Total views: {stats['total']}<br>"
            f"Internal views: {stats['internal']}<br>"
            f"External views: {stats['external']}<br>"
            f"Direct/no-referrer views: {stats['direct']}<br>"
            f"External ratio: {external_ratio:.1%}"
        )

    for source, target in graph.edges():
        edge_views = get_traffic_edge_views(source, target, traffic_data)
        if edge_heat_enabled:
            graph.edges[source, target]["color"] = get_heat_color(
                edge_views,
                max_edge_views,
                edge_heat,
            )
        graph.edges[source, target]["title"] = f"Views: {edge_views}"

    net = Network(height="800px", width="100%", bgcolor="#ffffff", font_color="black", directed=True)
    net.from_nx(graph)
    net.set_options(PHYSICS_OPTIONS)
    net.save_graph(str(output_file))
    print(f"Generated interactive map: {output_file}")


def read_edges_csv(csv_file: Path | str) -> tuple[list[dict[str, str]], list[str]]:
    edges = []
    nodes = set()

    with Path(csv_file).open(mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            edges.append({"source": row["Source"], "target": row["Target"]})
            nodes.add(row["Source"])
            nodes.add(row["Target"])

    return edges, sorted(nodes)


def generate_interactive_hop_finder(
    csv_file: Path | str = "website_edges.csv",
    output_html: Path | str = "hop_finder.html",
    title: str = "Interactive Hop & Path Finder",
) -> None:
    edges, sorted_nodes = read_edges_csv(csv_file)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{escape(title)}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 900px; margin: 30px auto; padding: 0 20px; color: #333; line-height: 1.5; }}
        .card {{ background: #ffffff; border: 1px solid #e0e0e0; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        label {{ font-weight: bold; display: block; margin-top: 10px; }}
        select, button {{ width: 100%; padding: 10px; margin-top: 5px; border-radius: 4px; border: 1px solid #ccc; font-size: 14px; box-sizing: border-box; }}
        button {{ background: #0066cc; color: white; font-weight: bold; cursor: pointer; border: none; transition: background 0.2s; }}
        button:hover {{ background: #0052a3; }}
        .blocked-container {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
        .pill {{ background: #ffebe9; border: 1px solid #ffc1c0; color: #cf222e; padding: 4px 10px; border-radius: 16px; font-size: 13px; display: inline-flex; align-items: center; gap: 6px; word-break: break-all; }}
        .pill-remove {{ cursor: pointer; font-weight: bold; background: #cf222e; color: white; border-radius: 50%; width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; border: none; padding: 0; }}
        .clear-btn {{ background: #6e7781; width: auto; padding: 6px 12px; font-size: 12px; margin-top: 10px; }}
        .result {{ padding: 15px 20px; background: #f0f7ff; border-left: 5px solid #0066cc; border-radius: 4px; }}
        .path-list {{ list-style-type: none; padding: 0; margin-top: 15px; }}
        .path-step {{ display: flex; align-items: center; justify-content: space-between; padding: 10px; background: #ffffff; border: 1px solid #e1e4e8; border-radius: 6px; margin-bottom: 8px; word-break: break-all; gap: 12px; }}
        .exclude-btn {{ width: auto; padding: 4px 10px; font-size: 12px; background: #cf222e; margin: 0; flex-shrink: 0; }}
        .exclude-btn:hover {{ background: #a40e26; }}
        .step-num {{ font-weight: bold; margin-right: 10px; color: #57606a; flex-shrink: 0; }}
        .no-path {{ background: #fff0f0; border-left-color: #cf222e; }}
    </style>
</head>
<body>

    <h2>{escape(title)}</h2>

    <div class="card">
        <label for="startNode">Starting Page (Source):</label>
        <select id="startNode" onchange="calculateHops()"></select>

        <label for="targetNode">Target Page (Destination):</label>
        <select id="targetNode" onchange="calculateHops()"></select>
    </div>

    <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3 style="margin: 0;">Excluded Pages (<span id="blockedCount">0</span>)</h3>
            <button class="clear-btn" id="clearBtn" onclick="clearBlocked()" style="display:none;">Clear All Exclusions</button>
        </div>
        <p style="font-size: 13px; color: #666; margin: 5px 0 0 0;">Pages listed here are bypassed when finding paths.</p>
        <div id="blockedBadges" class="blocked-container">
            <em style="color: #888; font-size: 13px; margin-top: 5px;">No pages excluded yet. Click "Exclude" on any path result below to test alternative routes.</em>
        </div>
    </div>

    <div id="output"></div>

    <script>
        const nodes = {json.dumps(sorted_nodes)};
        const edges = {json.dumps(edges)};
        let blockedNodes = new Set();

        function escapeHtml(str) {{
            return str
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }}

        const startSelect = document.getElementById('startNode');
        const targetSelect = document.getElementById('targetNode');

        nodes.forEach(node => {{
            startSelect.add(new Option(node, node));
            targetSelect.add(new Option(node, node));
        }});

        const graph = {{}};
        edges.forEach(edge => {{
            if (!graph[edge.source]) graph[edge.source] = [];
            graph[edge.source].push(edge.target);
        }});

        function blockNode(encodedUrl) {{
            const url = decodeURIComponent(encodedUrl);
            blockedNodes.add(url);
            updateBlockedUI();
            calculateHops();
        }}

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
                badgesDiv.innerHTML = '<em style="color: #888; font-size: 13px; margin-top: 5px;">No pages excluded yet. Click "Exclude" on any path result below to test alternative routes.</em>';
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
                        <button class="pill-remove" onclick="unblockNode('${{encoded}}')" title="Remove exclusion">x</button>
                    </div>
                `;
            }});
            badgesDiv.innerHTML = html;
        }}

        function calculateHops() {{
            const start = startSelect.value;
            const target = targetSelect.value;
            const output = document.getElementById('output');

            if (!start || !target) {{
                output.innerHTML = '<div class="result no-path">No crawl edges are available for this project yet.</div>';
                return;
            }}

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
                    const isEndNode = index === 0 || index === shortestPath.length - 1;
                    const encoded = encodeURIComponent(url);
                    const safeUrl = escapeHtml(url);

                    stepsHtml += `
                        <li class="path-step">
                            <div>
                                <span class="step-num">[${{index}}]</span>
                                <a href="${{safeUrl}}" target="_blank" style="color:#0066cc;">${{safeUrl}}</a>
                            </div>
                            ${{!isEndNode ? `<button class="exclude-btn" onclick="blockNode('${{encoded}}')">Exclude</button>` : '<span style="font-size:11px; color:#888;">Terminal</span>'}}
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

        calculateHops();
    </script>
</body>
</html>"""

    Path(output_html).write_text(html_content, encoding="utf-8")
    print(f"Generated hop finder: {output_html}")


def generate_dashboard(
    output_file: Path | str = "dashboard.html",
    map_file: str = "site_map.html",
    hop_file: str = "hop_finder.html",
    title: str = "Domain Mapper Dashboard",
) -> None:
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body, html {{ height: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; overflow: hidden; background: #f4f6f8; }}
        .nav-bar {{ display: flex; background: #1e293b; color: white; padding: 10px 20px; align-items: center; gap: 10px; border-bottom: 1px solid #334155; height: 50px; }}
        .title {{ font-weight: bold; font-size: 15px; margin-right: 20px; color: #f8fafc; letter-spacing: 0.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .tab-btn {{ background: transparent; border: none; color: #94a3b8; font-size: 14px; font-weight: 600; padding: 6px 14px; border-radius: 6px; cursor: pointer; transition: all 0.2s; }}
        .tab-btn:hover {{ color: white; background: #334155; }}
        .tab-btn.active {{ color: white; background: #2563eb; }}
        .content-area {{ height: calc(100vh - 50px); width: 100%; position: relative; }}
        iframe {{ width: 100%; height: 100%; border: none; display: none; }}
        iframe.active {{ display: block; }}
    </style>
</head>
<body>
    <div class="nav-bar">
        <span class="title">{escape(title)}</span>
        <button class="tab-btn active" onclick="switchTab('map', this)">Network Visualizer</button>
        <button class="tab-btn" onclick="switchTab('hop', this)">Hop & Path Finder</button>
    </div>

    <div class="content-area">
        <iframe id="mapFrame" src="{escape(map_file)}" class="active"></iframe>
        <iframe id="hopFrame" src="{escape(hop_file)}"></iframe>
    </div>

    <script>
        function switchTab(tabName, btn) {{
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('iframe').forEach(f => f.classList.remove('active'));

            btn.classList.add('active');
            if (tabName === 'map') {{
                document.getElementById('mapFrame').classList.add('active');
            }} else {{
                document.getElementById('hopFrame').classList.add('active');
            }}
        }}
    </script>
</body>
</html>"""

    Path(output_file).write_text(html_content, encoding="utf-8")
    print(f"Generated dashboard: {output_file}")


def discover_projects(output_root: Path) -> list[dict[str, str]]:
    projects = []
    for config_file in sorted(output_root.glob("*/config.yaml")):
        with config_file.open(encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        project_dir = config_file.parent
        dashboard = project_dir / "dashboard.html"
        if not dashboard.exists():
            continue
        projects.append(
            {
                "name": str(config.get("name") or project_dir.name),
                "start_url": str(config.get("start_url") or ""),
                "href": dashboard.as_posix(),
                "slug": project_dir.name,
            }
        )
    return projects


def generate_project_index(
    output_file: Path | str = "index.html",
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
) -> None:
    root = Path(output_root)
    projects = discover_projects(root)

    if projects:
        cards = "\n".join(
            f"""        <a class="project-card" href="{escape(project['href'])}">
            <span class="project-name">{escape(project['name'])}</span>
            <span class="project-url">{escape(project['start_url'])}</span>
        </a>"""
            for project in projects
        )
    else:
        cards = """        <div class="empty">
            No project dashboards have been generated yet.
        </div>"""

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Domain Mapper Projects</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #172033; background: #f5f7fb; }}
        header {{ background: #1e293b; color: white; padding: 24px clamp(18px, 4vw, 48px); }}
        h1 {{ margin: 0; font-size: clamp(24px, 4vw, 38px); letter-spacing: 0; }}
        main {{ max-width: 980px; margin: 0 auto; padding: 32px clamp(18px, 4vw, 32px); }}
        .project-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }}
        .project-card {{ display: flex; flex-direction: column; gap: 10px; min-height: 128px; padding: 18px; border: 1px solid #d9e0ea; border-radius: 8px; background: white; color: inherit; text-decoration: none; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06); }}
        .project-card:hover {{ border-color: #2563eb; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1); }}
        .project-name {{ font-size: 18px; font-weight: 700; }}
        .project-url {{ color: #536174; font-size: 13px; overflow-wrap: anywhere; }}
        .empty {{ padding: 18px; border: 1px solid #d9e0ea; border-radius: 8px; background: white; color: #536174; }}
    </style>
</head>
<body>
    <header>
        <h1>Domain Mapper Projects</h1>
    </header>
    <main>
        <div class="project-grid">
{cards}
        </div>
    </main>
</body>
</html>"""

    Path(output_file).write_text(html_content, encoding="utf-8")
    print(f"Generated project index: {output_file}")


def write_effective_config(config: MapperConfig, output_file: Path) -> None:
    with output_file.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config.to_yaml_data(), f, sort_keys=False)


def generate_project(config: MapperConfig, output_root: Path) -> Path:
    slug = slugify(config.name)
    project_dir = output_root / slug

    edges_file = project_dir / "website_edges.csv"
    map_file = project_dir / "site_map.html"
    hop_file = project_dir / "hop_finder.html"
    dashboard_file = project_dir / "dashboard.html"

    edges = crawl_and_map(config)

    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    export_to_csv(edges, edges_file)
    traffic_data = prepare_traffic_data(config, project_dir, edges)
    build_visual_graph(edges, config, map_file, traffic_data)
    generate_interactive_hop_finder(edges_file, hop_file, f"{config.name} Hop & Path Finder")
    generate_dashboard(dashboard_file, "site_map.html", "hop_finder.html", config.name)
    write_effective_config(config, project_dir / "config.yaml")

    return project_dir


def csv_edges_to_tuples(csv_file: Path) -> list[tuple[str, str]]:
    edges, _ = read_edges_csv(csv_file)
    return sorted((edge["source"], edge["target"]) for edge in edges)


def refresh_project(config: MapperConfig, output_root: Path) -> Path:
    slug = slugify(config.name)
    project_dir = output_root / slug
    edges_file = project_dir / "website_edges.csv"

    if not edges_file.exists():
        raise FileNotFoundError(
            f"Cannot refresh without an existing crawl CSV: {edges_file}"
        )

    map_file = project_dir / "site_map.html"
    hop_file = project_dir / "hop_finder.html"
    dashboard_file = project_dir / "dashboard.html"

    edges = csv_edges_to_tuples(edges_file)
    traffic_data = prepare_traffic_data(config, project_dir, edges)
    build_visual_graph(edges, config, map_file, traffic_data)
    generate_interactive_hop_finder(edges_file, hop_file, f"{config.name} Hop & Path Finder")
    generate_dashboard(dashboard_file, "site_map.html", "hop_finder.html", config.name)
    write_effective_config(config, project_dir / "config.yaml")

    return project_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate static domain mapping dashboards.")
    parser.add_argument("config", nargs="?", help="YAML config file for this project.")
    parser.add_argument("--project", help="Project display name and folder slug source.")
    parser.add_argument(
        "--output-root",
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Folder that stores generated project dashboards. Default: {DEFAULT_OUTPUT_ROOT}",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Only regenerate the root index.html by scanning project folders.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Rebuild generated HTML from the existing project CSV without scraping.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_root = Path(args.output_root)

    if args.index_only:
        generate_project_index("index.html", output_root)
        return

    if not args.config:
        raise SystemExit("Provide a YAML config file, or use --index-only.")

    config = load_config(Path(args.config), args.project)
    if args.refresh:
        project_dir = refresh_project(config, output_root)
    else:
        project_dir = generate_project(config, output_root)
    generate_project_index("index.html", output_root)
    print(f"Project dashboard ready: {project_dir / 'dashboard.html'}")


if __name__ == "__main__":
    main()
