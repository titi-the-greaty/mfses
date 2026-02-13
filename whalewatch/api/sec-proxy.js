// Vercel serverless function — CORS proxy for SEC EDGAR
export default async function handler(req, res) {
  var path = req.query.path;
  if (!path) {
    res.status(400).json({ error: 'Missing path parameter' });
    return;
  }

  try {
    var target = path.startsWith('/Archives') ? 'https://www.sec.gov' + path : 'https://data.sec.gov' + path;
    var secRes = await fetch(target, {
      headers: { 'User-Agent': process.env.VITE_SEC_USER_AGENT || 'WhaleWatch admin@seesaw.io' }
    });
    var data = await secRes.text();
    var ct = secRes.headers.get('content-type') || 'text/plain';
    res.setHeader('Content-Type', ct);
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(secRes.status).send(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
