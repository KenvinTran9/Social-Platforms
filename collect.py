import os
import yaml
import requests
import json
import time
import base64
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    current_dir = Path(__file__).resolve().parent
    env_path = current_dir / ".env"
    load_dotenv(env_path)
except ImportError:
    print("[!] Cần cài đặt python-dotenv: pip install python-dotenv")

class APIError(Exception):
    pass

class YouTubeAPIError(APIError):
    pass

class RedditAPIError(APIError):
    pass

class RedditFetcher:
    def __init__(self, config: Dict):
        self.config = config
        self.reddit_config = config["sources"]["reddit"]
        self.session = requests.Session()
        self.access_token = None
        self._authenticate()
    
    def _authenticate(self):
        client_id = os.environ.get("REDDIT_CLIENT_ID")
        client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            raise RedditAPIError("Cần có REDDIT_CLIENT_ID và REDDIT_CLIENT_SECRET")
        
        auth_string = f"{client_id}:{client_secret}"
        auth_b64 = base64.b64encode(auth_string.encode('ascii')).decode('ascii')
        
        headers = {
            'Authorization': f'Basic {auth_b64}',
            'User-Agent': 'idea-collector/0.1'
        }
        
        response = requests.post(
            'https://www.reddit.com/api/v1/access_token',
            headers=headers,
            data={'grant_type': 'client_credentials'},
            timeout=30
        )

        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data['access_token']
            self.session.headers.update({
                'Authorization': f'Bearer {self.access_token}',
                'User-Agent': 'idea-collector/0.1'
            })
        else:
            raise RedditAPIError(f"Reddit auth failed: {response.status_code}")
    
    def _extract_post_data(self, post_data: Dict) -> Optional[Dict]:
        try:
            data = post_data["data"]
            return {
                "id": data["id"],
                "title": data["title"],
                "selftext": data.get("selftext", ""),
                "subreddit": data["subreddit"],
                "author": data.get("author", "[deleted]"),
                "score": data.get("score", 0),
                "num_comments": data.get("num_comments", 0),
                "created_utc": data["created_utc"],
                "permalink": f"https://www.reddit.com{data['permalink']}",
                "fetched_at": datetime.now().isoformat()
            }
        except KeyError:
            return None
    
    def fetch_reddit_posts(self, max_items: int = 20) -> List[Dict]:
        if not self.reddit_config.get("enabled", False):
            return []
        
        subreddits = self.reddit_config.get("subreddits", [])
        if not subreddits:
            return []
        
        all_results = []
        seen_post_ids: Set[str] = set()
        
        for subreddit in subreddits:
            print(f"[*] Fetching r/{subreddit}")
            
            url = f"https://oauth.reddit.com/r/{subreddit}/hot"
            params = {"limit": 25, "raw_json": 1}
            
            try:
                response = self.session.get(url, params=params, timeout=30)
                if response.status_code != 200:
                    continue
                
                data = response.json()
                posts = data.get("data", {}).get("children", [])
                
                for post in posts:
                    post_data = self._extract_post_data(post)
                    if post_data and post_data["id"] not in seen_post_ids:
                        all_results.append(post_data)
                        seen_post_ids.add(post_data["id"])
                
                print(f"[+] r/{subreddit}: {len(posts)} posts")
                time.sleep(1)
                
            except Exception as e:
                print(f"[!] Error r/{subreddit}: {e}")
                continue
        
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results[:max_items]

