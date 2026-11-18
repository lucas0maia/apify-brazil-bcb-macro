"""Apify Actor & Standby MCP Server for Banco Central do Brasil (BCB) APIs."""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import urllib.parse
import urllib.request
from typing import Any, Callable

try:
    from aiohttp import web
    from apify import Actor
except ImportError:  # Allows running pure client functions & tests without Apify SDK installed
    web = None  # type: ignore[assignment]
    Actor = None  # type: ignore[assignment]

EVENT_NAME = "record-delivered"

SGS_SERIES_NAMES: dict[int, str] = {
    12: "CDI Daily (% p.d.)",
    189: "IGP-M Monthly (%)",
    432: "Selic Target Rate (% p.a.)",
    433: "IPCA Monthly (%)",
    21082: "Credit Delinquency Total (%)",
    24369: "PNAD Unemployment Rate (%)",
}

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_brazil_central_bank",
        "description": (
            "Query official Banco Central do Brasil (BCB) data: SGS time series "
            "(Selic, CDI, IPCA, IGP-M), Focus Market Expectations, bank lending "
            "interest rates, and PTAX FX buy/sell rates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": [
                        "focus_expectations",
                        "sgs_series",
                        "bank_interest_rates",
                        "ptax_fx",
                    ],
                },
                "sgsCode": {"type": "integer", "default": 432},
                "lastN": {"type": "integer", "default": 20},
                "indicator": {"type": "string", "default": ""},
                "currency": {"type": "string", "default": "USD"},
                "startDate": {"type": "string", "default": ""},
                "endDate": {"type": "string", "default": ""},
                "query": {"type": "string", "default": ""},
                "maxResults": {"type": "integer", "default": 50},
                "timeoutSecs": {"type": "integer", "default": 30},
            },
            "required": ["mode"],
        },
    }
]


def http_get_json(url: str, timeout: int = 30) -> Any:
    """Perform a standard HTTP GET request and decode a JSON payload."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "brasil-api-lcm/apify-brazil-bcb-macro/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).replace(",", ".").strip())


def _br_date_to_iso(date_str: str) -> str:
    clean = (date_str or "").strip()
    if len(clean) == 10 and clean[2] == "/" and clean[5] == "/":
        dd, mm, yyyy = clean.split("/")
        return f"{yyyy}-{mm}-{dd}"
    return clean[:10]


def _normalize_ptax_date(date_str: str, fallback_days_ago: int = 0) -> str:
    clean = (date_str or "").strip()
    if not clean:
        target = datetime.date.today() - datetime.timedelta(days=fallback_days_ago)
        return target.strftime("%m-%d-%Y")
    # Convert YYYY-MM-DD to MM-DD-YYYY required by BCB PTAX OData
    if len(clean) == 10 and clean[4] == "-" and clean[7] == "-":
        yyyy, mm, dd = clean.split("-")
        return f"{mm}-{dd}-{yyyy}"
    # Convert DD/MM/YYYY to MM-DD-YYYY
    if len(clean) == 10 and clean[2] == "/" and clean[5] == "/":
        dd, mm, yyyy = clean.split("/")
        return f"{mm}-{dd}-{yyyy}"
    return clean


def _normalize_sgs_rows(
    raw_rows: list[dict[str, Any]],
    sgs_code: int,
    source_url: str,
) -> list[dict[str, Any]]:
    series_name = SGS_SERIES_NAMES.get(sgs_code, f"SGS Series {sgs_code}")
    parsed: list[dict[str, Any]] = []
    for row in raw_rows:
        iso_date = _br_date_to_iso(str(row.get("data", "")))
        val = _safe_float(row.get("valor"))
        parsed.append({"isoDate": iso_date, "rawDate": row.get("data", ""), "value": val})

    parsed.sort(key=lambda item: item["isoDate"])
    results: list[dict[str, Any]] = []
    prev_val: float | None = None
    for item in parsed:
        val = item["value"]
        change_abs = round(val - prev_val, 6) if prev_val is not None else 0.0
        change_pct = (
            round(((val - prev_val) / prev_val) * 100.0, 4)
            if prev_val not in (None, 0.0)
            else 0.0
        )
        results.append(
            {
                "recordType": "sgs_series",
                "sgsCode": sgs_code,
                "seriesName": series_name,
                "referenceDate": item["isoDate"],
                "metric": f"SGS-{sgs_code}",
                "entityOrModality": series_name,
                "valuePrimary": val,
                "valueSecondary": prev_val if prev_val is not None else val,
                "spreadBpsOrChange": change_abs,
                "changePct": change_pct,
                "sourceUrl": source_url,
            }
        )
        prev_val = val

    results.reverse()
    return results


def fetch_sgs_series(
    sgs_code: int = 432,
    last_n: int = 20,
    timeout: int = 30,
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Fetch and normalize BCB SGS macroeconomic time series."""
    count = max(1, min(int(last_n), 500))
    code = int(sgs_code)
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados/ultimos/{count}?formato=json"
    payload = fetcher(url, timeout)
    if not isinstance(payload, list):
        return []
    return _normalize_sgs_rows(payload, code, url)


