# -*- coding: utf-8 -*-
"""
GitHub Actions — 每日新闻早报
每天 7:00 (北京时间) 自动抓取新闻 + 天气，推送到企业微信群
"""
import json
import requests
import datetime
import time
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
HOURS_24 = 24 * 3600

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
    except Exception as e:
        print(f"   天气获取失败: {e}")
        return "天气数据获取中"

# ==================== 新闻 ====================
NEWS_SOURCES_DOMESTIC = [
    {"name": "人民网政治", "url": "http://www.people.com.cn/rss/politics.xml"},
    {"name": "人民网社会", "url": "http://www.people.com.cn/rss/society.xml"},
    {"name": "澎湃新闻",   "url": "https://www.thepaper.cn/rss.jsp"},
]

NEWS_SOURCES_INTERNATIONAL = [
    {"name": "人民网国际", "url": "http://www.people.com.cn/rss/world.xml"},
    {"name": "联合早报中国", "url": "https://www.zaobao.com.sg/rss/realtime/china"},
]

def to_simplified(text):
    if zhconv and text:
        try:
            return zhconv.convert(text, 'zh-cn')
        except Exception:
            pass
    return text

def parse_pub_time(entry):
    """尝试解析 RSS 条目的发布时间，返回 UNIX 时间戳或 None"""
    for key in ("published_parsed", "updated_parsed"):
        t = getattr(entry, key, None)
        if t:
            try:
                return time.mktime(t)
            except Exception:
                pass
    # 尝试解析 published 字符串
    for key in ("published", "updated", "pubDate"):
        s = getattr(entry, key, None)
        if s:
            try:
                import email.utils
                t = email.utils.parsedate_to_datetime(s)
                if t:
                    return t.timestamp()
            except Exception:
                pass
    return None

def is_recent(pub_ts, max_seconds=HOURS_24):
    """发布时间是否在最近 max_seconds 内"""
    if pub_ts is None:
        return True  # 无法判断时间，保留
    now = time.time()
    return (now - pub_ts) <= max_seconds

def smart_truncate(text, max_chars=50):
    text = text.strip()
    if len(text) <= max_chars:
        return text
    snippet = text[:max_chars]
    for i in range(len(snippet) - 1, -1, -1):
        if snippet[i] in '。！？.!?':
            return snippet[:i + 1]
    for i in range(len(snippet) - 1, -1, -1):
        if snippet[i] in '，,；;':
            return snippet[:i + 1]
    return snippet

def fetch_news(sources, max_items=6, max_age_hours=24):
    all_items = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
    cutoff = time.time() - max_age_hours * 3600

    for source in sources:
        try:
            print(f"   抓取 [{source['name']}]...")
            resp = requests.get(source["url"], headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"     失败: HTTP {resp.status_code}")
                continue
            feed = feedparser.parse(resp.content)
            print(f"     获取到 {len(feed.entries)} 条，过滤最近 {max_age_hours}h")
            count = 0
            for entry in feed.entries:
                title = html.unescape(entry.get("title", "").strip())
                title = to_simplified(title)
                link = entry.get("link", "")
                desc = entry.get("description", "") or entry.get("summary", "")
                desc = html.unescape(desc)
                desc = re.sub(r'<[^>]+>', '', desc)
                desc = to_simplified(desc.strip())
                desc = smart_truncate(desc, 50)
                if not desc:
                    desc = title[:50]

                # 时间过滤
                pub_ts = parse_pub_time(entry)
                if pub_ts and pub_ts < cutoff:
                    continue  # 太旧，跳过

                if title and link:
                    all_items.append({
                        "title": title[:30],
                        "link": link,
                        "summary": desc,
                        "source": source["name"],
                    })
                    count += 1
                if len(all_items) >= max_items * 3:
                    break
            print(f"     最近 {max_age_hours}h 内有 {count} 条")
        except Exception as e:
            print(f"     异常: {e}")
            continue

    # 去重
    seen = set()
    unique = []
    for item in all_items:
        key = item["title"][:15]
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) >= max_items:
            break
    return unique[:max_items]

def format_news_items(items):
    if not items:
        return "> _暂无新闻数据_"
    lines = []
    for i, item in enumerate(items):
        lines.append(f"{i+1}. {item['title']}：{item['summary']} [【查看详情】]({item['link']})")
    return "\n".join(lines)

# ==================== 祝福语 ====================
BLESSINGS = [
    "新的一天，愿你专注高效，收获成就感！",
    "愿今日工作顺遂，事事有回应，件件有着落！",
    "早上好，愿今天的你比昨天更接近目标！",
    "愿你的每一个决策都清晰有力，每一步都坚定从容！",
    "今天也是发光的一天，加油！",
    "愿你以最好的状态，迎接每一个挑战！",
]

def get_blessing():
    return random.choice(BLESSINGS)

# ==================== 主函数 ====================
def main():
    now = datetime.datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday_str = weekdays[now.weekday()]
    now_str = now.strftime("%H:%M")

    print(f"执行时间: {date_str} {weekday_str} {now_str}")

    print("获取天气...")
    weather = get_weather()
    print(f"   天气: {weather}")

    print("获取国内新闻（最近24小时）...")
    domestic = fetch_news(NEWS_SOURCES_DOMESTIC, max_items=6, max_age_hours=24)
    print(f"   国内: {len(domestic)} 条")

    print("获取国际新闻（最近24小时）...")
    international = fetch_news(NEWS_SOURCES_INTERNATIONAL, max_items=6, max_age_hours=24)
    print(f"   国际: {len(international)} 条")

    blessing = get_blessing()

    domestic_text = format_news_items(domestic)
    international_text = format_news_items(international)

    markdown_content = f"""## 彭先生早报 | {date_str} {weekday_str} {now_str}

**早上好！今天又是能量满满的一天**

今日天气: {weather}

**国内要闻**
{domestic_text}

**国际要闻**
{international_text}

---
> {blessing}
> 每日 7:00 自动推送 | 新闻小助手"""

    content_bytes = markdown_content.encode("utf-8")
    if len(content_bytes) > 4000:
        markdown_content = content_bytes[:4000].decode("utf-8", errors="ignore")

    print("发送到企业微信...")
    payload = {"msgtype": "markdown", "markdown": {"content": markdown_content}}

    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        result = resp.json()
        print(f"   结果: {result}")
        if result.get("errcode") == 0:
            print("推送成功！")
        else:
            print(f"推送失败: {result}")
            exit(1)
    except Exception as e:
        print(f"发送异常: {e}")
        exit(1)

if __name__ == "__main__":
    main()
