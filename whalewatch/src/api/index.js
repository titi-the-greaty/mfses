// Data orchestrator + useWhaleWatchData() React hook
import { useState, useEffect, useRef, useCallback } from 'react';
import { getCandles, getSectorHeatmap, getSnapshot, getFinancials, getMarketOverview } from './polygon.js';
import { fetchRecentTrades } from './edgar.js';
import { fetchScoredNews, detectNewsClusters, aggregateSentiment } from './reuters.js';

// Data source status tracker
function createSourceStatus() {
  return {
    edgar: { status: 'IDLE', latency: null, lastUpdate: null, error: null },
    polygon: { status: 'IDLE', latency: null, lastUpdate: null, error: null },
    news: { status: 'IDLE', latency: null, lastUpdate: null, error: null }
  };
}

export function useWhaleWatchData(pollInterval) {
  pollInterval = pollInterval || 60000;

  var tradesState = useState([]);
  var trades = tradesState[0], setTrades = tradesState[1];

  var sectorsState = useState([]);
  var sectors = sectorsState[0], setSectors = sectorsState[1];

  var newsState = useState([]);
  var news = newsState[0], setNews = newsState[1];

  var mktState = useState(null);
  var marketOverview = mktState[0], setMarketOverview = mktState[1];

  var statusRef = useRef(createSourceStatus());
  var loadingState = useState(true);
  var loading = loadingState[0], setLoading = loadingState[1];

  // Fetch trades from SEC EDGAR
  var refreshTrades = useCallback(function() {
    var start = Date.now();
    statusRef.current.edgar.status = 'LOADING';
    return fetchRecentTrades(8).then(function(data) {
      if (data && data.length > 0) setTrades(data);
      statusRef.current.edgar = { status: 'LIVE', latency: (Date.now() - start) + 'ms', lastUpdate: new Date(), error: null };
      return data;
    }).catch(function(err) {
      statusRef.current.edgar = { status: 'ERROR', latency: null, lastUpdate: null, error: err.message };
      return [];
    });
  }, []);

  // Fetch sector heatmap from Polygon
  var refreshSectors = useCallback(function() {
    var start = Date.now();
    statusRef.current.polygon.status = 'LOADING';
    return getSectorHeatmap().then(function(data) {
      if (data && data.length > 0) setSectors(data);
      statusRef.current.polygon = { status: 'LIVE', latency: (Date.now() - start) + 'ms', lastUpdate: new Date(), error: null };
      return data;
    }).catch(function(err) {
      statusRef.current.polygon = { status: 'ERROR', latency: null, lastUpdate: null, error: err.message };
      return [];
    });
  }, []);

  // Fetch candle data for a specific ticker
  var refreshCandles = useCallback(function(ticker, days) {
    return getCandles(ticker, days || 60);
  }, []);

  // Fetch news
  var refreshNews = useCallback(function(tickers) {
    tickers = tickers || ['NVDA', 'AAPL', 'MSFT', 'TSLA', 'META'];
    var start = Date.now();
    statusRef.current.news.status = 'LOADING';
    return fetchScoredNews(tickers, 5).then(function(data) {
      if (data && data.length > 0) setNews(data);
      statusRef.current.news = { status: 'LIVE', latency: (Date.now() - start) + 'ms', lastUpdate: new Date(), error: null };
      return data;
    }).catch(function(err) {
      statusRef.current.news = { status: 'ERROR', latency: null, lastUpdate: null, error: err.message };
      return [];
    });
  }, []);

  // Market overview
  var refreshMarket = useCallback(function() {
    return getMarketOverview().then(function(data) {
      setMarketOverview(data);
      return data;
    }).catch(function() { return null; });
  }, []);

  // Get balance sheet financials for a ticker
  var getBalanceSheet = useCallback(function(ticker) {
    return getFinancials(ticker);
  }, []);

  // Data source status for the SrcComp widget
  var getDataSourceStatus = useCallback(function() {
    var s = statusRef.current;
    return [
      { n: 'SEC EDGAR', s: s.edgar.status, l: s.edgar.latency || '—' },
      { n: 'Polygon.io Pro', s: s.polygon.status, l: s.polygon.latency || '—' },
      { n: 'News / Sentiment', s: s.news.status, l: s.news.latency || '—' }
    ];
  }, []);

  // AI query handler with live data
  var handleQuery = useCallback(function(cmd) {
    var q = cmd.toLowerCase();

    if (q.indexOf('flag') >= 0) {
      var flagged = trades.filter(function(x) { return x.flagged; });
      if (flagged.length === 0) return Promise.resolve('No flagged trades detected yet.');
      var lines = flagged.map(function(f) { return '  ' + f.insider + ' (' + f.ticker + ') ' + f.type + ' $' + (f.value / 1e6).toFixed(1) + 'M — ' + f.reason; });
      return Promise.resolve('⸬ ' + flagged.length + ' FLAGGED TRADES:\n' + lines.join('\n'));
    }

    if (q.indexOf('sell') >= 0 || q.indexOf('top') >= 0) {
      var sells = trades.filter(function(x) { return x.type === 'SELL'; }).sort(function(a, b) { return b.value - a.value; }).slice(0, 5);
      if (sells.length === 0) return Promise.resolve('No sell trades loaded yet.');
      var sLines = sells.map(function(s, i) { return '  ' + (i + 1) + '. ' + s.insider + ' ' + s.ticker + ' $' + (s.value / 1e6).toFixed(1) + 'M'; });
      return Promise.resolve('⸬ TOP SELLS:\n' + sLines.join('\n'));
    }

    if (q.indexOf('sector') >= 0) {
      if (sectors.length === 0) return Promise.resolve('Sector data loading...');
      var secLines = sectors.map(function(s) { return '  ' + s.sector + ' ' + (s.change > 0 ? '+' : '') + s.change + '%'; });
      return Promise.resolve('⸬ SECTORS:\n' + secLines.join('\n'));
    }

    // Ticker lookup
    var tickerMatch = cmd.toUpperCase().match(/[A-Z]{1,5}/);
    if (tickerMatch) {
      var ticker = tickerMatch[0];
      var tickerTrades = trades.filter(function(x) { return x.ticker === ticker; });
      if (tickerTrades.length > 0) {
        var tLines = tickerTrades.slice(0, 3).map(function(tr) { return '  ' + tr.insider + ' ' + tr.type + ' $' + (tr.value / 1e6).toFixed(1) + 'M · ' + tr.date; });
        return Promise.resolve('⸬ ' + ticker + ': ' + tickerTrades.length + ' trades\n' + tLines.join('\n'));
      }
      // Try getting a snapshot
      return getSnapshot(ticker).then(function(snap) {
        if (snap) return '⸬ ' + ticker + ': $' + snap.price.toFixed(2) + ' (' + (snap.changePercent > 0 ? '+' : '') + snap.changePercent.toFixed(2) + '%)';
        return 'No data for "' + cmd + '"';
      }).catch(function() { return 'No data for "' + cmd + '"'; });
    }

    return Promise.resolve('Commands: flagged, top sells, sector, [TICKER]');
  }, [trades, sectors]);

  // Initial load
  useEffect(function() {
    var cancelled = false;

    async function load() {
      // Load in priority order, don't block on slow ones
      refreshMarket();
      refreshSectors();
      refreshNews();
      // EDGAR is slowest, load last
      await refreshTrades();
      if (!cancelled) setLoading(false);
    }

    load();

    // Poll for updates
    var iv = setInterval(function() {
      refreshMarket();
      refreshSectors();
    }, pollInterval);

    // Less frequent EDGAR poll (5 min)
    var edgarIv = setInterval(function() {
      refreshTrades();
    }, 300000);

    return function() {
      cancelled = true;
      clearInterval(iv);
      clearInterval(edgarIv);
    };
  }, [pollInterval, refreshMarket, refreshSectors, refreshNews, refreshTrades]);

  return {
    trades: trades,
    sectors: sectors,
    news: news,
    marketOverview: marketOverview,
    loading: loading,
    refreshTrades: refreshTrades,
    refreshSectors: refreshSectors,
    refreshCandles: refreshCandles,
    refreshNews: refreshNews,
    refreshMarket: refreshMarket,
    getBalanceSheet: getBalanceSheet,
    getDataSourceStatus: getDataSourceStatus,
    handleQuery: handleQuery
  };
}
