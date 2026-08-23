/* Poles of remoteness, server side. Two jobs on HTML page loads (run_worker_first in wrangler.jsonc sends
   only the extension-less paths here): record one Analytics Engine data point, and stamp the visitor's
   coarse location into the page so the first screen can open the visitor's own unit without a geolocation
   prompt. Every other request goes straight to the static assets binding.

   Privacy by design (GDPR): no raw user agent, no IP, no unique or quasi-unique identifier, so a data point
   cannot be traced back to a person and no consent banner is owed. What is kept is coarse: country,
   Cloudflare colo, referrer host, browser family, OS family, our hostname, and the landing region and unit
   from the URL path. The visitor meta written into the page is the country and region code Cloudflare
   already attaches to the request; it never leaves the visitor's own page. */

const SEG = /^[a-z][a-z0-9-]{0,31}$/;

/* The page paths are '/', '/<region>' and '/<region>/<unit>', a trailing slash tolerated. Anything else
   (including '/index.html', which the assets layer redirects to '/') is not a page view. */
export function landing(pathname) {
  const parts = pathname.replace(/\/+$/, '').split('/').slice(1);
  if (parts.length === 0) return { page: true, region: '', unit: '' };
  if (parts.length > 2 || !parts.every((p) => SEG.test(p))) return { page: false, region: '', unit: '' };
  return { page: true, region: parts[0], unit: parts[1] || '' };
}

/* 'LT' or 'US-AK' from request.cf, uppercase, or '' when the country is not a plain two-letter code
   (Cloudflare uses 'T1' for Tor and leaves the field empty for some ranges). The value is written into
   HTML, so the shape is enforced here and the site re-checks it before use. */
export function visitorCode(cf) {
  const country = String((cf && cf.country) || '').toUpperCase();
  if (!/^[A-Z]{2}$/.test(country)) return '';
  const region = String((cf && cf.regionCode) || '').toUpperCase();
  return /^[A-Z0-9]{1,3}$/.test(region) ? `${country}-${region}` : country;
}

/* Coarse user agent buckets. Order matters: a specific token has to be tested before the generic one it
   embeds. Edge, Opera and Samsung Internet all carry "Chrome", Chrome and Firefox on iOS carry "Safari",
   Android carries "Linux". */
export function browserFamily(ua) {
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

export function osFamily(ua) {
  if (!ua) return 'Other';
  if (/android/i.test(ua)) return 'Android';
  if (/iphone|ipad|ipod|ios\//i.test(ua)) return 'iOS';
  if (/mac os x|macintosh/i.test(ua)) return 'macOS';
  if (/windows/i.test(ua)) return 'Windows';
  if (/linux|x11|cros/i.test(ua)) return 'Linux';
  return 'Other';
}

/* Host of the referring page, or '' when there is no referrer, it does not parse, or the visit came from
   our own site. Only the host is kept, never the full URL, which can carry query strings and personal data. */
export function referrerHost(request, url) {
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
    const where = landing(url.pathname);
    if (request.method !== 'GET' || !where.page) return env.ASSETS.fetch(request);

    const response = await env.ASSETS.fetch(request);
    const type = response.headers.get('Content-Type') || '';
    if (!type.includes('text/html')) return response;

    try {
      const ua = request.headers.get('User-Agent') || '';
      env.SITE_VIEWS.writeDataPoint({
        /* Fixed blob order, do not reshuffle: queries address blobs positionally.
             blob1 country,  blob2 colo,           blob3 referrer host, blob4 browser,
             blob5 OS family, blob6 hostname,      blob7 landing region, blob8 landing unit */
        blobs: [
          (request.cf && request.cf.country) || '',
          (request.cf && request.cf.colo) || '',
          referrerHost(request, url),
          browserFamily(ua),
          osFamily(ua),
          url.hostname,
          where.region,
          where.unit,
        ],
        doubles: [1],
        indexes: ['view'],
      });
    } catch {
      /* Analytics is best effort. Never let it break serving the page. */
    }

    const code = visitorCode(request.cf);
    if (!code) return response;
    return new HTMLRewriter()
      .on('head', { element(el) { el.append(`<meta name="visitor" content="${code}">`, { html: true }); } })
      .transform(response);
  },
};
