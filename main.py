"""
롯데마트 전 지점 재고 조회 - 웹 서버 (FastAPI)
"""

import asyncio
import json
import os
import re
from typing import List

import aiohttp
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ============================================================
# 설정
# ============================================================
BASE_URL = "https://company.lottemart.com/mobiledowa"
AREAS = ["서울", "경기", "인천", "강원", "충북", "충남", "대전",
         "경북", "경남", "대구", "부산", "울산", "전북", "전남", "광주", "기타"]

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")

CONCURRENCY = 15
REQUEST_TIMEOUT = 15

STORE_CACHE_FILE = "lotte_stores_cache.json"


# ============================================================
# 매장 목록 (앱 시작 시 한 번 로드, 메모리에 보관)
# ============================================================
STORES = []


def fetch_all_stores():
    """전국 매장 목록을 사이트에서 긁어와 리스트로 반환"""
    stores = []
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": f"{BASE_URL}/index.asp",
    })
    sess.get(f"{BASE_URL}/index.asp", timeout=REQUEST_TIMEOUT)

    for area in AREAS:
        try:
            r = sess.get(
                f"{BASE_URL}/inc/asp/search_market_list.asp",
                params={"p_area": area, "p_werks": "", "p_type": "1"},
                timeout=REQUEST_TIMEOUT,
            )
            r.encoding = "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            for opt in soup.select("option"):
                code = (opt.get("value") or "").strip()
                name = opt.text.strip()
                if code and name and name != "매장선택":
                    stores.append({"area": area, "code": code, "name": name})
        except Exception as e:
            print(f"[경고] {area} 매장 목록 수집 실패: {e}")

    return stores


def load_stores():
    """캐시가 있으면 캐시에서, 없으면 새로 받아와서 저장"""
    if os.path.exists(STORE_CACHE_FILE):
        try:
            with open(STORE_CACHE_FILE, "r", encoding="utf-8") as f:
                stores = json.load(f)
                if stores:
                    return stores
        except Exception:
            pass

    print("매장 목록을 처음 받아오는 중...")
    stores = fetch_all_stores()
    if stores:
        with open(STORE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(stores, f, ensure_ascii=False, indent=2)
    return stores


# ============================================================
# 검색 (한 매장)
# ============================================================
async def search_one_store(session, store, keyword, sem):
    async with sem:
        data = {
            "p_area": store["area"],
            "p_market": store["code"],
            "p_schWord": keyword,
        }
        try:
            async with session.post(
                f"{BASE_URL}/product/search_product.asp",
                data=data,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as r:
                html = await r.text(encoding="utf-8", errors="ignore")
        except Exception:
            return []

        return parse_search_result(html, store)


def parse_search_result(html, store):
    soup = BeautifulSoup(html, "html.parser")
    products = []

    for li in soup.select("ul.list-result > li"):
        name_el = li.select_one(".prod-name")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)

        count_div = li.select_one(".prod-count")
        barcode = ""
        if count_div:
            m = re.search(r"<!--\s*(\d+)\s*-->", str(count_div))
            if m:
                barcode = m.group(1)

        stock = "-"
        price = "-"
        for tr in li.select(".layer_popup table tr"):
            th = tr.select_one("th")
            td = tr.select_one("td")
            if not th or not td:
                continue
            th_text = th.get_text(strip=True)
            td_text = td.get_text(strip=True)
            if "재고" in th_text:
                stock = td_text
            elif "가격" in th_text:
                price = td_text

        # 재고 분류
        stock_label, stock_num = classify_stock(stock)

        products.append({
            "area": store["area"],
            "store": store["name"],
            "store_code": store["code"],
            "name": name,
            "barcode": barcode,
            "price": price,
            "stock": stock,
            "stock_label": stock_label,
            "stock_num": stock_num,
        })
    return products


def classify_stock(stock_str):
    s = stock_str.strip()
    if not s or s == "-":
        return ("정보없음", -1)
    m = re.search(r"\d+", s)
    if m:
        n = int(m.group())
        if n > 0:
            return ("재고있음", n)
        return ("품절", 0)
    if "품절" in s or "없" in s:
        return ("품절", 0)
    if "있" in s or "충분" in s or "보유" in s:
        return ("재고있음", 999)
    return ("기타", -1)


# ============================================================
# 전 매장 병렬 검색
# ============================================================
async def search_all_stores_async(keyword: str, stores: list):
    sem = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=CONCURRENCY)

    headers = {
        "User-Agent": USER_AGENT,
        "Referer": f"{BASE_URL}/index.asp",
        "Origin": BASE_URL.replace("/mobiledowa", ""),
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        try:
            async with session.get(f"{BASE_URL}/index.asp",
                                   timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)):
                pass
        except Exception:
            pass

        tasks = [search_one_store(session, s, keyword, sem) for s in stores]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = []
        for r in results:
            if isinstance(r, list):
                all_results.extend(r)

    return all_results


# ============================================================
# FastAPI 앱
# ============================================================
app = FastAPI(title="롯데마트 재고조회")


@app.on_event("startup")
async def startup():
    global STORES
    print("매장 목록 로드 중...")
    # 캐시 파일이 있으면 우선 사용 (서버가 롯데마트 못 찌를 수 있어서)
    if os.path.exists(STORE_CACHE_FILE):
        try:
            with open(STORE_CACHE_FILE, "r", encoding="utf-8") as f:
                STORES = json.load(f)
                print(f"매장 목록 캐시에서 로드 완료: {len(STORES)}개")
                return
        except Exception as e:
            print(f"캐시 로드 실패: {e}")

    # 캐시 없으면 받아오기 시도 (실패해도 앱 죽지 않음)
    try:
        STORES = fetch_all_stores()
        print(f"매장 목록 신규 수집 완료: {len(STORES)}개")
    except Exception as e:
        print(f"매장 목록 수집 실패: {e}")
        STORES = []


class SearchRequest(BaseModel):
    keyword: str


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/stores")
async def get_stores():
    """매장 목록 반환"""
    return {"count": len(STORES), "stores": STORES}


@app.post("/api/search")
async def search(req: SearchRequest):
    """전 매장 재고 검색"""
    keyword = req.keyword.strip()
    if len(keyword) < 2:
        raise HTTPException(status_code=400, detail="검색어는 2글자 이상 입력해주세요.")

    if not STORES:
        raise HTTPException(status_code=503, detail="매장 목록이 아직 준비되지 않았습니다.")

    results = await search_all_stores_async(keyword, STORES)

    # 상품별로 그룹화
    grouped = {}
    for r in results:
        key = r["name"]
        if key not in grouped:
            grouped[key] = {
                "name": r["name"],
                "barcode": r["barcode"],
                "price": r["price"],
                "stores": [],
            }
        grouped[key]["stores"].append({
            "area": r["area"],
            "store": r["store"],
            "stock": r["stock"],
            "stock_label": r["stock_label"],
            "stock_num": r["stock_num"],
        })

    # 정렬: 재고있는 매장이 많은 상품 먼저
    products = list(grouped.values())
    for p in products:
        # 매장 정렬: 재고있음 → 품절
        p["stores"].sort(key=lambda s: -s["stock_num"])
        p["in_stock_count"] = sum(1 for s in p["stores"] if s["stock_label"] == "재고있음")
        p["total_count"] = len(p["stores"])

    products.sort(key=lambda p: (-p["in_stock_count"], p["name"]))

    return {
        "keyword": keyword,
        "total_products": len(products),
        "total_results": len(results),
        "products": products,
    }


# 정적 파일
app.mount("/static", StaticFiles(directory="static"), name="static")
