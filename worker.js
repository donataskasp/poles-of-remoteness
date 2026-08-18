/* Atokiausia Lietuva - server side page view logging.
   Runs in front of HTML page loads only (see run_worker_first in
   wrangler.jsonc), records one Analytics Engine data point, then hands the
   request straight back to the static assets binding.

   Privacy by design (GDPR): we deliberately do NOT store the raw user agent
   string, the client IP, or any other unique or quasi-unique identifier, so a
   data point cannot be traced back to a person and no consent banner is owed.
   What we keep is coarse and non-identifying: country, Cloudflare colo,
   referrer host, browser family, OS family, and our own hostname. */

/* Only '/' counts: a direct /index.html hit gets a 307 redirect to '/' from
   the assets layer and would otherwise log twice. */
const PAGE_PATHS = new Set(['/']);

/* Coarse user agent buckets. Order matters: a specific token has to be tested
   before the generic one it embeds. Edge, Opera and Samsung Internet all carry
   "Chrome", Chrome and Firefox on iOS carry "Safari", Android carries "Linux". */
function browserFamily(ua) {
  if (!ua) return 'Other';
  if (/bot|crawl|spider|slurp|headlesschrome|facebookexternalhit|curl|wget|monitoring/i.test(ua)) return 'Bot';
  if (/edg(e|a|ios)?\//i.test(ua)) return 'Edge';
  if (/samsungbrowser\//i.test(ua)) return 'Samsung Internet';
  if (/opr\/|opios\/|opera/i.test(ua)) return 'Opera';
  if (/firefox\/|fxios\//i.test(ua)) return 'Firefox';
  if (/(chrome|chromium|crios)\//i.test(ua)) return 'Chrome';
  if (/safari\//i.test(ua)) return 'Safari';
  return 'Other';
}

function osFamily(ua) {
  if (!ua) return 'Other';
  if (/android/i.test(ua)) return 'Android';
  if (/iphone|ipad|ipod|ios\//i.test(ua)) return 'iOS';
  if (/mac os x|macintosh/i.test(ua)) return 'macOS';
  if (/windows/i.test(ua)) return 'Windows';
  if (/linux|x11|cros/i.test(ua)) return 'Linux';
  return 'Other';
}

/* Host of the referring page, or '' when there is no referrer, it does not
   parse, or the visit came from our own site. Only the host is kept, never the
   full referrer URL, which can carry query strings and personal data. */
function referrerHost(request, url) {
  const ref = request.headers.get('Referer');
  if (!ref) return '';
  try {
    const host = new URL(ref).hostname.replace(/^www\./, '');
    return host === url.hostname.replace(/^www\./, '') ? '' : host;
  } catch {
    return '';
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'GET' && PAGE_PATHS.has(url.pathname)) {
      try {
        const ua = request.headers.get('User-Agent') || '';
        env.SITE_VIEWS.writeDataPoint({
          /* Fixed blob order, do not reshuffle: existing rows keep the old
             layout and queries address blobs positionally.
               blob1 country, blob2 colo,       blob3 referrer host,
               blob4 browser, blob5 OS family,  blob6 hostname */
          blobs: [
            request.cf?.country || '',
            request.cf?.colo || '',
            referrerHost(request, url),
            browserFamily(ua),
            osFamily(ua),
            url.hostname,
          ],
          doubles: [1],
          indexes: ['view'],
        });
      } catch {
        /* Analytics is best effort. Never let it break serving the page. */
      }
    }

    return env.ASSETS.fetch(request);
  },
};
