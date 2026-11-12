const rateMap = new Map();

// Grounding: You.com Web Search — gateway goi search truoc khi proxy toi
// LiteLLM, nhet ket qua vao prompt dang khoi <GROUNDING_DATA> (co nguon +
// thoi gian). Fail-open: search loi/timeout thi proxy binh thuong nhu cu.
// Chi Search o lane nay (khong Research/Contents). Secret: YOUCOM_API_KEY.
const YOUCOM_SEARCH_URL = 'https://ydc-index.io/v1/search';
const YOUCOM_COUNT = 5;
const YOUCOM_TIMEOUT_MS = 5000;

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
      // Host treo (khong tra loi) thi bo sau 8s de chuyen host tiep,
      // khong de ca request treo theo (gap 09-10/11: IB public URL treo;
      // 30s/host -> toi da 180s khi nhieu host treo, rut xuong 8s).
      signal: AbortSignal.timeout(8000),
    });
  } catch {
    return null;
  }
  if (resp.status >= 500) return null;
  return resp;
}

function lastUserText(body) {
  const messages = Array.isArray(body && body.messages) ? body.messages : [];
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i] && messages[i].role === 'user') {
      const c = messages[i].content;
      if (typeof c === 'string') return c;
      if (Array.isArray(c)) {
        const parts = c
          .filter(p => p && p.type === 'text' && typeof p.text === 'string')
          .map(p => p.text);
        return parts.join(' ');
      }
      return '';
    }
  }
  return '';
}

function trimSnippet(s) {
  const t = String(s || '').replace(/\s+/g, ' ').trim();
  return t.length > 240 ? t.slice(0, 240) + '…' : t;
}

async function fetchGrounding(query, apiKey) {
  if (!apiKey || !query || !query.trim()) return null;
  const started = Date.now();
  let resp;
  try {
    resp = await fetch(YOUCOM_SEARCH_URL, {
      method: 'POST',
      headers: {
        // You.com (Cloudflare) tra 403/1010 cho request khong co User-Agent
        // trinh duyet (gap tren chinh gateway nay 12/11); gui UA de qua WAF.
        'User-Agent': 'Mozilla/5.0 (compatible; vn-stock-ai-gateway)',
        'X-API-Key': apiKey,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query: query.slice(0, 500), count: YOUCOM_COUNT }),
      signal: AbortSignal.timeout(YOUCOM_TIMEOUT_MS),
    });
  } catch (e) {
    console.log('grounding fetch error', String(e && e.name || e), Date.now() - started + 'ms');
    return null;
  }
  if (!resp || resp.status < 200 || resp.status >= 300) {
    console.log('grounding search HTTP', resp ? resp.status : 'no-resp', Date.now() - started + 'ms');
    return null;
  }
  let data;
  try {
    data = await resp.json();
  } catch {
    console.log('grounding bad json', Date.now() - started + 'ms');
    return null;
  }
  const web = (data && data.results && Array.isArray(data.results.web)) ? data.results.web : [];
  if (!web.length) {
    console.log('grounding 0 results', Date.now() - started + 'ms');
    return null;
  }
  const lines = web.slice(0, YOUCOM_COUNT).map((r, i) => {
    const title = r.title || r.page_title || '';
    const url = r.url || r.page_url || '';
    const date = r.published_date || r.published || '';
    const desc = trimSnippet(r.description || r.snippet || '');
    return `- [${i + 1}] ${title} | ${url}${date ? ' | ' + date : ''}${desc ? ' | ' + desc : ''}`;
  });
  return [
    '<GROUNDING_DATA>',
    'nguon: You.com Web Search API',
    'thoi_diem: ' + new Date().toISOString(),
    'query: ' + query.slice(0, 500),
    ...lines,
    '</GROUNDING_DATA>',
    'Khối trên chỉ bổ sung tin tức có nguồn + thời gian. Số BCTC vẫn chỉ lấy từ VERIFIED_DATA; không tự tính số ngoài khối; thiếu dữ liệu lõi thì ABSTAIN như luật.',
  ].join('\n');
}

function injectGrounding(body, block) {
  const messages = Array.isArray(body.messages) ? body.messages : [];
  const idx = messages.findIndex(m => m && m.role === 'system');
  const msg = { role: 'system', content: block };
  if (idx >= 0) messages.splice(idx + 1, 0, msg);
  else messages.unshift(msg);
  body.messages = messages;
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
      const resp = new Response(JSON.stringify({ok: true, upstreams: upstreamUrls(env).length, grounding: Boolean(env.YOUCOM_API_KEY)}), {status: 200, headers: {'Content-Type': 'application/json'}});
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

      if (env.YOUCOM_API_KEY) {
        const block = await fetchGrounding(lastUserText(body), env.YOUCOM_API_KEY);
        if (block) {
          injectGrounding(body, block);
          console.log('POST', path, 'grounding injected', block.length + ' chars');
        } else {
          console.log('POST', path, 'grounding skipped (fail-open)');
        }
      }

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
