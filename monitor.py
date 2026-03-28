#!/usr/bin/env python3
"""
TixCraft 票卷監控器 v2
- 增加瀏覽器偽裝
- 增加重試機制
- 更好的錯誤處理
"""

import os
import json
import time
import random
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
    slack_webhook_url: str
    tixcraft_activity_url: str
    notify_on_available: bool = True
    notify_on_sold_out: bool = True
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

config = Config(
    slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL", ""),
    tixcraft_activity_url=os.environ.get("TIXCRAFT_ACTIVITY_URL", ""),
)

# ===== 日誌設定 =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


# ===== 票種資料結構 =====
@dataclass
class TicketArea:
    name: str
    price: str
    status: str
    remaining: Optional[int] = None

@dataclass
class MonitorResult:
    url: str
    timestamp: str
    event_name: str
    areas: list
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
    BASE_URL = "https://tixcraft.com"
    
    def __init__(self, config: Config):
        self.config = config
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        session = requests.Session()
        
        # 偽裝成真實瀏覽器
        session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        })
        return session
    
    def _random_delay(self):
        """隨機延遲，模擬人類"""
        delay = random.uniform(1, 3)
        time.sleep(delay)
    
    def fetch_page(self, url: str, retry: int = 3) -> Optional[BeautifulSoup]:
        """抓取頁面 HTML，帶重試"""
        
        for attempt in range(retry):
            try:
                self._random_delay()
                logger.info(f"正在抓取 (嘗試 {attempt + 1}/{retry}): {url}")
                
                response = self.session.get(url, timeout=30)
                
                if response.status_code == 200:
                    # 檢查是否為挑戰頁面
                    if self._is_challenge_page(response.text):
                        logger.warning("檢測到驗證頁面，等待後重試...")
                        time.sleep(10)
                        continue
                    
                    logger.info(f"抓取成功，頁面大小: {len(response.text)} bytes")
                    return BeautifulSoup(response.text, 'lxml')
                    
                elif response.status_code == 403:
                    logger.warning(f"403 拒絕訪問 (嘗試 {attempt + 1}/{retry})")
                    time.sleep(5)
                    
                elif response.status_code == 429:
                    logger.warning(f"429 请求过多，等待 60 秒...")
                    time.sleep(60)
                    
                else:
                    logger.error(f"HTTP {response.status_code}")
                    
            except requests.exceptions.Timeout:
                logger.warning("請求超時")
            except requests.exceptions.RequestException as e:
                logger.error(f"請求失敗: {e}")
        
        return None
    
    def _is_challenge_page(self, html: str) -> bool:
        indicators = [
            "checking your browser",
            "cloudflare",
            "access denied",
            "just a moment",
            "ray id",
            "attention required",
            "sorry, you have been blocked"
        ]
        html_lower = html.lower()
        return any(ind in html_lower for ind in indicators)
    
    def parse_ticket_areas(self, soup: BeautifulSoup) -> list[TicketArea]:
        """解析票種區域"""
        areas = []
        
        # 嘗試多種選擇器
        selectors = [
            # Table 結構
            ('table', 'ticket'),
            ('table', 'area'),
            # Div 結構
            ('div', 'ticket-item'),
            ('div', 'area-item'),
            ('div', 'product'),
            # List 結構
            ('li', 'ticket'),
            ('li', 'area'),
        ]
        
        for tag, classname in selectors:
            elements = soup.find_all(tag, class_=lambda x: x and classname in str(x).lower())
            if elements:
                logger.info(f"找到 {len(elements)} 個票種元素 (tag={tag}, class~={classname})")
                
                for elem in elements:
                    name = ""
                    price = ""
                    status = "unknown"
                    
                    # 嘗試提取名稱
                    for name_tag in ['span', 'div', 'h3', 'h4', 'p']:
                        name_elem = elem.find(name_tag)
                        if name_elem:
                            name = name_elem.get_text(strip=True)
                            if name and len(name) < 100:
                                break
                    
                    # 嘗試提取價格
                    price_elem = elem.find(class_=lambda x: x and 'price' in str(x).lower())
                    if price_elem:
                        price = price_elem.get_text(strip=True)
                    
                    # 嘗試提取狀態
                    text = elem.get_text(strip=True).lower()
                    if any(w in text for w in ['剩餘', 'available', '可購', '熱賣', '預售']):
                        status = "available"
                    elif any(w in text for w in ['售完', 'sold out', 'soldout', '已售', '完售']):
                        status = "sold_out"
                    
                    if name and name not in areas:
                        areas.append(TicketArea(name=name, price=price, status=status))
                
                if areas:
                    break
        
        # 如果都找不到，嘗試從整個頁面文字分析
        if not areas:
            logger.info("使用文字掃描方式解析...")
            text = soup.get_text()
            
            # 簡單的關鍵字掃描
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if not line or len(line) > 100:
                    continue
                    
                if any(w in line for w in ['區', '區剩餘', '票種']):
                    status = "unknown"
                    if any(w in line for w in ['剩餘', '可購']):
                        status = "available"
                    elif any(w in line for w in ['售完', '已售']):
                        status = "sold_out"
                    
                    if status != "unknown":
                        areas.append(TicketArea(name=line[:50], price="", status=status))
        
        return areas[:20]  # 最多 20 個
    
    def get_event_name(self, soup: BeautifulSoup) -> str:
        for selector in ['h1', '.event-title', '.title', '.activity-title']:
            elem = soup.select_one(selector)
            if elem:
                name = elem.get_text(strip=True)
                if name and len(name) < 200:
                    return name
        return "Unknown Event"
    
    def monitor(self) -> Optional[MonitorResult]:
        url = self.config.tixcraft_activity_url
        if not url:
            logger.error("未設定 TIXCRAFT_ACTIVITY_URL")
            return None
        
        soup = self.fetch_page(url)
        if not soup:
            logger.error("無法抓取頁面")
            return None
        
        areas = self.parse_ticket_areas(soup)
        event_name = self.get_event_name(soup)
        has_available = any(area.status == "available" for area in areas)
        
        return MonitorResult(
            url=url,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            event_name=event_name,
            areas=areas,
            has_available=has_available
        )


