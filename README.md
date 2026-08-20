# Domain Mapper

Just a little vibe coded project to quickly map and explore user routes through a website.

## Crawling

The crawling is a bit opinionated. `mapper.py` produces a network interface in `site_map.html`

* Stays within the parent domain of `START_URL`
* Allows exclusion of explicit index style pages that can distort the picture
* Allows exclusion of html tags and classes 

## Speeding up route analysis

`hop_finder_gen.py` generates a simple interface to look for shortest routes between two pages. You can exclude pages interactively to find where the architecture is brittle.

## Directions

I'd create a python virtual environment. The general gist is..

```sh
git clone <this-repository>
cd path/to/the-repository
python3 -m vevn .
pip install requirements.txt
```

To run your own you need to change `START_URL` in `mapper.py` and delete or set `EXCLUDE_PATTERNS`. Then if you want to include navigation you should edit lines 68-71.

```sh
# crawl site and create site_map.html and edges csv
python mapper.py
# create hop finder from the saved edges
python hop_finder_gen.py
# optionally create a single dashboard for both interfaces
python generate_dashboard.py
```