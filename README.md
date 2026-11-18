# Brazil Central Bank (BCB) — Selic, PTAX, Focus & Bank Rates (`apify-brazil-bcb-macro`)

Extract structured Brazilian macroeconomic indicators, consensus market expectations, FX reference rates, and commercial bank lending interest rates directly from the official **Banco Central do Brasil (BCB)** JSON and Olinda OData APIs — with zero residential proxies and zero external API keys.

## Why Use This Actor?

Designed for **quantitative funds, fintech credit desks, corporate treasuries, ERP/BI pipelines, and AI agents (Claude Code, Cursor, Codex CLI)** needing auditable official Brazilian monetary data:

- **`focus_expectations`:** Weekly BCB **Relatório Focus** market consensus expectations (`Mean`, `Median`, `StdDev`, `Min`, `Max`, `Respondents`) for IPCA, Selic, GDP (`PIB Total`), BRL/USD exchange rate (`Câmbio`), IGP-M, and Fiscal Balance across forecast years.
- **`sgs_series`:** Official **SGS Time Series** (`api.bcb.gov.br`), pre-mapped for **Selic Meta (`432`)**, **CDI (`12`)**, **IPCA (`433`)**, **IGP-M (`189`)**, **Unemployment (`24369`)**, and **Credit Delinquency (`21082`)** — including ISO date normalization and period-over-period delta calculation.
- **`bank_interest_rates`:** Monthly & annual lending interest rates charged by individual Brazilian banks (`Taxas de Juros - Olinda v2`) across modalities (Payroll Loans, Working Capital, Credit Card Revolving, Overdraft, Auto & Mortgage Financing).
- **`ptax_fx`:** Official **PTAX FX Rates** (`USD`, `EUR`, `GBP`, `JPY`, `CHF`, etc.) across intraday and closing bulletins (`Abertura`, `Intermediário`, `Fechamento`) with automated buy/sell spread calculation (`spreadAbs` and `spreadBps`).

## Example Input

```json
{
  "mode": "focus_expectations",
  "indicator": "IPCA",
  "maxResults": 20
}
```

```json
{
  "mode": "ptax_fx",
  "currency": "USD",
  "maxResults": 10
}
```

## MCP & Standby Ready

Connect directly via Apify Standby HTTP (`GET /`, `GET /health`, `POST /`) or **MCP JSON-RPC 2.0** (`POST /mcp`, tool name `query_brazil_central_bank`).
