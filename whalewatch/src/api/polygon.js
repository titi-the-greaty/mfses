// Polygon.io market data module
var API_KEY = import.meta.env.VITE_POLYGON_API_KEY || '';
var BASE = 'https://api.polygon.io';

var lastCall = 0;
async function polyFetch(path, params) {
  // Rate limit: 150ms between calls (free tier = 5/min, pro = higher)
  var now = Date.now();
  var wait = Math.max(0, 150 - (now - lastCall));
  if (wait > 0) await new Promise(function(r) { setTimeout(r, wait); });
  lastCall = Date.now();

  var url = new URL(BASE + path);
  if (params) {
    Object.keys(params).forEach(function(k) { url.searchParams.set(k, params[k]); });
  }
  url.searchParams.set('apiKey', API_KEY);

  var res = await fetch(url.toString());
  if (!res.ok) throw new Error('Polygon ' + res.status + ': ' + res.statusText);
  return res.json();
}

// Sector ticker lists for heatmap
var SECTOR_TICKERS = {
  'Technology': ['AAPL','MSFT','NVDA','GOOG','META','AVGO','AMD','INTC','CRM','ORCL'],
  'Financials': ['JPM','BAC','WFC','GS','MS','V','AXP'],
  'Healthcare': ['UNH','JNJ','LLY','PFE','ABBV','MRK'],
  'Energy': ['XOM','CVX','COP','SLB','EOG','OXY'],
  'Consumer': ['AMZN','TSLA','HD','NKE','MCD','COST'],
  'Industrials': ['GE','CAT','RTX','HON','BA'],
  'Real Estate': ['PLD','AMT','EQIX','SPG'],
  'Utilities': ['NEE','DUK','SO','AEP']
};

// Get single ticker snapshot
export async function getSnapshot(ticker) {
  try {
    var data = await polyFetch('/v2/snapshot/locale/us/markets/stocks/tickers/' + ticker);
    if (data.status === 'OK' && data.ticker) {
      return {
        ticker: ticker,
        price: data.ticker.lastTrade?.p || data.ticker.day?.c || 0,
        changePercent: data.ticker.todaysChangePerc || 0,
        volume: data.ticker.day?.v || 0,
        prevClose: data.ticker.prevDay?.c || 0
      };
    }
  } catch (err) {
    // Fallback: use previous day aggs
    try {
      var d = new Date();
      var to = d.toISOString().slice(0, 10);
      d.setDate(d.getDate() - 5);
      var from = d.toISOString().slice(0, 10);
      var agg = await polyFetch('/v2/aggs/ticker/' + ticker + '/range/1/day/' + from + '/' + to, { adjusted: 'true', sort: 'desc', limit: '2' });
      if (agg.results && agg.results.length >= 2) {
        var curr = agg.results[0];
        var prev = agg.results[1];
        var chg = prev.c > 0 ? ((curr.c - prev.c) / prev.c * 100) : 0;
        return { ticker: ticker, price: curr.c, changePercent: +chg.toFixed(2), volume: curr.v, prevClose: prev.c };
      }
    } catch (e2) { /* skip */ }
  }
  return null;
}

// Get OHLCV candle data
export async function getCandles(ticker, days) {
  days = days || 60;
  var to = new Date();
  var from = new Date(to.getTime() - days * 86400000);
  var data = await polyFetch('/v2/aggs/ticker/' + ticker + '/range/1/day/' + from.toISOString().slice(0,10) + '/' + to.toISOString().slice(0,10), {
    adjusted: 'true', sort: 'asc', limit: String(days + 10)
  });
  if (!data.results) return [];
  return data.results.map(function(bar) {
    var d = new Date(bar.t);
    return {
      date: (d.getMonth() + 1) + '/' + d.getDate(),
      open: +bar.o.toFixed(2),
      close: +bar.c.toFixed(2),
      high: +bar.h.toFixed(2),
      low: +bar.l.toFixed(2),
      volume: bar.v
    };
  });
}

