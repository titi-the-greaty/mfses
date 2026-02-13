// SEC EDGAR Form 4 parser
// Uses Vite proxy in dev (/sec-data, /sec-archives) and serverless proxy in prod

var SEC_DATA = '/sec-data';
var SEC_ARCHIVES = '/sec-archives';

// Major company CIKs for Form 4 fetching
var WATCHED_COMPANIES = [
  { ticker: 'AAPL', cik: '0000320193', name: 'Apple Inc' },
  { ticker: 'MSFT', cik: '0000789019', name: 'Microsoft Corp' },
  { ticker: 'NVDA', cik: '0001045810', name: 'NVIDIA Corp' },
  { ticker: 'GOOG', cik: '0001652044', name: 'Alphabet Inc' },
  { ticker: 'META', cik: '0001326801', name: 'Meta Platforms' },
  { ticker: 'AMZN', cik: '0001018724', name: 'Amazon.com Inc' },
  { ticker: 'TSLA', cik: '0001318605', name: 'Tesla Inc' },
  { ticker: 'JPM', cik: '0000019617', name: 'JPMorgan Chase' },
  { ticker: 'BAC', cik: '0000070858', name: 'Bank of America' },
  { ticker: 'WFC', cik: '0000072971', name: 'Wells Fargo' },
  { ticker: 'GS', cik: '0000886982', name: 'Goldman Sachs' },
  { ticker: 'UNH', cik: '0000731766', name: 'UnitedHealth' },
  { ticker: 'JNJ', cik: '0000200406', name: 'Johnson & Johnson' },
  { ticker: 'LLY', cik: '0000059478', name: 'Eli Lilly' },
  { ticker: 'AMD', cik: '0000002488', name: 'AMD' },
  { ticker: 'INTC', cik: '0000050863', name: 'Intel Corp' },
  { ticker: 'XOM', cik: '0000034088', name: 'Exxon Mobil' },
  { ticker: 'HD', cik: '0000354950', name: 'Home Depot' },
  { ticker: 'GM', cik: '0001467858', name: 'General Motors' },
  { ticker: 'BA', cik: '0000012927', name: 'Boeing Co' }
];

var idCounter = 0;

// Fetch company submissions to find Form 4 filings
async function fetchSubmissions(cik) {
  try {
    var res = await fetch(SEC_DATA + '/submissions/CIK' + cik + '.json');
    if (!res.ok) return [];
    var data = await res.json();
    var recent = data.filings?.recent;
    if (!recent) return [];

    var form4s = [];
    for (var i = 0; i < recent.form.length && form4s.length < 10; i++) {
      if (recent.form[i] === '4') {
        form4s.push({
          accession: recent.accessionNumber[i],
          date: recent.filingDate[i],
          primaryDoc: recent.primaryDocument[i],
          company: data.name,
          tickers: data.tickers || []
        });
      }
    }
    return form4s;
  } catch (err) {
    return [];
  }
}

// Parse Form 4 XML to extract trade details
async function parseForm4Xml(cik, accession, primaryDoc) {
  try {
    var accClean = accession.replace(/-/g, '');
    var url = SEC_ARCHIVES + '/Archives/edgar/data/' + cik.replace(/^0+/, '') + '/' + accClean + '/' + primaryDoc;
    var res = await fetch(url);
    if (!res.ok) return null;
    var text = await res.text();

    // Parse XML manually (no DOMParser dependency issues)
    var getTag = function(xml, tag) {
      var re = new RegExp('<' + tag + '>(.*?)</' + tag + '>', 's');
      var m = xml.match(re);
      return m ? m[1].trim() : '';
    };
    var getAllTags = function(xml, tag) {
      var re = new RegExp('<' + tag + '>([\\s\\S]*?)</' + tag + '>', 'g');
      var results = [];
      var m;
      while ((m = re.exec(xml)) !== null) results.push(m[1]);
      return results;
    };

    var issuerName = getTag(text, 'issuerName');
    var issuerTicker = getTag(text, 'issuerTradingSymbol');

    var rptOwnerName = getTag(text, 'rptOwnerName');
    var officerTitle = getTag(text, 'officerTitle') || getTag(text, 'relType') || 'Insider';

    // Get non-derivative transactions
    var transactions = getAllTags(text, 'nonDerivativeTransaction');
    var trades = [];
    for (var ti = 0; ti < transactions.length; ti++) {
      var tx = transactions[ti];
      var code = getTag(tx, 'transactionCode'); // P=purchase, S=sale
      var shares = parseFloat(getTag(tx, 'transactionShares') || getTag(tx, 'sharesOwnedFollowingTransaction') || '0');
      var price = parseFloat(getTag(tx, 'transactionPricePerShare') || '0');
      if (code === 'P' || code === 'S') {
        idCounter++;
        trades.push({
          id: idCounter,
          insider: rptOwnerName,
          title: officerTitle,
          company: issuerName,
          ticker: issuerTicker.toUpperCase(),
          type: code === 'P' ? 'BUY' : 'SELL',
          shares: Math.round(shares),
          value: Math.round(shares * price),
          date: getTag(tx, 'transactionDate') ? getTag(getTag(tx, 'transactionDate'), 'value') || '' : '',
          cap: 0,
          flagged: false,
          reason: ''
        });
      }
    }
    return trades;
  } catch (err) {
    return null;
  }
}

// Detect flagged trades: cluster buys, buys after big drops
function detectFlags(trades) {
  // Cluster detection: 3+ buys on same ticker within 7 days
  var tickerBuys = {};
  trades.forEach(function(tr) {
    if (tr.type === 'BUY') {
      if (!tickerBuys[tr.ticker]) tickerBuys[tr.ticker] = [];
      tickerBuys[tr.ticker].push(tr);
    }
  });

  Object.keys(tickerBuys).forEach(function(ticker) {
    var buys = tickerBuys[ticker];
    if (buys.length >= 3) {
      // Check if within 7 days
      var dates = buys.map(function(b) { return new Date(b.date).getTime(); }).sort();
      if (dates.length >= 3 && (dates[dates.length - 1] - dates[0]) <= 7 * 86400000) {
        buys.forEach(function(b) {
          b.flagged = true;
          b.reason = 'Cluster buy: ' + buys.length + ' insiders in 7d';
        });
      }
    }
  });

  return trades;
}

// Main: fetch recent Form 4 filings for all watched companies
export async function fetchRecentTrades(maxCompanies) {
  maxCompanies = maxCompanies || 10;
  var allTrades = [];
  var companies = WATCHED_COMPANIES.slice(0, maxCompanies);

  for (var ci = 0; ci < companies.length; ci++) {
    var co = companies[ci];
    try {
      var filings = await fetchSubmissions(co.cik);
      for (var fi = 0; fi < filings.length && fi < 3; fi++) {
        var trades = await parseForm4Xml(co.cik, filings[fi].accession, filings[fi].primaryDoc);
        if (trades && trades.length > 0) {
          // Fill in date from filing if transaction date missing
          trades.forEach(function(tr) {
            if (!tr.date) tr.date = filings[fi].date;
          });
          allTrades = allTrades.concat(trades);
        }
      }
      // Small delay between companies to respect SEC rate limits
      await new Promise(function(r) { setTimeout(r, 200); });
    } catch (err) {
      // Continue with next company
    }
  }

  // Sort by date descending
  allTrades.sort(function(a, b) { return b.date > a.date ? 1 : -1; });

  // Run flag detection
  allTrades = detectFlags(allTrades);

  return allTrades;
}

export { WATCHED_COMPANIES };
