// Fortress 2026 — Cloudflare Worker
// Uses Yahoo Finance (no API key required)
// LSE ETFs: .L suffix, prices returned in GBp (pence) → divide by 100 for GBP
// ATH is managed client-side (localStorage) — Yahoo Finance data unreliable for SWDA.L

export default {
  async fetch(request, env) {

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type",
        },
      });
    }

    const url = new URL(request.url);
    const debug = url.searchParams.get("debug") === "1";

    // Fetch a single Yahoo Finance quote
    // Returns { value, prevClose, currency, status }
    const qFull = async (symbol) => {
      try {
        const r = await fetch(
          `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1d&range=1d`,
          {
            headers: {
              "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
              "Accept": "application/json",
            },
          }
        );
        const data = await r.json();
        const meta = data?.chart?.result?.[0]?.meta;
        if (!meta) return { value: null, prevClose: null, currency: null, status: r.status, raw: data?.chart?.error };
        const value    = meta.regularMarketPrice ?? null;
        const prevClose = meta.chartPreviousClose ?? meta.regularMarketPreviousClose ?? null;
        const currency = meta.currency ?? null;
        return { value, prevClose, currency, status: r.status };
      } catch (e) {
        return { value: null, prevClose: null, currency: null, status: "FETCH_ERROR", raw: e.message };
      }
    };

    // GBp (pence) → GBP conversion; everything else returned as-is
    const toGBP = (raw, currency) =>
      raw !== null && currency === "GBp" ? raw / 100 : raw;

    // LSE ETFs — Yahoo Finance uses .L suffix
    const etfs = {
      SGLN: "SGLN.L",
      DFNG: "DFNG.L",
      SSLN: "SSLN.L",
      GDGB: "GDGB.L",
      IEUX: "IEUX.L",
      NUCG: "NUCG.L",
      COPG: "COPG.L",
      CYBP: "CYBP.L",
      NAVY: "NAVY.L",
    };

    const tickers = Object.keys(etfs);
    const symbols = Object.values(etfs);

    // SWDA fetch: current price + prevClose only.
    // ATH is NOT computed here — Yahoo Finance returns an adjusted/total-return figure
    // (~12,838 GBp) for both fiftyTwoWeekHigh and historical closes, making server-side
    // ATH calculation unreliable. ATH is instead managed as a user-editable value in the
    // dashboard (persisted in localStorage), defaulting to the last known good value.
    const qSWDA = async () => {
      try {
        const r = await fetch(
          `https://query1.finance.yahoo.com/v8/finance/chart/SWDA.L?interval=1d&range=1d`,
          { headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "application/json" } }
        );
        const data = await r.json();
        const result = data?.chart?.result?.[0];
        const meta = result?.meta;
        if (!meta) return { value: null, prevClose: null, currency: null, status: r.status };
        const currency  = meta.currency ?? null;
        const value     = meta.regularMarketPrice ?? null;
        const prevClose = meta.chartPreviousClose ?? meta.regularMarketPreviousClose ?? null;
        return { value, prevClose, currency, status: r.status };
      } catch (e) {
        return { value: null, prevClose: null, currency: null, status: "FETCH_ERROR", raw: e.message };
      }
    };

    if (debug) {
      const [sgln, dfng, vix, swda, brent] = await Promise.all([
        qFull("SGLN.L"),
        qFull("DFNG.L"),
        qFull("^VIX"),
        qSWDA(),
        qFull("BZ=F"),
      ]);
      return new Response(JSON.stringify({
        "SGLN.L":   sgln,
        "DFNG.L":   dfng,
        "^VIX":     vix,
        "SWDA.L":   { value: swda.value, prevClose: swda.prevClose, currency: swda.currency, status: swda.status },
        "BZ=F":     brent,
      }, null, 2), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
      });
    }

    // Normal mode: fetch all in parallel
    const [etfResults, swdaResult, vixResult, brentResult] = await Promise.all([
      Promise.all(symbols.map(s => qFull(s))),
      qSWDA(),
      qFull("^VIX"),
      qFull("BZ=F"),
    ]);

    const prices    = {};
    const prevClose = {};

    tickers.forEach((ticker, i) => {
      const { value, prevClose: pc, currency } = etfResults[i];
      const v  = toGBP(value, currency);
      const pv = toGBP(pc,    currency);
      if (v  !== null) prices[ticker]    = v;
      if (pv !== null) prevClose[ticker] = pv;
    });

    return new Response(JSON.stringify({
      prices,
      prevClose,
      macro: {
        swda:          toGBP(swdaResult.value,     swdaResult.currency),
        swdaPrevClose: toGBP(swdaResult.prevClose, swdaResult.currency),
        vix:           vixResult.value,
        vixPrevClose:  vixResult.prevClose,
        brent:         brentResult.value,
      },
      ts:  Date.now(),
      src: "Yahoo Finance",
    }), {
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};
