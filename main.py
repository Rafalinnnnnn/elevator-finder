import os
import time
import json
import asyncio
import httpx
from typing import List, Dict, Any, Optional, Tuple

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import pandas as pd
import requests

# Load environment
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    raise RuntimeError("Define GOOGLE_API_KEY en .env")

app = FastAPI(title="Elevator Distributor Finder", version="1.0.0")
templates = Jinja2Templates(directory="templates")

# Static curated synonyms for performance
QUERY_SYNONYMS = [
    # Español
    "distribuidores de ascensores", "ascensoristas",
    "proveedores de ascensores",
    # Inglés
    "elevator distributors", "lift distributors",
    # Accesibilidad
    "stairlift distributors", "wheelchair lift suppliers",
    # Singular & plural in key languages
    "ascensor", "ascensores",
    "elevator", "elevators",
    "ascenseur", "ascenseurs",
    "aufzug", "aufzüge",
    "ascensore", "ascensori",
    "elevador", "elevadores",
]

# Simple in-memory cache: area → (timestamp, results)
CACHE_TTL = 3600  # 1 hour
cache_store: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def scrape_site_details(url: str) -> Dict[str, Any]:
    info = {"email": None, "linkedin": None, "brands": [], "certifications": [], "company_type": None}
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # JSON-LD brands and founding
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    brand = data.get("brand")
                    items = []
                    if isinstance(brand, list):
                        items = brand
                    elif isinstance(brand, dict) and "name" in brand:
                        items = [brand["name"]]
                    elif isinstance(brand, str):
                        items = [brand]
                    info["brands"].extend(items)
                    if data.get("@type") == "Organization" and data.get("foundingDate"):
                        info["founding_date"] = data["foundingDate"]
            except:
                pass
        # Email & LinkedIn
        m = soup.select_one('a[href^="mailto:"]')
        if m:
            info["email"] = m["href"].split("mailto:")[1].split("?")[0]
        l = soup.select_one('a[href*="linkedin.com/company"]')
        if l:
            info["linkedin"] = l["href"]
        # Lists under headers
        for header in soup.find_all(["h2", "h3", "h4"]):
            title = header.get_text(strip=True).lower()
            ul = header.find_next_sibling("ul")
            if ul:
                items = [li.get_text(strip=True) for li in ul.find_all("li")]
                if "marca" in title:
                    info["brands"].extend(items)
                if "certific" in title:
                    info["certifications"].extend(items)
        # Company type heuristic
        text = soup.get_text(separator=" ").lower()
        if "fabricante" in text:
            info["company_type"] = "Fabricante + Distribuidor"
        elif "constructora" in text:
            info["company_type"] = "Constructora con instalación"
        else:
            info["company_type"] = "Distribuidor puro"
    except:
        pass
    # Deduplicate
    info["brands"] = list(dict.fromkeys([b for b in info["brands"] if isinstance(b, str)]))
    info["certifications"] = list(dict.fromkeys([c for c in info["certifications"] if isinstance(c, str)]))
    return info


async def get_elevator_distributors(area: str) -> List[Dict[str, Any]]:
    now = time.monotonic()
    # Serve from cache
    if area in cache_store:
        ts, data = cache_store[area]
        if now - ts < CACHE_TTL:
            return data
    seen_ids = set()
    prelim: List[Tuple[str, str, str]] = []

    async with httpx.AsyncClient(timeout=10) as client:
        # Text Search sequential due to pagination
        for base in QUERY_SYNONYMS:
            token: Optional[str] = None
            while True:
                params = {"query": f"{base} en {area}", "key": API_KEY, "language": "es"}
                if token:
                    params["pagetoken"] = token
                    await asyncio.sleep(2)
                resp = await client.get(
                    "https://maps.googleapis.com/maps/api/place/textsearch/json", params=params
                )
                resp.raise_for_status()
                page = resp.json()
                for p in page.get("results", []):
                    pid = p.get("place_id")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        prelim.append((pid, p.get("name"), p.get("formatted_address")))
                token = page.get("next_page_token")
                if not token:
                    break
        # Fetch details + scrape in parallel
        async def fetch(pid: str, name: str, addr: str) -> Dict[str, Any]:
            r = await client.get(
                "https://maps.googleapis.com/maps/api/place/details/json",
                params={"place_id": pid, "fields": "formatted_phone_number,website", "key": API_KEY}
            )
            r.raise_for_status()
            detail = r.json().get("result", {})
            phone = detail.get("formatted_phone_number")
            website = detail.get("website")
            extras = await asyncio.to_thread(scrape_site_details, website) if website else {}
            return {"company": name, "address": addr, "phone": phone, "website": website, **extras}

        tasks = [fetch(pid, nm, ad) for pid, nm, ad in prelim]
        results = await asyncio.gather(*tasks)

    # Cache and return
    cache_store[area] = (now, results)
    return results


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/results", response_class=HTMLResponse)
async def results(
    request: Request,
    area: str = Query(..., description="Ciudad, región o país"),
    brand: Optional[str] = Query(None),
    company_type: Optional[str] = Query(None),
    certification: Optional[str] = Query(None)
) -> HTMLResponse:
    a = normalize(area)
    provs = await get_elevator_distributors(a)
    all_brands = sorted({b for p in provs for b in p.get("brands", [])})
    all_types = sorted({p.get("company_type") for p in provs})
    all_certs = sorted({c for p in provs for c in p.get("certifications", [])})
    filtered = [
        p for p in provs
        if (not brand or brand in p.get("brands", []))
        and (not company_type or p.get("company_type") == company_type)
        and (not certification or certification in p.get("certifications", []))
    ]
    return templates.TemplateResponse("index.html", {
        "request": request,
        "results": filtered,
        "area": a,
        "all_brands": all_brands,
        "all_types": all_types,
        "all_certs": all_certs,
        "selected_brand": brand or "",
        "selected_type": company_type or "",
        "selected_cert": certification or ""
    })


@app.get("/export")
async def export(
    area: str = Query(...),
    brand: Optional[str] = Query(None),
    company_type: Optional[str] = Query(None),
    certification: Optional[str] = Query(None)
) -> FileResponse:
    a = normalize(area)
    provs = await get_elevator_distributors(a)
    filtered = [
        p for p in provs
        if (not brand or brand in p.get("brands", []))
        and (not company_type or p.get("company_type") == company_type)
        and (not certification or certification in p.get("certifications", []))
    ]
    df = pd.DataFrame(filtered)
    df.rename(columns={
        "company": "Empresa", "address": "Dirección", "brands": "Marcas",
        "certifications": "Certificaciones", "company_type": "TipoEmpresa",
        "email": "Email", "phone": "Teléfono", "linkedin": "LinkedIn",
        "website": "Website"
    }, inplace=True)
    fname = f"distribuidores_{a}.xlsx".replace(" ", "_")
    df.to_excel(fname, index=False)
    return FileResponse(
        fname,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=fname
    )


# JSON endpoint for Swagger
@app.get("/api/results", summary="Buscar distribuidores (JSON)")
async def api_results(
    area: str = Query(..., description="Ciudad, región o país")
) -> List[Dict[str, Any]]:
    """
    Devuelve JSON puro de distribuidores para integraciones.
    """
    a = normalize(area)
    return await get_elevator_distributors(a)
