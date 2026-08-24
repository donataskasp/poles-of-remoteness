/* The old worker name keeps the old workers.dev URL alive forever: every request is a permanent
   redirect to the Lithuania view of the new site, so the LinkedIn post of 2026-08-17 still lands
   where its readers expect. The URL hash survives a redirect in the browser, no logging happens here. */
export default {
  fetch() {
    return Response.redirect('https://polesofremoteness.com/europe/lt', 301);
  },
};
