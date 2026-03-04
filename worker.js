// Fortress 2026 — Cloudflare Worker
// Uses Yahoo Finance (no API key required)
// LSE ETFs: .L suffix, prices returned in GBp (pence) → divide by 100 for GBP
// Replace the existing Worker code with this entire file.

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

    // Fetch a single Yahoo Finance quote — returns { value, currency, status }
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
        if (!meta) return { value: null, currency: null, status: r.status, raw: data?.chart?.error };
        const value  = meta.regularMarketPrice ?? null;
        const currency = meta.currency ?? null;
        return { value, currency, status: r.status };
      } catch (e) {
        return { value: null, currency: null, status: "FETCH_ERROR", raw: e.message };
      }
    };

    // GBp (pence) → GBP conversion; everything else returned as-is
    const toGBP = ({ value, currency }) =>
      value !== null && currency === "GBp" ? value / 100 : value;

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

    if (debug) {
      // Debug mode: test key symbols and show raw currency/value
      const [sgln, dfng, vix, swda, brent] = await Promise.all([
        qFull("SGLN.L"),
        qFull("DFNG.L"),
        qFull("^VIX"),
        qFull("SWDA.L"),
        qFull("BZ=F"),
      ]);
      return new Response(JSON.stringify({
        "SGLN.L":  sgln,
        "DFNG.L":  dfng,
        "^VIX":    vix,
        "SWDA.L":  swda,
        "BZ=F":    brent,
      }, null, 2), {
        headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
      });
    }

    // Normal mode: fetch all in parallel
    const [etfResults, swdaResult, vixResult, brentResult] = await Promise.all([
      Promise.all(symbols.map(s => qFull(s))),
      qFull("SWDA.L"),
      qFull("^VIX"),
      qFull("BZ=F"),   // Brent Crude futures
    ]);

    const prices = {};
    tickers.forEach((ticker, i) => {
      const v = toGBP(etfResults[i]);
      if (v !== null) prices[ticker] = v;
    });

    return new Response(JSON.stringify({
      prices,
      macro: {
        swda:  toGBP(swdaResult),
        vix:   vixResult.value,    // VIX index — already in points, no conversion
        brent: brentResult.value,  // USD per barrel
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