def fetch_focus_expectations(
    indicator: str = "",
    max_results: int = 50,
    timeout: int = 30,
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Fetch and normalize BCB Focus Market Expectations."""
    cap = max(1, min(int(max_results), 1000))
    needle = (indicator or "").strip()
    top = cap if not needle else max(cap * 4, 250)
    url = (
        "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
        f"ExpectativasMercadoAnuais?$top={top}&$orderby=Data%20desc&$format=json"
    )
    payload = fetcher(url, timeout)
    raw_rows = payload.get("value", []) if isinstance(payload, dict) else []
    needle_low = needle.lower()

    results: list[dict[str, Any]] = []
    for row in raw_rows:
        ind = str(row.get("Indicador") or "")
        detail = str(row.get("IndicadorDetalhe") or "")
        if needle_low and needle_low not in ind.lower() and needle_low not in detail.lower():
            continue
        mean_val = _safe_float(row.get("Media"))
        median_val = _safe_float(row.get("Mediana"))
        std_val = _safe_float(row.get("DesvioPadrao"))
        results.append(
            {
                "recordType": "focus_expectations",
                "indicator": ind,
                "indicatorDetail": detail,
                "referenceDate": f"{row.get('Data', '')} (Ref {row.get('DataReferencia', '')})",
                "reportDate": str(row.get("Data", "")),
                "targetYear": str(row.get("DataReferencia", "")),
                "metric": ind,
                "entityOrModality": detail or f"Forecast {row.get('DataReferencia', '')}",
                "valuePrimary": median_val,
                "valueSecondary": mean_val,
                "spreadBpsOrChange": std_val,
                "min": _safe_float(row.get("Minimo")),
                "max": _safe_float(row.get("Maximo")),
                "respondents": int(row.get("numeroRespondentes") or 0),
                "sourceUrl": url,
            }
        )
        if len(results) >= cap:
            break
    return results


def fetch_bank_interest_rates(
    query: str = "",
    max_results: int = 50,
    timeout: int = 30,
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Fetch and normalize BCB bank credit interest rates by institution and modality."""
    cap = max(1, min(int(max_results), 1000))
    needle = (query or "").strip().lower()
    top = cap if not needle else min(max(cap * 8, 400), 2000)
    url = (
        "https://olinda.bcb.gov.br/olinda/servico/taxaJuros/versao/v2/odata/"
        f"TaxasJurosMensalPorMes?$top={top}&$format=json"
    )
    payload = fetcher(url, timeout)
    raw_rows = payload.get("value", []) if isinstance(payload, dict) else []

    results: list[dict[str, Any]] = []
    for row in raw_rows:
        bank = str(row.get("InstituicaoFinanceira") or "")
        modality = str(row.get("Modalidade") or "")
        if needle and needle not in bank.lower() and needle not in modality.lower():
            continue
        monthly_rate = _safe_float(row.get("TaxaJurosAoMes"))
        annual_rate = _safe_float(row.get("TaxaJurosAoAno"))
        results.append(
            {
                "recordType": "bank_interest_rates",
                "referenceDate": str(row.get("anoMes") or row.get("Mes") or ""),
                "monthLabel": str(row.get("Mes") or ""),
                "metric": f"Rank #{row.get('Posicao', '')} · {bank}",
                "institution": bank,
                "cnpj8": str(row.get("cnpj8") or ""),
                "modality": modality,
                "position": int(row.get("Posicao") or 0),
                "entityOrModality": modality,
                "valuePrimary": annual_rate,
                "valueSecondary": monthly_rate,
                "spreadBpsOrChange": round(annual_rate - (monthly_rate * 12.0), 4),
                "sourceUrl": url,
            }
        )
        if len(results) >= cap:
            break
    return results


def fetch_ptax_fx(
    currency: str = "USD",
    start_date: str = "",
    end_date: str = "",
    max_results: int = 50,
    timeout: int = 30,
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Fetch BCB PTAX FX rates and compute buy/sell spreads in absolute terms and bps."""
    cap = max(1, min(int(max_results), 1000))
    curr = (currency or "USD").strip().upper() or "USD"
    s_date = _normalize_ptax_date(start_date, fallback_days_ago=15)
    e_date = _normalize_ptax_date(end_date, fallback_days_ago=0)

    url = (
        "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
        "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
        f"?@moeda=%27{urllib.parse.quote(curr)}%27"
        f"&@dataInicial=%27{urllib.parse.quote(s_date)}%27"
        f"&@dataFinalCotacao=%27{urllib.parse.quote(e_date)}%27"
        f"&$top={cap}&$orderby=dataHoraCotacao%20desc&$format=json"
    )
    payload = fetcher(url, timeout)
    raw_rows = payload.get("value", []) if isinstance(payload, dict) else []

    results: list[dict[str, Any]] = []
    for row in raw_rows:
        buy = _safe_float(row.get("cotacaoCompra"))
        sell = _safe_float(row.get("cotacaoVenda"))
        spread_abs = round(sell - buy, 6)
        spread_bps = round((spread_abs / buy) * 10000.0, 2) if buy > 0 else 0.0
        ts = str(row.get("dataHoraCotacao") or "")
        bulletin = str(row.get("tipoBoletim") or "")
        results.append(
            {
                "recordType": "ptax_fx",
                "currency": curr,
                "referenceDate": ts[:19],
                "metric": f"{curr}/BRL PTAX",
                "entityOrModality": bulletin,
                "bulletinType": bulletin,
                "buyRate": buy,
                "sellRate": sell,
                "valuePrimary": sell,
                "valueSecondary": buy,
                "spreadAbs": spread_abs,
                "spreadBpsOrChange": spread_bps,
                "parityBuy": _safe_float(row.get("paridadeCompra")),
                "paritySell": _safe_float(row.get("paridadeVenda")),
                "sourceUrl": url,
            }
        )
    return results[:cap]


def run_query(
    params: dict[str, Any],
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Route an Actor input or MCP tool call to the corresponding BCB mode."""
    mode = str(params.get("mode") or "focus_expectations").strip().lower()
    timeout = max(5, min(int(params.get("timeoutSecs") or 30), 60))
    max_results = int(params.get("maxResults") or 50)

    if mode == "sgs_series":
        return fetch_sgs_series(
            sgs_code=int(params.get("sgsCode") or 432),
            last_n=int(params.get("lastN") or min(max_results, 20)),
            timeout=timeout,
            fetcher=fetcher,
        )
    if mode == "focus_expectations":
        indicator = str(params.get("indicator") or params.get("query") or "")
        return fetch_focus_expectations(
            indicator=indicator,
            max_results=max_results,
            timeout=timeout,
            fetcher=fetcher,
        )
    if mode == "bank_interest_rates":
        return fetch_bank_interest_rates(
            query=str(params.get("query") or ""),
            max_results=max_results,
            timeout=timeout,
            fetcher=fetcher,
        )
    if mode == "ptax_fx":
        return fetch_ptax_fx(
            currency=str(params.get("currency") or "USD"),
            start_date=str(params.get("startDate") or ""),
            end_date=str(params.get("endDate") or ""),
            max_results=max_results,
            timeout=timeout,
            fetcher=fetcher,
        )
    raise ValueError(f"Unsupported mode: {mode}")


async def _charge_records(count: int) -> int:
    if count <= 0:
        return 0
    max_items_env = os.environ.get("ACTOR_MAX_PAID_DATASET_ITEMS")
    allowed = count
    if max_items_env and max_items_env.isdigit():
        allowed = min(count, int(max_items_env))
    if allowed <= 0:
        return 0
    try:
        res = await Actor.charge(event_name=EVENT_NAME, count=allowed)
        if hasattr(res, "event_charge_limit_reached") and res.event_charge_limit_reached:
            Actor.log.warning("Pay-per-event limit reached on %s.", EVENT_NAME)
    except Exception as exc:
        Actor.log.warning("Charge skipped in local/non-monetized mode: %s", exc)
    return allowed


async def _handle_mcp_rpc(payload: dict[str, Any]) -> dict[str, Any]:
    rpc_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "apify-brazil-bcb-macro", "version": "0.0.1"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": MCP_TOOLS}}
    if method == "tools/call":
        if params.get("name") != "query_brazil_central_bank":
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Unknown tool"}}
        args = params.get("arguments") or {}
        rows = await asyncio.to_thread(run_query, args)
        await _charge_records(len(rows))
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"content": [{"type": "text", "text": json.dumps(rows, ensure_ascii=False)}]},
        }
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": f"Unsupported method: {method}"}}


