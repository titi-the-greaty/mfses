// News fetcher via Polygon news API + sentiment scoring + cluster detection
import { getNews } from './polygon.js';

// Simple keyword-based sentiment scoring
var POSITIVE_WORDS = ['surge','rally','beat','exceeds','growth','profit','upgrade','outperform','bullish','record','strong','momentum','breakout','soar','gain'];
var NEGATIVE_WORDS = ['crash','plunge','miss','decline','loss','downgrade','underperform','bearish','layoff','weak','risk','warning','sell-off','drop','cut'];

function scoreSentiment(text) {
  var lower = text.toLowerCase();
  var pos = 0;
  var neg = 0;
  POSITIVE_WORDS.forEach(function(w) { if (lower.indexOf(w) >= 0) pos++; });
  NEGATIVE_WORDS.forEach(function(w) { if (lower.indexOf(w) >= 0) neg++; });
  var total = pos + neg;
  if (total === 0) return { score: 0, label: 'NEUTRAL' };
  var s = (pos - neg) / total;
  var label = s > 0.3 ? 'BULLISH' : s < -0.3 ? 'BEARISH' : 'NEUTRAL';
  return { score: +s.toFixed(2), label: label };
}

// Fetch and score news for given tickers
export async function fetchScoredNews(tickers, limit) {
  limit = limit || 5;
  var allArticles = [];

  for (var i = 0; i < tickers.length; i++) {
    try {
      var articles = await getNews(tickers[i], limit);
      articles.forEach(function(a) {
        a.sentiment = scoreSentiment(a.title);
        a.queryTicker = tickers[i];
      });
      allArticles = allArticles.concat(articles);
    } catch (e) { /* skip */ }
  }

  // Deduplicate by URL
  var seen = {};
  var unique = [];
  allArticles.forEach(function(a) {
    if (!seen[a.url]) { seen[a.url] = true; unique.push(a); }
  });

  // Sort by date descending
  unique.sort(function(a, b) {
    return (b.published || '') > (a.published || '') ? 1 : -1;
  });

  return unique;
}

// Detect news clusters (multiple articles on same topic/ticker in short window)
export function detectNewsClusters(articles) {
  var tickerCounts = {};
  var recentWindow = Date.now() - 24 * 60 * 60 * 1000; // last 24h

  articles.forEach(function(a) {
    var pubTime = new Date(a.published || 0).getTime();
    if (pubTime > recentWindow) {
      (a.tickers || []).forEach(function(ticker) {
        tickerCounts[ticker] = (tickerCounts[ticker] || 0) + 1;
      });
    }
  });

  var clusters = [];
  Object.keys(tickerCounts).forEach(function(ticker) {
    if (tickerCounts[ticker] >= 3) {
      clusters.push({ ticker: ticker, count: tickerCounts[ticker], alert: 'HIGH_NEWS_VOLUME' });
    }
  });

  return clusters;
}

// Aggregate sentiment per ticker
export function aggregateSentiment(articles) {
  var byTicker = {};

  articles.forEach(function(a) {
    if (!a.sentiment) return;
    var ticker = a.queryTicker || (a.tickers && a.tickers[0]) || 'UNKNOWN';
    if (!byTicker[ticker]) byTicker[ticker] = { scores: [], articles: 0 };
    byTicker[ticker].scores.push(a.sentiment.score);
    byTicker[ticker].articles++;
  });

  var result = {};
  Object.keys(byTicker).forEach(function(ticker) {
    var scores = byTicker[ticker].scores;
    var avg = scores.reduce(function(s, v) { return s + v; }, 0) / scores.length;
    result[ticker] = {
      avgSentiment: +avg.toFixed(2),
      label: avg > 0.3 ? 'BULLISH' : avg < -0.3 ? 'BEARISH' : 'NEUTRAL',
      articleCount: byTicker[ticker].articles
    };
  });

  return result;
}