class YouTubeFetcher:
    def __init__(self, config: Dict):
        self.config = config
        self.api_key = os.environ.get("YOUTUBE_API_KEY")
        if not self.api_key:
            raise ValueError("Cần có YOUTUBE_API_KEY")
        self.session = requests.Session()
    
    def _extract_video_data(self, item: Dict) -> Optional[Dict]:
        try:
            video_id = item["id"]["videoId"]
            snippet = item["snippet"]
            return {
                "videoId": video_id,
                "title": snippet["title"],
                "description": snippet["description"],
                "channelTitle": snippet["channelTitle"],
                "publishedAt": snippet["publishedAt"],
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "fetched_at": datetime.now().isoformat()
            }
        except KeyError:
            return None
    
    def fetch_youtube_videos(self, max_items: int = 20) -> List[Dict]:
        youtube_config = self.config["sources"]["youtube"]
        
        if not youtube_config.get("enabled", False):
            return []
        
        search_terms = youtube_config.get("search_terms", [])
        if not search_terms:
            return []
        
        all_results = []
        seen_video_ids: Set[str] = set()
        
        for term in search_terms:
            print(f"[*] YouTube search: '{term}'")
            
            params = {
                "part": "snippet",
                "q": term,
                "maxResults": max_items // len(search_terms),
                "type": "video",
                "key": self.api_key
            }
            
            try:
                response = self.session.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params=params,
                    timeout=30
                )
                
                if response.status_code != 200:
                    continue
                
                data = response.json()
                for item in data.get("items", []):
                    video_data = self._extract_video_data(item)
                    if video_data and video_data["videoId"] not in seen_video_ids:
                        all_results.append(video_data)
                        seen_video_ids.add(video_data["videoId"])
                
                print(f"[+] Found {len(data.get('items', []))} videos")
                
            except Exception as e:
                print(f"[!] YouTube error: {e}")
                continue
        
        all_results.sort(key=lambda x: x["publishedAt"], reverse=True)
        return all_results[:max_items]

class DataCollector:
    def __init__(self, config_path: Path):
        self.config = self._load_config(config_path)
        
        config_dir = config_path.parent
        self.out_dir = config_dir / self.config["run"]["out_dir"]
        self.out_dir.mkdir(parents=True, exist_ok=True)
        
        self.youtube_fetcher = YouTubeFetcher(self.config)
        self.reddit_fetcher = RedditFetcher(self.config)
    
    def _load_config(self, config_path: Path) -> Dict:
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")
        
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    
    def collect_all_data(self) -> Dict[str, List[Dict]]:
        results = {}
        max_items = self.config["run"].get("max_items_per_source", 20)
        
        # YouTube
        if self.config["sources"]["youtube"].get("enabled", False):
            print("FETCHING YOUTUBE")
            try:
                results["youtube"] = self.youtube_fetcher.fetch_youtube_videos(max_items)
            except Exception as e:
                print(f"[!] YouTube failed: {e}")
                results["youtube"] = []
        
        # Reddit
        if self.config["sources"]["reddit"].get("enabled", False):
            print("FETCHING REDDIT")
            try:
                results["reddit"] = self.reddit_fetcher.fetch_reddit_posts(max_items)
            except Exception as e:
                print(f"[!] Reddit failed: {e}")
                results["reddit"] = []
        
        return results
    
    def save_json(self, data: Dict[str, List[Dict]], filename: Optional[str] = None) -> Path:
        total_items = sum(len(source_data) for source_data in data.values())
        
        output_data = {
            "metadata": {
                "total_items": total_items,
                "sources": {source: len(source_data) for source, source_data in data.items()},
                "fetched_at": datetime.now().isoformat()
            },
            "data": data
        }
        
        if not filename:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{timestamp}.json"
        
        filepath = self.out_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"[+] Saved {filepath} ({total_items} items)")
        return filepath

def main():
    try:
        current_dir = Path(__file__).resolve().parent
        config_path = current_dir / "config.yml"
        
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")
        
        collector = DataCollector(config_path)
        all_data = collector.collect_all_data()
        
        if any(all_data.values()):
            output_file = collector.save_json(all_data)
            print("\nSUMMARY:")
            for source, items in all_data.items():
                print(f"[✓] {source.upper()}: {len(items)} items")
            print(f"[✓] Output: {output_file}")
        else:
            print("[!] No data collected")
            
    except Exception as e:
        print(f"[!] Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())