// Get sector heatmap data via individual snapshots
export async function getSectorHeatmap() {
  var sectors = [];
  var sectorKeys = Object.keys(SECTOR_TICKERS);
  for (var si = 0; si < sectorKeys.length; si++) {
    var sector = sectorKeys[si];
    var tickers = SECTOR_TICKERS[sector];
    var tickerData = [];
    for (var ti = 0; ti < tickers.length; ti++) {
      try {
        var snap = await getSnapshot(tickers[ti]);
        if (snap) {
          tickerData.push({ t: snap.ticker, c: +(snap.changePercent || 0).toFixed(1) });
        }
      } catch (e) { /* skip failed tickers */ }
    }
    if (tickerData.length > 0) {
      var avg = tickerData.reduce(function(s, x) { return s + x.c; }, 0) / tickerData.length;
      sectors.push({ sector: sector, change: +avg.toFixed(1), mcap: '', tickers: tickerData });
    }
  }
  return sectors;
}

// Get company details
export async function getCompanyDetails(ticker) {
  var data = await polyFetch('/v3/reference/tickers/' + ticker);
  if (data.results) {
    return {
      name: data.results.name,
      ticker: ticker,
      marketCap: data.results.market_cap || 0,
      sector: data.results.sic_description || '',
      exchange: data.results.primary_exchange || ''
    };
  }
  return null;
}

// Get news articles for a ticker
export async function getNews(ticker, limit) {
  limit = limit || 10;
  var data = await polyFetch('/v2/reference/news', { ticker: ticker, limit: String(limit), sort: 'published_utc' });
  if (!data.results) return [];
  return data.results.map(function(article) {
    return {
      title: article.title,
      url: article.article_url,
      source: article.publisher?.name || 'Unknown',
      published: article.published_utc,
      tickers: article.tickers || [],
      sentiment: null // will be scored by reuters.js
    };
  });
}

// Get financials for balance sheet Sankey
export async function getFinancials(ticker) {
  try {
    var data = await polyFetch('/vX/reference/financials', { ticker: ticker, limit: '4', timeframe: 'annual', order: 'desc' });
    if (!data.results || data.results.length === 0) return null;
    return data.results.map(function(f) {
      var inc = f.financials?.income_statement || {};
      var bs = f.financials?.balance_sheet || {};
      var cf = f.financials?.cash_flow_statement || {};
      return {
        period: f.fiscal_period + ' ' + f.fiscal_year,
        revenue: inc.revenues?.value || 0,
        costOfRevenue: inc.cost_of_revenue?.value || 0,
        grossProfit: inc.gross_profit?.value || 0,
        operatingIncome: inc.operating_income_loss?.value || 0,
        netIncome: inc.net_income_loss?.value || 0,
        totalAssets: bs.assets?.value || 0,
        totalLiabilities: bs.liabilities?.value || 0,
        equity: bs.equity?.value || 0,
        cash: bs.current_assets?.value || 0,
        debt: bs.noncurrent_liabilities?.value || 0,
        operatingCashFlow: cf.net_cash_flow_from_operating_activities?.value || 0,
        freeCashFlow: (cf.net_cash_flow_from_operating_activities?.value || 0) + (cf.net_cash_flow_from_investing_activities?.value || 0)
      };
    });
  } catch (e) {
    return null;
  }
}

// Get market overview (SPX, VIX, BTC proxies)
export async function getMarketOverview() {
  var out = { spx: null, vix: null, btc: null };
  try {
    var spy = await getSnapshot('SPY');
    if (spy) out.spx = { price: +(spy.price * 10).toFixed(0), change: spy.changePercent };
  } catch (e) { /* skip */ }
  try {
    // VIX not directly available via equity snapshot; use VIXY as proxy
    var vixy = await getSnapshot('VIXY');
    if (vixy) out.vix = { price: vixy.price, change: vixy.changePercent };
  } catch (e) { /* skip */ }
  return out;
}
