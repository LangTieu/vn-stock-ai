const rateMap = new Map();

export default {
  async fetch(request, env) {
    const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
    const now = Date.now();
    const timestamps = rateMap.get(ip) || [];
    const recent = timestamps.filter(t => now - t < 60000);
    if (recent.length >= 30) {
      const resp = new Response(JSON.stringify({error: 'rate limited'}), {status: 429, headers: {'Content-Type': 'application/json'}});
      console.log(request.method, new URL(request.url).pathname, 429);
      return resp;
    }
    recent.push(now);
    rateMap.set(ip, recent);

    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === 'GET' && path === '/health') {
      const resp = new Response(JSON.stringify({ok: true}), {status: 200, headers: {'Content-Type': 'application/json'}});
      console.log('GET', path, 200);
      return resp;
    }

    if (request.method === 'POST' && path === '/v1/chat/completions') {
      const auth = request.headers.get('Authorization') || '';
      if (auth !== `Bearer ${env.GATEWAY_API_KEY}`) {
        const resp = new Response(JSON.stringify({error: 'unauthorized'}), {status: 401, headers: {'Content-Type': 'application/json'}});
        console.log('POST', path, 401);
        return resp;
      }

      let body;
      try {
        body = await request.json();
      } catch {
        const resp = new Response(JSON.stringify({error: 'invalid json'}), {status: 400, headers: {'Content-Type': 'application/json'}});
        console.log('POST', path, 400);
        return resp;
      }

      if (!Array.isArray(body.messages)) {
        const resp = new Response(JSON.stringify({error: 'messages required'}), {status: 400, headers: {'Content-Type': 'application/json'}});
        console.log('POST', path, 400);
        return resp;
      }

      body.model = 'vn-stock';

      const upstreamUrl = `${env.LITELLM_URL}/v1/chat/completions`;
      const upstreamHeaders = new Headers();
      upstreamHeaders.set('Authorization', `Bearer ${env.LITELLM_MASTER_KEY}`);
      upstreamHeaders.set('Content-Type', 'application/json');

      let upstreamResp;
      try {
        upstreamResp = await fetch(upstreamUrl, {
          method: 'POST',
          headers: upstreamHeaders,
          body: JSON.stringify(body)
        });
      } catch {
        const resp = new Response(JSON.stringify({error: 'upstream unavailable'}), {status: 502, headers: {'Content-Type': 'application/json'}});
        console.log('POST', path, 502);
        return resp;
      }

      const contentType = upstreamResp.headers.get('content-type') || 'application/json';
      const headers = new Headers();
      headers.set('Content-Type', contentType);
      console.log('POST', path, upstreamResp.status);
      return new Response(upstreamResp.body, {status: upstreamResp.status, headers});
    }

    const resp = new Response(JSON.stringify({error: 'not found'}), {status: 404, headers: {'Content-Type': 'application/json'}});
    console.log(request.method, path, 404);
    return resp;
  }
}
