"""
批量下载真实公开文档脚本 —— 抓取 gov.cn 国务院政策文件，存为纯文本 TXT。

用法：
    python eval/download_docs.py

流程：
    1. 抓取 gov.cn 政策文件库的列表页（服务端渲染）
    2. 提取所有详情页 URL（content_*.htm）
    3. 逐个抓详情页，提取 <div class="*pages_content*"> 正文
    4. 清洗文本，按标题存为 eval/data/*.txt
    5. 统计总份数 / 总字数 / 总字节数
"""
import os
import re
import time
import urllib.request

# gov.cn 政策文件库列表页（服务端渲染，可直接抓）
LIST_PAGES = [
    "https://www.gov.cn/zhengce/xxgk/",      # 政府信息公开（~42 份）
    "https://www.gov.cn/zhengce/zuixin/",    # 最新政策（~8 份）
]

OUT_DIR = os.path.join(os.path.dirname(__file__), "data")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch(url: str, timeout: int = 20) -> str:
    """抓取网页，返回 UTF-8 文本。"""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def extract_urls(html: str) -> list[str]:
    """从列表页提取详情页 URL，去重保序。"""
    urls = []
    for u in re.findall(r'href="(https://www\.gov\.cn/[^"]*content_\d+\.htm)"', html):
        if u not in urls:
            urls.append(u)
    return urls


def clean_filename(title: str) -> str:
    """把标题清洗成合法文件名。"""
    title = re.sub(r'[\\/:*?"<>|\r\n\t]', "", title).strip()
    return (title[:80] or "untitled") + ".txt"


def extract_body(html: str) -> str:
    """提取详情页正文：正文容器 class 含 pages_content。"""
    m = re.search(r'class="[^"]*pages_content[^"]*"[^>]*>(.*?)</div>', html, re.S)
    body = m.group(1) if m else ""
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    text = re.sub(r"<[^>]+>", "", body)
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)

    # 1. 收集所有详情页 URL
    all_urls: list[str] = []
    for lp in LIST_PAGES:
        try:
            html = fetch(lp)
            urls = extract_urls(html)
            print(f"[列表] {lp}  ->  {len(urls)} 个详情链接")
            all_urls.extend(urls)
        except Exception as e:
            print(f"[列表] {lp} 抓取失败: {e}")

    # 去重保序
    seen = set()
    urls = [u for u in all_urls if not (u in seen or seen.add(u))]

    # 2. 逐个抓详情页
    total_chars = 0
    ok = 0
    for i, u in enumerate(urls, 1):
        try:
            html = fetch(u)
            t = re.search(r"<title[^>]*>(.*?)</title>", html, re.S)
            title = re.sub(r"_中国政府网.*$", "", t.group(1).strip()) if t else u.split("/")[-1]
            text = extract_body(html)
            if len(text) < 50:  # 正文太短视为提取失败
                print(f"  [{i}/{len(urls)}] 跳过(正文过短) {title[:40]}")
                continue
            path = os.path.join(OUT_DIR, clean_filename(title))
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            total_chars += len(text)
            ok += 1
            print(f"  [{i}/{len(urls)}] {len(text):>6} 字  {title[:40]}")
            time.sleep(0.3)  # 礼貌限速
        except Exception as e:
            print(f"  [{i}/{len(urls)}] 失败 {u.split('/')[-1]}: {e}")

    # 3. 汇总
    total_bytes = sum(os.path.getsize(os.path.join(OUT_DIR, f)) for f in os.listdir(OUT_DIR) if f.endswith(".txt"))
    print("\n" + "=" * 50)
    print(f"  成功下载: {ok} 份")
    print(f"  总字数:   {total_chars} 字")
    print(f"  总字节:   {total_bytes} 字节 ({total_bytes / 1024 / 1024:.2f} MB)")
    print(f"  存放目录: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
