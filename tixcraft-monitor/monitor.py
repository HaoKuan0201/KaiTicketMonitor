#!/usr/bin/env python3
"""
TixCraft 票卷監控器
- 定時檢查票況
- 狀態變化時推播 Slack 通知
- 部署至 GitHub Actions
"""

import os
import json
import time
import logging
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ===== 設定 =====
@dataclass
class Config:
    # Slack
    slack_webhook_url: str
    
    # 監控目標
    tixcraft_activity_url: str  # 例如: https://tixcraft.com/activity/detail/xxx
    
    # 通知條件
    notify_on_available: bool = True
    notify_on_sold_out: bool = True
    
    # 速率控制（秒）
    request_delay: float = 2.0  # 請求間隔，避免被封
    
    # User-Agent
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

config = Config(
    slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL", ""),
    tixcraft_activity_url=os.environ.get("TIXCRAFT_ACTIVITY_URL", ""),
)

# ===== 日誌設定 =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# ===== 票種資料結構 =====
@dataclass
class TicketArea:
    """票種區域"""
    name: str           # 區域名稱 (如 "特價區", "VIP區")
    price: str          # 票價
    status: str         # 狀態 (available / sold_out / unknown)
    remaining: Optional[int]  # 剩餘數量 (如果有的話)


@dataclass
class MonitorResult:
    """監控結果"""
    url: str
    timestamp: str
    event_name: str
    areas: list[TicketArea]
    has_available: bool
    
    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "timestamp": self.timestamp,
            "event_name": self.event_name,
            "areas": [asdict(area) for area in self.areas],
            "has_available": self.has_available
        }


