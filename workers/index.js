const rateMap = new Map();

// Lay danh sach LiteLLM host tu env LITELLM_URLS (cach nhau bang dau phay).
// Vi du: "https://lv1.example.com,https://lv2.example.com,https://m1.example.com"
// Tuong thich nguoc: neu chi co LITELLM_URL (1 host) thi dung no.
function upstreamUrls(env) {
  const raw = env.LITELLM_URLS || env.LITELLM_URL || '';
  return raw.split(',').map(s => s.trim()).filter(Boolean);
}

// Thu goi 1 host; tra Response neu duoc (ke ca 4xx tu LiteLLM — do la
// loi cua request, khong phai host chet), null neu host khong tra loi
// duoc (loi mang) hoac tra 5xx (host loi). Nguoi goi se thu host tiep.
async function tryUpstream(base, body, masterKey) {
  let resp;
  try {
    resp = await fetch(`${base}/v1/chat/completions`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${masterKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      // Host treo (khong tra loi) thi bo sau 30s de chuyen host tiep,
      // khong de ca request treo theo (gap 09-10/11: IB public URL treo).
      signal: AbortSignal.timeout(30000),
    });
  } catch {
    return null;
  }
  if (resp.status >= 500) return null;
  return resp;
}

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
      const resp = new Response(JSON.stringify({ok: true, upstreams: upstreamUrls(env).length}), {status: 200, headers: {'Content-Type': 'application/json'}});
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

      body.model = 'vn-stock-assistant';

      const hosts = upstreamUrls(env);
      if (hosts.length === 0) {
        const resp = new Response(JSON.stringify({error: 'no upstream configured'}), {status: 502, headers: {'Content-Type': 'application/json'}});
        console.log('POST', path, 502);
        return resp;
      }

      // Thu lan luot tung host; host nao tra loi duoc (ke ca 4xx) thi dung.
      let upstreamResp = null;
      let usedHost = '';
      for (const base of hosts) {
        upstreamResp = await tryUpstream(base, body, env.LITELLM_MASTER_KEY);
        if (upstreamResp) { usedHost = base; break; }
        console.log('POST', path, 'upstream failover, host khong tra loi:', base);
      }
      if (!upstreamResp) {
        const resp = new Response(JSON.stringify({error: 'upstream unavailable'}), {status: 502, headers: {'Content-Type': 'application/json'}});
        console.log('POST', path, 502);
        return resp;
      }

      const contentType = upstreamResp.headers.get('content-type') || 'application/json';
      const headers = new Headers();
      headers.set('Content-Type', contentType);
      console.log('POST', path, upstreamResp.status, 'via', usedHost);
      return new Response(upstreamResp.body, {status: upstreamResp.status, headers});
    }

    const resp = new Response(JSON.stringify({error: 'not found'}), {status: 404, headers: {'Content-Type': 'application/json'}});
    console.log(request.method, path, 404);
    return resp;
  }
}
