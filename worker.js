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

    // Special fetch for SWDA: also pulls 5yr monthly history to calculate true ATH
    const qSWDA = async () => {
      try {
        const r = await fetch(
          `https://query1.finance.yahoo.com/v8/finance/chart/SWDA.L?interval=1mo&range=5y`,
          { headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Accept": "application/json" } }
        );
        const data = await r.json();
        const result = data?.chart?.result?.[0];
        const meta = result?.meta;
        if (!meta) return { value: null, prevClose: null, ath: null, currency: null, status: r.status };
        const currency  = meta.currency ?? null;
        const value     = meta.regularMarketPrice ?? null;
        const prevClose = meta.chartPreviousClose ?? meta.regularMarketPreviousClose ?? null;
        const closes = result?.indicators?.quote?.[0]?.close?.filter(c => c !== null && c > 0) ?? [];
        const histMax        = closes.length > 0 ? Math.max(...closes) : null;
        const fiftyTwoWkHigh = meta.fiftyTwoWeekHigh ?? null; // intraday high — matches broker "1Y High"
        // ATH = max of: historical monthly closes, 52-week intraday high, today's price
        const candidates = [histMax, fiftyTwoWkHigh, value].filter(v => v !== null && v > 0);
        const athRaw = candidates.length > 0 ? Math.max(...candidates) : null;
        return { value, prevClose, ath: athRaw, currency, status: r.status };
      } catch (e) {
        return { value: null, prevClose: null, ath: null, currency: null, status: "FETCH_ERROR", raw: e.message };
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
        "SWDA.L":   { value: swda.value, prevClose: swda.prevClose, ath: swda.ath, currency: swda.currency, status: swda.status },
        "SWDA ATH (GBP)": swda.ath !== null ? toGBP(swda.ath, swda.currency) : null,
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
        swdaATH:       toGBP(swdaResult.ath,       swdaResult.currency),
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