# ===== 爬蟲核心 =====
class TixCraftMonitor:
    """TixCraft 票卷監控器"""
    
    BASE_URL = "https://tixcraft.com"
    SESSION_FILE = ".session_cache.json"
    
    def __init__(self, config: Config):
        self.config = config
        self.session = self._create_session()
        
    def _create_session(self) -> requests.Session:
        """建立 HTTP Session"""
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        return session
    
    def _load_session_cookies(self) -> dict:
        """載入快取的 Session Cookie (如果有)"""
        if Path(self.SESSION_FILE).exists():
            try:
                with open(self.SESSION_FILE, 'r') as f:
                    cookies = json.load(f)
                logger.info("已載入快取的 Session Cookie")
                return cookies
            except Exception:
                pass
        return {}
    
    def _save_session_cookies(self, cookies: dict):
        """儲存 Session Cookie"""
        try:
            with open(self.SESSION_FILE, 'w') as f:
                json.dump(cookies, f)
            logger.info("已儲存 Session Cookie")
        except Exception as e:
            logger.warning(f"無法儲存 Session Cookie: {e}")
    
    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """抓取頁面 HTML"""
        try:
            # 先嘗試使用快取的 cookies
            cached_cookies = self._load_session_cookies()
            if cached_cookies:
                self.session.cookies.update(cached_cookies)
            
            logger.info(f"正在抓取: {url}")
            response = self.session.get(url, timeout=30)
            
            # 檢查是否被導向登入頁或需要驗證
            if response.status_code == 200:
                # 如果有新的 cookies，儲存起來
                self._save_session_cookies(dict(self.session.cookies))
                
                # 檢查是否有 Cloudflare 或驗證頁面
                if self._is_challenge_page(response.text):
                    logger.warning("檢測到挑戰頁面 (Cloudflare)，可能需要等待或更換 IP")
                    return None
                    
                return BeautifulSoup(response.text, 'html.parser')
            else:
                logger.error(f"HTTP {response.status_code}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("請求超時")
        except requests.exceptions.RequestException as e:
            logger.error(f"請求失敗: {e}")
        return None
    
    def _is_challenge_page(self, html: str) -> bool:
        """檢查是否為挑戰頁面"""
        challenge_indicators = [
            "Checking your browser",
            "Cloudflare",
            "Access denied",
            "Just a moment",
            "checking your browser before accessing"
        ]
        html_lower = html.lower()
        return any(indicator.lower() in html_lower for indicator in challenge_indicators)
    
    def parse_ticket_areas(self, soup: BeautifulSoup) -> list[TicketArea]:
        """解析票種區域"""
        areas = []
        
        # TixCraft 通常用 table 或 div 結構展示票種
        # 這裡用常見的選擇器模式
        
        # 方式1: 找 table 結構
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    name_cell = cells[0]
                    status_cell = cells[-1]  # 最後一欄通常是狀態
                    
                    area_name = name_cell.get_text(strip=True)
                    status_text = status_cell.get_text(strip=True)
                    
                    # 解析狀態
                    status = "unknown"
                    if any(word in status_text.lower() for word in ['剩餘', 'available', '可購', '熱賣']):
                        status = "available"
                    elif any(word in status_text.lower() for word in ['售完', 'sold', 'soldout', '已售']):
                        status = "sold_out"
                    
                    if area_name and area_name not in ['票種', 'Zone', 'Area', '']:
                        areas.append(TicketArea(
                            name=area_name,
                            price="",
                            status=status
                        ))
        
        # 方式2: 找 div/card 結構 (備用)
        if not areas:
            area_cards = soup.find_all(['div', 'li'], class_=lambda x: x and any(
                keyword in str(x).lower() for keyword in ['area', 'zone', 'ticket', '票種']
            ))
            
            for card in area_cards:
                # 嘗試提取區域名稱
                name_elem = card.find(['span', 'div', 'h3', 'h4'])
                status_elem = card.find_all(['span', 'div', 'p'])
                
                if name_elem:
                    area_name = name_elem.get_text(strip=True)
                    # 取最後一個狀態相關的元素
                    status_text = status_elem[-1].get_text(strip=True) if status_elem else ""
                    
                    status = "unknown"
                    if any(word in status_text.lower() for word in ['剩餘', 'available', '可購']):
                        status = "available"
                    elif any(word in status_text.lower() for word in ['售完', 'sold', 'soldout']):
                        status = "sold_out"
                    
                    if area_name:
                        areas.append(TicketArea(
                            name=area_name,
                            price="",
                            status=status
                        ))
        
        return areas
    
    def get_event_name(self, soup: BeautifulSoup) -> str:
        """取得活動名稱"""
        # 常見的標題選擇器
        selectors = [
            'h1.event-title',
            'h1.title',
            '.event-name',
            'h1',
            '.activity-title'
        ]
        
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                return elem.get_text(strip=True)
        
        return "Unknown Event"
    
    def monitor(self) -> Optional[MonitorResult]:
        """執行一次監控"""
        url = self.config.tixcraft_activity_url
        if not url:
            logger.error("未設定 TIXCRAFT_ACTIVITY_URL")
            return None
        
        soup = self.fetch_page(url)
        if not soup:
            return None
        
        areas = self.parse_ticket_areas(soup)
        event_name = self.get_event_name(soup)
        
        has_available = any(area.status == "available" for area in areas)
        
        result = MonitorResult(
            url=url,
            timestamp=datetime.now().isoformat(),
            event_name=event_name,
            areas=areas,
            has_available=has_available
        )
        
        return result


# ===== Slack 通知 =====
class SlackNotifier:
    """Slack 通知器"""
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
    
    def send(self, result: MonitorResult, previous_result: Optional[MonitorResult] = None):
        """發送 Slack 通知"""
        if not self.webhook_url:
            logger.warning("未設定 Slack Webhook URL")
            return
        
        # 判斷是否需要通知
        if previous_result:
            # 比對狀態變化
            prev_available = previous_result.has_available
            curr_available = result.has_available
            
            if not self.config.notify_on_sold_out and prev_available and not curr_available:
                logger.info("票已售完，但關閉此通知")
                return
            if not self.config.notify_on_available and not prev_available and curr_available:
                logger.info("有票了，但關閉此通知")
                return
        
        # 構建訊息
        payload = self._build_payload(result, previous_result)
        
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                logger.info("Slack 通知已發送")
            else:
                logger.error(f"Slack 通知失敗: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Slack 通知失敗: {e}")
    
    def _build_payload(self, result: MonitorResult, previous_result: Optional[MonitorResult]) -> dict:
        """構建 Slack 訊息"""
        # Emoji 根據狀態
        if result.has_available:
            emoji = "🎉"
            title = f"{emoji} 有票了！"
            color = "#36a64f"  # 綠色
        else:
            emoji = "😢"
            title = f"{emoji} 票已售完"
            color = "#ff0000"  # 紅色
        
        # 構建區域詳情
        area_lines = []
        for area in result.areas[:10]:  # 最多顯示 10 個
            if area.status == "available":
                icon = "✅"
            elif area.status == "sold_out":
                icon = "❌"
            else:
                icon = "❓"
            area_lines.append(f"{icon} {area.name}")
        
        if len(result.areas) > 10:
            area_lines.append(f"...還有 {len(result.areas) - 10} 個區域")
        
        areas_text = "\n".join(area_lines) if area_lines else "無法取得區域資訊"
        
        payload = {
            "attachments": [
                {
                    "color": color,
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": title,
                                "emoji": True
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"*活動:*\n{result.event_name}"
                                },
                                {
                                    "type": "mrkdwn",
                                    "text": f"*時間:*\n{result.timestamp}"
                                }
                            ]
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*票種狀態:*\n```{areas_text}```"
                            }
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {
                                        "type": "plain_text",
                                        "text": "立即購票 🎫",
                                        "emoji": True
                                    },
                                    "url": result.url,
                                    "style": "primary"
                                }
                            ]
                        },
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"監控時間: {result.timestamp}"
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        
        return payload


