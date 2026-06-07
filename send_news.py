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

# ==================== 工具函数 ====================
def to_simplified(text):
    if zhconv and text:
        try:
            return zhconv.convert(text, 'zh-cn')
        except Exception:
            pass
    return text

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

def parse_pub_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = getattr(entry, key, None)
        if t:
            try:
                return time.mktime(t)
            except Exception:
                pass
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

# ==================== 知乎热榜（国内） ====================
def fetch_zhihu_hot(max_items=6):
    """抓取知乎热榜，作为国内新闻源"""
    try:
        url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            print(f"   知乎热榜: HTTP {resp.status_code}")
            return []
        data = resp.json()
        items = data.get("data", [])[:max_items]
        result = []
        for item in items:
            target = item.get("target", {})
            title = target.get("title", "").strip()
            url_link = target.get("url", "") or f"https://www.zhihu.com/question/{target.get('id', '')}"
            excerpt = target.get("excerpt", "") or title
            excerpt = smart_truncate(to_simplified(excerpt), 50)
            if not excerpt:
                excerpt = title[:50]
            if title:
                result.append({
                    "title": to_simplified(title)[:30],
                    "link": url_link,
                    "summary": excerpt,
                    "source": "知乎热榜",
                })
        print(f"   知乎热榜: 获取到 {len(result)} 条")
        return result
    except Exception as e:
        print(f"   知乎热榜异常: {e}")
        return []

# ==================== 百度热搜（备选） ====================
def fetch_baidu_hot(max_items=6):
    try:
        url = "https://top.baidu.com/board?tab=realtime"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []
        text = resp.text
        # 从页面中提取热搜标题
        matches = re.findall(r'"query":"([^"]+)"', text)
        result = []
        for i, title in enumerate(matches[:max_items]):
            result.append({
                "title": to_simplified(title)[:30],
                "link": f"https://www.baidu.com/s?wd={requests.utils.quote(title)}",
                "summary": title[:50],
                "source": "百度热搜",
            })
        print(f"   百度热搜: 获取到 {len(result)} 条")
        return result
    except Exception as e:
        print(f"   百度热搜异常: {e}")
        return []

# ==================== RSS 新闻 ====================
NEWS_SOURCES_DOMESTIC = [
    {"name": "人民网政治", "url": "http://www.people.com.cn/rss/politics.xml"},
    {"name": "人民网社会", "url": "http://www.people.com.cn/rss/society.xml"},
]

NEWS_SOURCES_INTERNATIONAL = [
    {"name": "人民网国际", "url": "http://www.people.com.cn/rss/world.xml"},
]

def fetch_rss_news(sources, max_items=6, max_age_hours=48):
    """抓取 RSS 新闻，带时间过滤"""
    all_items = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
    cutoff = time.time() - max_age_hours * 3600

    for source in sources:
        try:
            print(f"   抓取 [{source['name']}]...")
            resp = requests.get(source["url"], headers=headers, timeout=15)
            print(f"     HTTP状态: {resp.status_code}, 内容长度: {len(resp.content)}")
            if resp.status_code != 200:
                continue
            feed = feedparser.parse(resp.content)
            print(f"     解析到 {len(feed.entries)} 条条目")
            count = 0
            for entry in feed.entries[:max_items * 3]:
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

                # 时间过滤（宽松的：最多保留48小时，RSS没时间戳也保留）
                pub_ts = parse_pub_time(entry)
                if pub_ts and pub_ts < cutoff:
                    print(f"     跳过旧新闻: {title[:20]}... ({datetime.datetime.fromtimestamp(pub_ts).strftime('%m-%d %H:%M')})")
                    continue

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
            print(f"     保留 {count} 条")
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

    # 国内新闻：RSS + 知乎热榜
    print("获取国内新闻...")
    domestic_rss = fetch_rss_news(NEWS_SOURCES_DOMESTIC, max_items=6, max_age_hours=48)
    domestic_zhihu = fetch_zhihu_hot(max_items=4)
    domestic = domestic_rss + domestic_zhihu
    # 去重
    seen = set()
    unique = []
    for item in domestic:
        key = item["title"][:15]
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) >= 6:
            break
    domestic = unique[:6]
    print(f"   国内总计: {len(domestic)} 条 (RSS {len(domestic_rss)}, 知乎 {len(domestic_zhihu)})")

    # 国际新闻：RSS + 百度热搜
    print("获取国际新闻...")
    international_rss = fetch_rss_news(NEWS_SOURCES_INTERNATIONAL, max_items=6, max_age_hours=48)
    international_baidu = fetch_baidu_hot(max_items=4)
    international = international_rss + international_baidu
    seen = set()
    unique = []
    for item in international:
        key = item["title"][:15]
        if key not in seen:
            seen.add(key)
            unique.append(item)
        if len(unique) >= 6:
            break
    international = unique[:6]
    print(f"   国际总计: {len(international)} 条 (RSS {len(international_rss)}, 百度 {len(international_baidu)})")

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