async def _run_standby_server() -> None:
    port = int(os.environ.get("ACTOR_STANDBY_PORT", "8080"))

    async def handle_health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "actor": "apify-brazil-bcb-macro"})

    async def handle_root(request: web.Request) -> web.Response:
        if request.headers.get("x-apify-container-server-readiness-probe"):
            return web.Response(text="OK", status=200)
        args = {
            "mode": request.query.get("mode", "focus_expectations"),
            "sgsCode": int(request.query.get("sgsCode", "432")),
            "lastN": int(request.query.get("lastN", "20")),
            "indicator": request.query.get("indicator", ""),
            "currency": request.query.get("currency", "USD"),
            "startDate": request.query.get("startDate", ""),
            "endDate": request.query.get("endDate", ""),
            "query": request.query.get("query", ""),
            "maxResults": int(request.query.get("maxResults", "50")),
        }
        rows = await asyncio.to_thread(run_query, args)
        await _charge_records(len(rows))
        return web.json_response({"count": len(rows), "items": rows})

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        if isinstance(payload, dict) and payload.get("jsonrpc") == "2.0":
            return web.json_response(await _handle_mcp_rpc(payload))
        rows = await asyncio.to_thread(run_query, payload if isinstance(payload, dict) else {})
        await _charge_records(len(rows))
        return web.json_response({"count": len(rows), "items": rows})

    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get("/", handle_root)
    app.router.add_post("/", handle_post)
    app.router.add_post("/mcp", handle_post)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    Actor.log.info("Brazil Central Bank (BCB) Standby HTTP/MCP server listening on port %s", port)
    await asyncio.Event().wait()


async def main() -> None:
    if Actor is None:
        raise RuntimeError("apify package is required to run Actor.main()")
    async with Actor:
        if os.environ.get("APIFY_META_ORIGIN") == "STANDBY":
            await _run_standby_server()
            return
        actor_input = await Actor.get_input() or {}
        rows = await asyncio.to_thread(run_query, actor_input)
        allowed = await _charge_records(len(rows))
        to_push = rows[:allowed] if allowed else []
        if to_push:
            await Actor.push_data(to_push)
        Actor.log.info("Delivered %d BCB records.", len(to_push))


if __name__ == "__main__":
    asyncio.run(main())
