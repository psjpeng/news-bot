# -*- coding: utf-8 -*-
"""
GitHub Actions — 每日新闻早报
每天 7:00 (北京时间) 自动抓取新闻 + 天气，推送到企业微信群
"""
import json
import requests
import datetime
import feedparser
import random
import re
import html
from datetime import timezone, timedelta

try:
    import zhconv
except ImportError:
    zhconv = None

# ==================== 配置 ====================
WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=5fafe6e6-bbc8-49fc-bb53-96c6dfc18d0b"
CITY = "Beijing"
TZ = timezone(timedelta(hours=8))

# ==================== 天气 ====================
def get_weather():
    try:
        url = f"https://wttr.in/{CITY}?format=%C+%t+%w&lang=zh"
        headers = {"User-Agent": "curl/7.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            info = resp.text.strip()
            info = re.sub(r'\x1b\[[0-9;]*m', '', info)
            info = re.sub(r'\s+', ' ', info).strip()
            return info if info else "天气数据获取中"
        return "天气数据获取中"
    except Exception:
        return "天气数据获取中"

# ==================== 新闻 ====================
NEWS_SOURCES_DOMESTIC = [
    {"name": "人民网", "url": "http://www.people.com.cn/rss/politics.xml"},
    {"name": "人民网社会", "url": "http://www.people.com.cn/rss/society.xml"},
    {"name": "新浪新闻", "url": "https://rss.sina.com.cn/news/marquee/ddt.xml"},
]

NEWS_SOURCES_INTERNATIONAL = [
    {"name": "人民网国际", "url": "http://www.people.com.cn/rss/world.xml"},
]

def to_simplified(text):
    if zhconv and text:
        try:
            return zhconv.convert(text, 'zh-cn')
        except Exception:
            pass
    return text

def fetch_news(sources, max_items=6):
    all_items = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}

    for source in sources:
        try:
            resp = requests.get(source["url"], headers=headers, timeout=15)
            if resp.status_code != 200:
                continue
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:max_items]:
                title = html.unescape(entry.get("title", "").strip())
                title = to_simplified(title)
                link = entry.get("link", "")
                desc = entry.get("description", "") or entry.get("summary", "")
                desc = html.unescape(desc)
                desc = re.sub(r'<[^>]+>', '', desc)
                desc = to_simplified(desc.strip()[:50])
                if not desc:
                    desc = title[:50]
                if title and link:
                    all_items.append({
                        "title": title[:40],
                        "link": link,
                        "summary": desc,
                        "source": source["name"],
                    })
        except Exception:
            continue

    seen = set()
    unique = []
    for item in all_items:
        key = item["title"][:15]
        if key not in seen:
            seen
