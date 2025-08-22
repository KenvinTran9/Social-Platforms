# Idea Collector

This project collects trending topics and pain points from various online sources (Reddit, YouTube, etc.) for small business, freelancing, and productivity research.

## Features

- Collects posts and videos using keywords and topics from Reddit and YouTube.
- Configurable sources and search terms via `tool/config.yml`.
- Outputs structured JSON data with metadata and source breakdown.

## Usage

1. Configure API keys and search settings in `tool/config.yml` and `.env`.
2. Run data collection:
	```bash
	python tool/collect.py
	```
3. Collected data is saved in `tool/data/raw/` as JSON files.

## Requirements

- Python 3.8+
- Packages: `requests`, `PyYAML`, `python-dotenv`
