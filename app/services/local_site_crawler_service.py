import asyncio
import json
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Set
from urllib.parse import quote

from playwright.async_api import async_playwright, Page, BrowserContext

from app.models.schemas import (
    SearchCrawlRequest,
    SearchCrawlResponse,
    NoteItem,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

XHS_BASE = "https://www.xiaohongshu.com"
COOKIES_FILE = "data/raw/xhs_cookies.json"
STATE_FILE   = "data/raw/xhs_state.json"

INVALID_AD_WORDS = ["商单", "广告", "投放合作", "品牌合作"]
VIDEO_TYPE_KEYWORDS = ["视频", "直播", "合集"]


# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------

class XHSCrawler:
    """
    Two-phase crawler for real xiaohongshu.com.

    Phase 1 – Search pages: collect card URLs, skip video cards, pre-filter by date.
    Phase 2 – Detail pages: extract all data from detail page as single source of truth.
    Filters: 图文-only, comments > threshold, within 1 year, relevant topic.
    """

    # ---------- Search-page selectors ----------
    CARD_SELECTOR      = "section.note-item"
    CARD_LINK_SELECTOR = "a.cover"
    CARD_AUTHOR_SELECTOR = ".author"
    CARD_DATE_SELECTOR   = ".time"
    VIDEO_CARD_SELECTORS = [
        ".video-badge", ".play-icon", ".duration", "[class*='video-mark']",
    ]

    # ---------- Detail page selectors ----------
    DETAIL_CONTENT_SELECTOR = "#detail-desc"
    DETAIL_DATE_SELECTORS   = [".bottom-container .date", ".note-header .date", ".date"]
    DETAIL_TAG_SELECTORS    = ["#detail-desc .tag", "#hash-tag", ".tag"]

    # Counts from Open Graph meta tags (most reliable)
    META_COMMENT = "meta[name='og:xhs:note_comment']"
    META_LIKE    = "meta[name='og:xhs:note_like']"
    META_COLLECT = "meta[name='og:xhs:note_collect']"

    POPUP_CLOSE_SELECTORS = [
        ".close-btn", ".modal-close", "[class*='close-icon']", "button.close",
    ]

    def __init__(self, request: SearchCrawlRequest):
        self.request = request
        self.collected: List[NoteItem] = []
        self.seen_urls: Set[str] = set()
        self.used_keywords: List[str] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def _make_context(self, browser, storage_state: str | None = None):
        """创建浏览器 context，统一 viewport 和 UA。"""
        ctx_kwargs = {
            "viewport": {"width": 1440, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state
        return await browser.new_context(**ctx_kwargs)

    async def crawl(self) -> SearchCrawlResponse:
        keywords = self.request.keywords
        state_path = Path(STATE_FILE)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )

            # 首次创建 context（带 storage_state）
            context = await self._make_context(
                browser,
                storage_state=str(state_path) if state_path.exists() else None,
            )
            page = await context.new_page()

            # 检查并确保已登录（过期时自动重新登录，返回有效 page/context）
            page, context = await self._ensure_logged_in(browser)

            try:
                for keyword in keywords:
                    if len(self.collected) >= self.request.target_count:
                        break
                    self.used_keywords.append(keyword)
                    print(f"\n[搜索] {keyword}")
                    links = await self._collect_card_links(page, keyword)
                    print(f"  → 找到候选卡片 {len(links)} 张")

                    for card in links:
                        if len(self.collected) >= self.request.target_count:
                            break
                        note = await self._fetch_note_detail(page, card)
                        if note and self._is_valid(note):
                            self._add_note(note)

                await browser.close()

            except Exception:
                await browser.close()
                raise

        print(f"\n[完成] 共采集 {len(self.collected)} / {self.request.target_count} 条")
        return SearchCrawlResponse(
            target_count=self.request.target_count,
            count=len(self.collected),
            used_keywords=self.used_keywords,
            items=self.collected,
        )

    # ------------------------------------------------------------------
    # Phase 1: collect card links
    # ------------------------------------------------------------------

    async def _collect_card_links(self, page: Page, keyword: str) -> List[dict]:
        search_url = f"{XHS_BASE}/search_result?keyword={quote(keyword)}&source=web_explore_feed"

        # 重试 3 次，页面加载失败时降级处理
        for attempt in range(3):
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(random.uniform(2.0, 3.5))
                await self._dismiss_popups(page)
                # 等待卡片容器出现，最长等 5 秒
                try:
                    await page.wait_for_selector(self.CARD_SELECTOR, timeout=5000)
                except Exception:
                    pass
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  ⚠ 页面加载失败（{keyword}）: {e}")
                    return []
                await asyncio.sleep(2)

        # DEBUG: 打印页面标题和 URL，确认是否登录或被拦截
        page_title = await page.title()
        page_url = page.url
        card_count = await page.locator(self.CARD_SELECTOR).count()
        print(f"  [DEBUG] title={page_title!r}, url={page_url}, cards={card_count}")

        # 增加滚动次数，确保更多内容加载
        await self._scroll_page(page, rounds=8)

        links: List[dict] = []
        seen_in_batch: Set[str] = set()

        cards = await page.locator(self.CARD_SELECTOR).all()
        debug_reasons: dict = {"video": 0, "no_href": 0, "duplicate": 0, "old_date": 0, "ok": 0, "error": 0}
        for idx, card in enumerate(cards):
            try:
                is_video = await self._is_video_card(card)
                if is_video:
                    debug_reasons["video"] += 1
                    continue

                href = await card.locator(self.CARD_LINK_SELECTOR).first.get_attribute("href", timeout=5000)
                if not href:
                    debug_reasons["no_href"] += 1
                    continue

                url = href if href.startswith("http") else f"{XHS_BASE}{href}"
                if url in self.seen_urls or url in seen_in_batch:
                    debug_reasons["duplicate"] += 1
                    continue
                seen_in_batch.add(url)

                author_raw = await self._safe_text(card, self.CARD_AUTHOR_SELECTOR)
                author = author_raw.split("\n")[0].strip() if author_raw else None
                date_text = await self._safe_text(card, self.CARD_DATE_SELECTOR)
                card_date = self._normalize_date(date_text)
                if idx < 5:
                    print(f"  [DEBUG] 卡{idx}: author={author_raw!r}, date={date_text!r}, card_date={card_date}")

                # Pre-filter: skip cards clearly older than 1 year
                if date_text and card_date and not self._is_within_one_year(card_date):
                    debug_reasons["old_date"] += 1
                    continue

                debug_reasons["ok"] += 1
                links.append({
                    "url": url,
                    "author": author.strip() if author else None,
                    "card_date": card_date,
                    "keyword": keyword,
                })
            except Exception as e:
                debug_reasons["error"] += 1
                print(f"  [DEBUG] 卡片 {idx} 异常: {e}")
                continue

        print(f"  [DEBUG] 卡片筛选: {debug_reasons}")

        return links

    async def _is_video_card(self, card) -> bool:
        for selector in self.VIDEO_CARD_SELECTORS:
            try:
                if await card.locator(selector).count() > 0:
                    return True
            except Exception:
                continue
        try:
            tag_area = card.locator(".bottom-tag-area")
            if await tag_area.count() > 0:
                text = await tag_area.first.inner_text()
                if any(kw in text for kw in VIDEO_TYPE_KEYWORDS):
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Phase 2: fetch detail page (single source of truth)
    # ------------------------------------------------------------------

    async def _fetch_note_detail(self, page: Page, card: dict) -> Optional[NoteItem]:
        url = card["url"]
        # 重试 2 次，页面加载失败时跳过
        for attempt in range(2):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(random.uniform(1.0, 1.8))
                await self._dismiss_popups(page)
            except Exception as e:
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                print(f"  ⚠ 详情页加载失败: {url}, {e}")
                return None

            # Title: strip " - 小红书" suffix; take first line; cap at 100 chars
            raw_title = await page.title()
            title = re.sub(r"\s*[-–—]\s*小红书.*$", "", raw_title).strip()
            title = title.split("\n")[0].strip()[:100]

            content       = await self._safe_text(page, self.DETAIL_CONTENT_SELECTOR) or ""
            date_raw      = await self._safe_text_candidates(page, self.DETAIL_DATE_SELECTORS)
            comments_text = await self._meta_content(page, self.META_COMMENT)
            like_text     = await self._meta_content(page, self.META_LIKE)
            collect_text  = await self._meta_content(page, self.META_COLLECT)

            tags: List[str] = []
            for selector in self.DETAIL_TAG_SELECTORS:
                try:
                    loc = page.locator(selector)
                    if await loc.count() > 0:
                        tags = [t.strip() for t in await loc.all_inner_texts() if t.strip()]
                        break
                except Exception:
                    continue

            publish_time = self._normalize_date(date_raw) or card.get("card_date")

            return NoteItem(
                title=title,
                content=content.strip(),
                author=card.get("author"),
                comments=self._parse_number(comments_text),
                likes=self._parse_number(like_text),
                favorites=self._parse_number(collect_text),
                tags=tags,
                publish_time=publish_time,
                url=url,
                content_type="图文",
                keyword_used=card["keyword"],
            )
        return None

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _is_valid(self, note: NoteItem) -> bool:
        # Content must exist (title can be empty)
        if not note.content:
            return False

        text = f"{note.title} {note.content}"

        # Skip ads
        if any(w in text for w in INVALID_AD_WORDS):
            return False

        # Must be relevant topic（为空则跳过此过滤）
        if self.request.topic_words and not any(w in text for w in self.request.topic_words):
            return False

        # 评论数、点赞数、收藏数三项都必须满足 >= 设定值
        if note.comments < self.request.min_comments:
            return False
        if note.likes < self.request.min_likes:
            return False
        if note.favorites < self.request.min_favorites:
            return False

        # Published within 1 year
        if not self._is_within_one_year(note.publish_time):
            return False

        return True

    def _is_within_one_year(self, publish_time: Optional[str]) -> bool:
        if not publish_time:
            return False
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                dt = datetime.strptime(publish_time.strip(), fmt)
                return dt >= datetime.now() - timedelta(days=365)
            except ValueError:
                continue
        return False

    def _add_note(self, note: NoteItem) -> None:
        url = (note.url or "").strip()
        if url and url in self.seen_urls:
            return
        if url:
            self.seen_urls.add(url)
        self.collected.append(note)
        preview = (note.title or note.content)[:30]
        print(f"  [OK] [已收集 {len(self.collected)} / {self.request.target_count}] {preview}")

    # ------------------------------------------------------------------
    # Page utilities
    # ------------------------------------------------------------------

    async def _scroll_page(self, page: Page, rounds: int = 5) -> None:
        for i in range(rounds):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(random.uniform(1.0, 1.8))
            if i < rounds - 1:
                # 滚动后等待新内容加载
                await page.wait_for_timeout(800)

    async def _verify_login(self, page: Page) -> bool:
        """
        验证当前页面是否处于登录状态。
        通过检测页面是否包含用户专属元素（头像、用户名、我的页面链接）
        或是否被重定向到了登录页来判断。
        """
        try:
            current_url = page.url
            # 如果 URL 包含登录相关的重定向，说明未登录或已过期
            if "login" in current_url.lower() or "passport" in current_url.lower():
                return False

            # 等待页面稳定
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            await asyncio.sleep(1)

            # 登录成功时，顶部导航栏会有"登录"按钮（未登录状态），
            # 登录后该按钮消失，取而代之的是用户头像或用户名
            try:
                login_btn = page.locator(".login-button")
                if await login_btn.count() > 0:
                    return False
            except Exception:
                pass

            # 检查登录用户元素（头像、我的页面入口等）
            logged_in_selectors = [
                ".avatar",
                "a[href*='/user/profile']",
                ".header-user",
                "[class*='user-info']",
            ]
            for selector in logged_in_selectors:
                try:
                    if await page.locator(selector).count() > 0:
                        return True
                except Exception:
                    pass

            return False
        except Exception:
            return False

    async def _ensure_logged_in(self, browser) -> tuple[Page, BrowserContext]:
        """
        确保已登录，返回 (page, context)。

        流程：
        1. 有 state 文件 → 加载，验证是否有效
        2. 有效 → 直接用
        3. 过期/无效 → 删除旧文件，重新引导登录，保存新 state
        """
        Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)

        if Path(STATE_FILE).exists():
            # 加载已有 state，验证是否仍然有效
            print("[XHSCrawler] 已加载持久化登录态，验证有效性…")
            context = await self._make_context(browser, storage_state=str(STATE_FILE))
            page = await context.new_page()
            await page.goto(XHS_BASE, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            if await self._verify_login(page):
                print("[XHSCrawler] 登录态有效，跳过登录 OK")
                return page, context

            # state 过期：关闭当前 context，重建
            print("[XHSCrawler] 登录态已过期或无效，需要重新登录")
            await context.close()
            Path(STATE_FILE).unlink(missing_ok=True)

        # 重新登录：创建空白 context，引导用户登录，保存 state
        context = await self._make_context(browser)
        page = await context.new_page()
        await page.goto(XHS_BASE, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1)

        print("[XHSCrawler] 请在弹出的浏览器窗口中完成小红书登录，登录完成后回到此终端按 Enter 继续…")
        await asyncio.get_event_loop().run_in_executor(None, input)

        # 验证登录成功后保存 state
        await page.goto(XHS_BASE, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        if not await self._verify_login(page):
            await context.close()
            raise RuntimeError("登录验证失败，请重新运行程序")

        await context.storage_state(path=STATE_FILE)
        print(f"[XHSCrawler] 登录态已保存至 {STATE_FILE}，后续启动自动跳过登录 OK")
        return page, context

    async def _dismiss_popups(self, page: Page) -> None:
        for selector in self.POPUP_CLOSE_SELECTORS:
            try:
                btn = page.locator(selector).first
                if await btn.count() > 0:
                    await btn.click()
                    await asyncio.sleep(0.3)
                    return
            except Exception:
                continue

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    async def _meta_content(self, page: Page, selector: str) -> Optional[str]:
        try:
            loc = page.locator(selector)
            if await loc.count() > 0:
                return await loc.first.get_attribute("content")
        except Exception:
            pass
        return None

    async def _safe_text(self, element, selector: str) -> Optional[str]:
        try:
            loc = element.locator(selector).first
            if await loc.count() > 0:
                text = await loc.inner_text()
                return text.strip() if text and text.strip() else None
        except Exception:
            pass
        return None

    async def _safe_text_candidates(self, element, selectors: List[str]) -> Optional[str]:
        for sel in selectors:
            text = await self._safe_text(element, sel)
            if text:
                return text
        return None

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    def _normalize_date(self, text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        text = text.strip()
        m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})", text)
        if m:
            return m.group(1).replace("/", "-")
        m = re.search(r"(\d+)天前", text)
        if m:
            return (datetime.now() - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
        if "小时前" in text or "分钟前" in text or "刚刚" in text:
            return datetime.now().strftime("%Y-%m-%d")
        m = re.search(r"(\d{1,2})-(\d{1,2})", text)
        if m:
            return f"{datetime.now().year}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
        return None

    def _parse_number(self, text: Optional[str]) -> int:
        if not text:
            return 0
        text = text.strip().replace(",", "")
        low = text.lower()
        if "w" in low or "万" in low:
            m = re.search(r"(\d+(?:\.\d+)?)", low)
            if m:
                return int(float(m.group(1)) * 10000)
        if "k" in low:
            m = re.search(r"(\d+(?:\.\d+)?)", low)
            if m:
                return int(float(m.group(1)) * 1000)
        m = re.search(r"(\d+)", text)
        return int(m.group(1)) if m else 0

    # ------------------------------------------------------------------
    # Cookie loader
    # ------------------------------------------------------------------

    async def _load_cookies(self, context: BrowserContext) -> None:
        path = Path(COOKIES_FILE)
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and "cookies" in raw:
                raw = raw["cookies"]

            SAME_SITE_MAP = {"strict": "Strict", "lax": "Lax", "no_restriction": "None"}
            cookies = []
            for c in raw:
                cookie: dict = {
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c["domain"],
                    "path": c.get("path", "/"),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                }
                if "expirationDate" in c:
                    cookie["expires"] = int(c["expirationDate"])
                elif "expires" in c:
                    cookie["expires"] = int(c["expires"])
                ss = str(c.get("sameSite", "")).lower()
                cookie["sameSite"] = SAME_SITE_MAP.get(ss, "None")
                cookies.append(cookie)

            await context.add_cookies(cookies)
            print(f"[XHSCrawler] 已加载 {len(cookies)} 个 Cookie")
        except Exception as e:
            print(f"[XHSCrawler] Cookie 加载失败: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def crawl_local_site_notes(request: SearchCrawlRequest) -> SearchCrawlResponse:
    crawler = XHSCrawler(request)
    return await crawler.crawl()


async def check_crawler_login_status() -> dict:
    """
    主动检查爬虫登录状态，不依赖完整采集流程。

    返回：
        {
            "has_state_file": bool,       # 是否存在持久化文件
            "is_logged_in": bool,        # 当前登录态是否有效
            "message": str                # 状态描述
        }
    """
    state_path = Path(STATE_FILE)
    result = {
        "has_state_file": state_path.exists(),
        "is_logged_in": False,
        "message": "",
    }

    if not result["has_state_file"]:
        result["message"] = "无持久化登录文件，需要手动登录"
        return result

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                storage_state=str(state_path),
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            await page.goto(XHS_BASE, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # 复用 crawler 的验证逻辑
            crawler = XHSCrawler.__new__(XHSCrawler)
            is_logged_in = await crawler._verify_login(page)

            result["is_logged_in"] = is_logged_in
            result["message"] = (
                "登录有效" if is_logged_in else "登录已过期，需要重新登录"
            )
            await browser.close()
    except Exception as e:
        result["message"] = f"检查失败: {e}"

    return result