# ===== Slack 通知 =====
class SlackNotifier:
    def __init__(self, webhook_url: str, config: Config):
        self.webhook_url = webhook_url
        self.config = config
    
    def send(self, result: MonitorResult):
        if not self.webhook_url:
            logger.warning("未設定 Slack Webhook URL")
            return
        
        payload = self._build_payload(result)
        
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=15,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                logger.info("Slack 通知已發送 ✅")
            else:
                logger.error(f"Slack 通知失敗: {response.status_code} - {response.text}")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Slack 通知失敗: {e}")
    
    def _build_payload(self, result: MonitorResult) -> dict:
        if result.has_available:
            emoji = "🎉"
            title = f"{emoji} 有票了！"
            color = "#36a64f"
        else:
            emoji = "😢"
            title = f"{emoji} 票已售完"
            color = "#ff4444"
        
        area_lines = []
        for area in result.areas[:8]:
            icon = "✅" if area.status == "available" else "❌" if area.status == "sold_out" else "❓"
            area_lines.append(f"{icon} {area.name}")
        
        if len(result.areas) > 8:
            area_lines.append(f"...還有 {len(result.areas) - 8} 個區域")
        
        areas_text = "\n".join(area_lines) if area_lines else "無法取得票種資訊"
        
        return {
            "attachments": [{
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": title, "emoji": True}
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*活動:*\n{result.event_name}"},
                            {"type": "mrkdwn", "text": f"*時間:*\n{result.timestamp}"}
                        ]
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*票種狀態:*\n```{areas_text}```"}
                    },
                    {
                        "type": "actions",
                        "elements": [{
                            "type": "button",
                            "text": {"type": "plain_text", "text": "立即購票 🎫"},
                            "url": result.url,
                            "style": "primary"
                        }]
                    }
                ]
            }]
        }


# ===== 主程式 =====
def main():
    logger.info("=" * 40)
    logger.info("TixCraft 票卷監控器")
    logger.info("=" * 40)
    
    if not config.slack_webhook_url:
        logger.error("錯誤: 請設定 SLACK_WEBHOOK_URL")
        exit(1)
    
    if not config.tixcraft_activity_url:
        logger.error("錯誤: 請設定 TIXCRAFT_ACTIVITY_URL")
        exit(1)
    
    logger.info(f"監控目標: {config.tixcraft_activity_url}")
    
    monitor = TixCraftMonitor(config)
    notifier = SlackNotifier(config.slack_webhook_url, config)
    
    result = monitor.monitor()
    
    if result:
        logger.info(f"活動: {result.event_name}")
        logger.info(f"有票: {'是 ✅' if result.has_available else '否 ❌'}")
        logger.info(f"找到 {len(result.areas)} 個票種")
        
        for area in result.areas:
            status_icon = "✅" if area.status == "available" else "❌" if area.status == "sold_out" else "❓"
            logger.info(f"  {status_icon} {area.name}")
        
        # 發送 Slack 通知
        notifier.send(result)
        
    else:
        logger.error("監控失敗")
        exit(1)
    
    logger.info("完成 ✅")


if __name__ == "__main__":
    main()