# ===== 狀態快取 =====
STATE_FILE = ".last_state.json"

def load_last_state() -> Optional[dict]:
    """載入上次狀態"""
    if Path(STATE_FILE).exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_current_state(result: MonitorResult):
    """儲存當前狀態"""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"無法儲存狀態: {e}")


# ===== 主程式 =====
def main():
    logger.info("=" * 50)
    logger.info("TixCraft 票卷監控器啟動")
    logger.info("=" * 50)
    
    # 驗證必要設定
    if not config.slack_webhook_url:
        logger.error("錯誤: 請設定 SLACK_WEBHOOK_URL 環境變數")
        exit(1)
    
    if not config.tixcraft_activity_url:
        logger.error("錯誤: 請設定 TIXCRAFT_ACTIVITY_URL 環境變數")
        exit(1)
    
    # 建立監控器
    monitor = TixCraftMonitor(config)
    notifier = SlackNotifier(config.slack_webhook_url)
    
    # 執行監控
    result = monitor.monitor()
    
    if result:
        # 顯示結果
        logger.info(f"活動: {result.event_name}")
        logger.info(f"有票: {'是' if result.has_available else '否'}")
        logger.info(f"區域數: {len(result.areas)}")
        
        for area in result.areas:
            logger.info(f"  - {area.name}: {area.status}")
        
        # 載入上次狀態
        last_state = load_last_state()
        previous_result = None
        
        if last_state:
            logger.info("發現上次狀態，將比對變化...")
            previous_result = MonitorResult(
                url=last_state.get("url", ""),
                timestamp=last_state.get("timestamp", ""),
                event_name=last_state.get("event_name", ""),
                areas=[TicketArea(**a) for a in last_state.get("areas", [])],
                has_available=last_state.get("has_available", False)
            )
        
        # 發送通知 (如果有變化或是第一次)
        if result.has_available or not previous_result:
            notifier.send(result, previous_result)
        else:
            logger.info("狀態無變化，不發送通知")
        
        # 儲存當前狀態
        save_current_state(result)
    else:
        logger.error("監控失敗")
        exit(1)
    
    logger.info("監控完成")


if __name__ == "__main__":
    main()
