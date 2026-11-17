import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type Addr, type Config, type MessageDetail, type MessageItem } from "./api";

/* ---------- tiện ích ---------- */

type Route =
  | { name: "list"; folder: "inbox" | "sent" }
  | { name: "message"; id: string }
  | { name: "compose"; replyTo?: string; forward?: string };

function parseRoute(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#/, "").split("?");
  const qs = new URLSearchParams(query);
  const m = path.match(/^\/m\/([0-9a-f-]{36})$/);
  if (m) return { name: "message", id: m[1] };
  if (path === "/compose")
    return { name: "compose", replyTo: qs.get("reply") || undefined, forward: qs.get("forward") || undefined };
  if (path === "/sent") return { name: "list", folder: "sent" };
  return { name: "list", folder: "inbox" };
}

function useRoute(): Route {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const on = () => setHash(location.hash);
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return useMemo(() => parseRoute(hash), [hash]);
}

const go = (h: string) => (location.hash = h);

function back(fallback: string) {
  if (history.length > 1) history.back();
  else go(fallback);
}

function formatDate(ts: number, long = false) {
  const d = new Date(ts);
  const now = new Date();
  if (long)
    return d.toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric" });
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
  if (d.getFullYear() === now.getFullYear()) return `${d.getDate()} thg ${d.getMonth() + 1}`;
  return d.toLocaleDateString("vi-VN");
}

function formatSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const displayName = (a?: Addr) => (a ? a.name || a.address : "");
const addrLine = (list: Addr[]) => list.map((a) => (a.name ? `${a.name} <${a.address}>` : a.address)).join(", ");

const COLORS = ["bg-teal-600", "bg-sky-600", "bg-indigo-600", "bg-rose-600", "bg-amber-600", "bg-emerald-600", "bg-violet-600"];

function Avatar({ label }: { label: string }) {
  const ch = (label.trim()[0] || "?").toUpperCase();
  let h = 0;
  for (const c of label) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return (
    <div className={`${COLORS[h % COLORS.length]} flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-base font-semibold text-white`}>
      {ch}
    </div>
  );
}

/* ---------- icon ---------- */

const Icon = ({ d, className = "h-6 w-6" }: { d: string; className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d={d} />
  </svg>
);
const I = {
  back: "M15 18l-6-6 6-6",
  search: "M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.35-4.35",
  close: "M18 6L6 18M6 6l12 12",
  pen: "M12 20h9M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z",
  send: "M22 2L11 13M22 2l-7 20-4-9-9-4z",
  reply: "M9 17l-5-5 5-5M20 18v-2a4 4 0 00-4-4H4",
  forward: "M15 17l5-5-5-5M4 18v-2a4 4 0 014-4h12",
  clip: "M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48",
  logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
  refresh: "M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15",
  unread: "M4 4h16v16H4zM4 4l8 8 8-8",
  download: "M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3",
};

function IconButton({ icon, label, onClick, className = "" }: { icon: string; label: string; onClick: () => void; className?: string }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className={`rounded-full p-2 active:bg-black/10 ${className}`}>
      <Icon d={icon} />
    </button>
  );
}

function Spinner() {
  return <div className="mx-auto my-10 h-7 w-7 animate-spin rounded-full border-2 border-teal-600 border-t-transparent" />;
}

function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="m-4 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
      {message}
      {onRetry && (
        <button onClick={onRetry} className="ml-2 font-semibold underline">
          Thử lại
        </button>
      )}
    </div>
  );
}

/* ---------- đăng nhập ---------- */

declare global {
  interface Window {
    google?: any;
  }
}

function Login({ config, onDone }: { config: Config; onDone: () => void }) {
  const btn = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!config.googleClientId) return;
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => {
      window.google.accounts.id.initialize({
        client_id: config.googleClientId,
        callback: async (r: { credential: string }) => {
          try {
            await api.loginGoogle(r.credential);
            onDone();
          } catch (e) {
            setError((e as Error).message);
          }
        },
        ux_mode: "popup",
      });
      window.google.accounts.id.renderButton(btn.current, { theme: "outline", size: "large", shape: "pill", text: "signin_with", locale: "vi" });
    };
    s.onerror = () => setError("Không tải được Google Sign-In");
    document.head.appendChild(s);
    return () => s.remove();
  }, [config.googleClientId, onDone]);

  return (
    <div className="flex min-h-full flex-col items-center justify-center bg-gradient-to-b from-teal-700 to-teal-900 px-6 py-12">
      <div className="w-full max-w-sm rounded-3xl bg-white p-7 text-center shadow-xl">
        <img src="/icon.svg" alt="" className="mx-auto h-14 w-14" />
        <h1 className="mt-4 text-xl font-bold">Thư AI Stock VN</h1>
        <p className="mt-1 text-sm text-slate-500">{config.mailbox}</p>
        <p className="mt-5 text-sm text-slate-600">Đăng nhập bằng tài khoản Google được cấp quyền để đọc và gửi thư.</p>
        <div className="mt-6 flex min-h-11 justify-center">
          {config.googleClientId ? (
            <div ref={btn} />
          ) : (
            <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
              Chưa cấu hình Google Client ID nên chưa thể đăng nhập bằng Google.
            </p>
          )}
        </div>
        {config.devLogin && (
          <button
            onClick={() => api.loginDev().then(onDone, (e) => setError(e.message))}
            className="mt-4 w-full rounded-full border border-dashed border-slate-400 py-2.5 text-sm text-slate-600"
          >
            Đăng nhập bản thử (chỉ môi trường local/preview)
          </button>
        )}
        {error && <p className="mt-4 text-sm text-rose-700">{error}</p>}
      </div>
    </div>
  );
}

/* ---------- danh sách thư ---------- */

function MailList({ folder, unread, onLogout, refreshCounts }: { folder: "inbox" | "sent"; unread: number; onLogout: () => void; refreshCounts: () => void }) {
  const [items, setItems] = useState<MessageItem[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [searching, setSearching] = useState(false);
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const r = await api.list(folder, query);
      setItems(r.items);
      setNext(r.nextBefore);
      refreshCounts();
    } catch (e) {
      setError((e as Error).message);
      setItems([]);
    }
  }, [folder, query, refreshCounts]);

  useEffect(() => {
    setItems(null);
    load();
  }, [load]);

  useEffect(() => {
    const t = setTimeout(() => setQuery(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  const more = async () => {
    if (!next) return;
    setLoadingMore(true);
    try {
      const r = await api.list(folder, query, next);
      setItems((cur) => [...(cur || []), ...r.items]);
      setNext(r.nextBefore);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingMore(false);
    }
  };

  const title = folder === "inbox" ? "Hộp thư đến" : "Đã gửi";

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-10 bg-teal-700 text-white shadow">
        {searching ? (
          <div className="flex items-center gap-1 px-2 py-2">
            <IconButton icon={I.back} label="Đóng tìm kiếm" onClick={() => { setSearching(false); setQ(""); }} />
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={`Tìm trong ${title.toLowerCase()}`}
              className="h-10 flex-1 rounded-full bg-white/15 px-4 text-base text-white placeholder-white/70 outline-none"
              enterKeyHint="search"
            />
          </div>
        ) : (
          <div className="flex items-center gap-1 px-3 py-2">
            <h1 className="flex-1 truncate pl-1 text-lg font-semibold">{title}</h1>
            <IconButton icon={I.search} label="Tìm kiếm" onClick={() => setSearching(true)} />
            <IconButton icon={I.refresh} label="Làm mới" onClick={load} />
            <IconButton icon={I.logout} label="Đăng xuất" onClick={onLogout} />
          </div>
        )}
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 pb-36">
        {error && <ErrorBox message={error} onRetry={load} />}
        {items === null ? (
          <Spinner />
        ) : items.length === 0 && !error ? (
          <div className="px-8 py-16 text-center text-slate-500">
            <Icon d={folder === "inbox" ? I.inbox : I.send} className="mx-auto h-12 w-12 text-slate-300" />
            <p className="mt-3 font-medium text-slate-700">{query ? "Không có thư nào khớp" : folder === "inbox" ? "Chưa có thư đến" : "Chưa gửi thư nào"}</p>
            {!query && folder === "inbox" && (
              <p className="mt-1 text-sm">Thư gửi tới địa chỉ @aistockvn.com sẽ xuất hiện ở đây ngay khi được nhận.</p>
            )}
          </div>
        ) : (
          <ul className="divide-y divide-slate-200 bg-white">
            {items.map((m) => {
              const who = folder === "sent" ? `Tới: ${m.to.map(displayName).join(", ")}` : displayName(m.from);
              const bold = folder === "inbox" && !m.isRead;
              return (
                <li key={m.id}>
                  <a href={`#/m/${m.id}`} className="flex gap-3 px-4 py-3 active:bg-slate-100">
                    <Avatar label={folder === "sent" ? displayName(m.to[0]) : displayName(m.from)} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2">
                        <span className={`flex-1 truncate ${bold ? "font-bold text-slate-900" : "text-slate-700"}`}>{who}</span>
                        <span className={`shrink-0 text-xs ${bold ? "font-bold text-teal-700" : "text-slate-500"}`}>{formatDate(m.date)}</span>
                      </div>
                      <div className={`truncate text-sm ${bold ? "font-semibold text-slate-900" : "text-slate-700"}`}>{m.subject || "(Không có tiêu đề)"}</div>
                      <div className="flex items-center gap-1 text-sm text-slate-500">
                        <span className="flex-1 truncate">{m.snippet}</span>
                        {m.hasAttachments && <Icon d={I.clip} className="h-4 w-4 shrink-0" />}
                      </div>
                    </div>
                  </a>
                </li>
              );
            })}
          </ul>
        )}
        {next && (
          <button onClick={more} disabled={loadingMore} className="mx-auto my-4 block rounded-full border border-slate-300 bg-white px-5 py-2 text-sm font-medium">
            {loadingMore ? "Đang tải…" : "Tải thêm thư"}
          </button>
        )}
      </main>

      <a href="#/compose" className="fixed right-4 bottom-24 z-20 flex items-center gap-2 rounded-2xl bg-teal-600 px-5 py-4 font-semibold text-white shadow-lg active:bg-teal-700">
        <Icon d={I.pen} className="h-5 w-5" /> Soạn thư
      </a>

      <nav className="safe-bottom fixed inset-x-0 bottom-0 z-20 border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-3xl">
          {(["inbox", "sent"] as const).map((f) => (
            <a key={f} href={f === "inbox" ? "#/inbox" : "#/sent"} className={`relative flex flex-1 flex-col items-center py-2 text-xs ${folder === f ? "text-teal-700" : "text-slate-500"}`}>
              <span className={`rounded-full px-5 py-1 ${folder === f ? "bg-teal-100" : ""}`}>
                <Icon d={f === "inbox" ? I.inbox : I.send} />
              </span>
              <span className="mt-0.5 font-medium">{f === "inbox" ? "Hộp thư đến" : "Đã gửi"}</span>
              {f === "inbox" && unread > 0 && (
                <span className="absolute top-1 left-1/2 ml-3 rounded-full bg-rose-600 px-1.5 text-[11px] font-bold text-white">{unread > 99 ? "99+" : unread}</span>
              )}
            </a>
          ))}
        </div>
      </nav>
    </div>
  );
}

/* ---------- đọc thư ---------- */

function MailBody({ html, text }: { html: string | null; text: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [showImages, setShowImages] = useState(false);
  const hasRemote = !!html && /<img[^>]+src=["']?https?:/i.test(html);

  if (!html) return <div className="px-4 py-3 text-[15px] leading-relaxed break-words whitespace-pre-wrap">{text || "(Thư trống)"}</div>;

  // Không cho script chạy (sandbox thiếu allow-scripts); ảnh từ xa bị chặn tới khi người dùng cho phép.
  const csp = `default-src 'none'; style-src 'unsafe-inline' https:; font-src https: data:; img-src data: ${showImages ? "https: http:" : ""};`;
  const doc = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;padding:12px 16px;font:15px/1.5 system-ui,sans-serif;color:#0f172a;word-wrap:break-word}img{max-width:100%;height:auto}table{max-width:100%}</style></head><body>${html}</body></html>`;

  const resize = () => {
    const f = ref.current;
    const h = f?.contentDocument?.documentElement?.scrollHeight;
    if (f && h) f.style.height = `${h + 8}px`;
  };

  return (
    <div>
      {hasRemote && !showImages && (
        <button onClick={() => setShowImages(true)} className="mx-4 mb-2 rounded-lg bg-slate-100 px-3 py-2 text-left text-sm text-slate-700">
          Hình ảnh từ bên ngoài đã bị ẩn để bảo vệ quyền riêng tư. <span className="font-semibold text-teal-700">Hiển thị hình ảnh</span>
        </button>
      )}
      <iframe
        key={String(showImages)}
        ref={ref}
        title="Nội dung thư"
        sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
        srcDoc={doc}
        onLoad={() => {
          resize();
          setTimeout(resize, 500);
        }}
        className="block h-40 w-full border-0"
      />
    </div>
  );
}

function MessageView({ id, refreshCounts }: { id: string; refreshCounts: () => void }) {
  const [m, setM] = useState<MessageDetail | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    api.get(id).then((d) => {
      setM(d);
      refreshCounts();
    }, (e) => setError(e.message));
  }, [id, refreshCounts]);
  useEffect(load, [load]);

  const listHash = m?.folder === "sent" ? "#/sent" : "#/inbox";

  return (
    <div className="flex min-h-full flex-col bg-white">
      <header className="sticky top-0 z-10 flex items-center gap-1 border-b border-slate-200 bg-white px-2 py-2">
        <IconButton icon={I.back} label="Quay lại" onClick={() => back(listHash)} />
        <div className="flex-1" />
        {m?.folder === "inbox" && (
          <IconButton
            icon={I.unread}
            label="Đánh dấu chưa đọc"
            onClick={() => api.markRead(id, false).then(() => { refreshCounts(); back("#/inbox"); }, (e) => setError(e.message))}
          />
        )}
      </header>
      {error && <ErrorBox message={error} onRetry={load} />}
      {!m && !error && <Spinner />}
      {m && (
        <main className="mx-auto w-full max-w-3xl flex-1 pb-28">
          <h1 className="px-4 pt-4 text-xl leading-snug font-semibold">{m.subject || "(Không có tiêu đề)"}</h1>
          <div className="flex gap-3 px-4 py-4">
            <Avatar label={displayName(m.from)} />
            <div className="min-w-0 flex-1 text-sm">
              <div className="flex items-baseline gap-2">
                <span className="flex-1 truncate font-semibold">{displayName(m.from)}</span>
                <span className="shrink-0 text-xs text-slate-500">{formatDate(m.date, true)}</span>
              </div>
              {m.from.name && <div className="truncate text-slate-500">{m.from.address}</div>}
              <div className="truncate text-slate-500">tới {addrLine(m.to) || "(không rõ)"}</div>
              {m.cc.length > 0 && <div className="truncate text-slate-500">cc {addrLine(m.cc)}</div>}
            </div>
          </div>
          <MailBody html={m.html} text={m.text} />
          {m.attachments.length > 0 && (
            <div className="mx-4 mt-4 space-y-2">
              <p className="text-sm font-semibold text-slate-600">{m.attachments.length} tệp đính kèm</p>
              {m.attachments.map((a) => (
                <a key={a.index} href={`/api/messages/${m.id}/attachments/${a.index}`} className="flex items-center gap-3 rounded-xl border border-slate-200 p-3 active:bg-slate-50">
                  <Icon d={I.clip} className="h-5 w-5 text-slate-500" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{a.filename}</span>
                    <span className="text-xs text-slate-500">{formatSize(a.size)}</span>
                  </span>
                  <Icon d={I.download} className="h-5 w-5 text-teal-700" />
                </a>
              ))}
            </div>
          )}
        </main>
      )}
      {m && (
        <div className="safe-bottom fixed inset-x-0 bottom-0 border-t border-slate-200 bg-white">
          <div className="mx-auto flex max-w-3xl gap-3 p-3">
            {m.folder === "inbox" && (
              <a href={`#/compose?reply=${m.id}`} className="flex flex-1 items-center justify-center gap-2 rounded-full border border-slate-300 py-3 font-medium active:bg-slate-100">
                <Icon d={I.reply} className="h-5 w-5" /> Trả lời
              </a>
            )}
            <a href={`#/compose?forward=${m.id}`} className="flex flex-1 items-center justify-center gap-2 rounded-full border border-slate-300 py-3 font-medium active:bg-slate-100">
              <Icon d={I.forward} className="h-5 w-5" /> Chuyển tiếp
            </a>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- soạn thư ---------- */

function quote(m: MessageDetail) {
  const head = `Vào ${formatDate(m.date, true)}, ${m.from.name ? `${m.from.name} <${m.from.address}>` : m.from.address} đã viết:`;
  return `\n\n${head}\n${m.text.split("\n").map((l) => `> ${l}`).join("\n")}`;
}

function Compose({ replyTo, forward, config }: { replyTo?: string; forward?: string; config: Config }) {
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [showCc, setShowCc] = useState(false);
  const [subject, setSubject] = useState("");
  const [text, setText] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "sending" | "sent">(replyTo || forward ? "loading" : "idle");
  const [error, setError] = useState("");
  const clientId = useMemo(() => crypto.randomUUID(), []);

  useEffect(() => {
    const src = replyTo || forward;
    if (!src) return;
    api.get(src).then(
      (m) => {
        if (replyTo) {
          setTo((m.replyTo[0] || m.from).address);
          setSubject(/^re:/i.test(m.subject) ? m.subject : `Re: ${m.subject}`);
          setText(quote(m));
        } else {
          setSubject(/^(fwd?|tt):/i.test(m.subject) ? m.subject : `Fwd: ${m.subject}`);
          setText(`\n\n---------- Thư chuyển tiếp ----------\nTừ: ${addrLine([m.from])}\nNgày: ${formatDate(m.date, true)}\nTiêu đề: ${m.subject}\nTới: ${addrLine(m.to)}\n\n${m.text}`);
        }
        setStatus("idle");
      },
      (e) => {
        setError(e.message);
        setStatus("idle");
      },
    );
  }, [replyTo, forward]);

  const send = async () => {
    setError("");
    if (!to.trim()) return setError("Hãy nhập người nhận");
    setStatus("sending");
    try {
      await api.send({ to, cc, subject, text, replyToId: replyTo, clientId });
      setStatus("sent");
      setTimeout(() => go("#/sent"), 800);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Không gửi được, kiểm tra mạng rồi thử lại");
      setStatus("idle");
    }
  };

  const busy = status === "sending" || status === "loading" || status === "sent";
  const field = "w-full bg-transparent py-3 text-base outline-none";

  return (
    <div className="flex min-h-full flex-col bg-white">
      <header className="sticky top-0 z-10 flex items-center gap-1 border-b border-slate-200 bg-white px-2 py-2">
        <IconButton icon={I.close} label="Hủy" onClick={() => back("#/inbox")} />
        <h1 className="flex-1 truncate text-lg font-semibold">{replyTo ? "Trả lời" : forward ? "Chuyển tiếp" : "Soạn thư"}</h1>
        <button
          onClick={send}
          disabled={busy || !config.sendingEnabled}
          className="flex items-center gap-2 rounded-full bg-teal-600 px-5 py-2.5 font-semibold text-white disabled:bg-slate-300"
        >
          <Icon d={I.send} className="h-5 w-5" />
          {status === "sending" ? "Đang gửi…" : status === "sent" ? "Đã gửi" : "Gửi"}
        </button>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1">
        {!config.sendingEnabled && <ErrorBox message="Máy chủ chưa được cấu hình khóa gửi thư (Resend), nên chưa gửi được." />}
        {error && <ErrorBox message={error} />}
        {status === "sent" && <p className="m-4 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">Đã gửi thư.</p>}
        <div className="divide-y divide-slate-200 px-4">
          <div className="flex items-center gap-3 text-slate-500">
            <span className="w-10 text-sm">Từ</span>
            <span className="truncate py-3 text-base text-slate-800">{config.mailbox}</span>
          </div>
          <label className="flex items-center gap-3 text-slate-500">
            <span className="w-10 text-sm">Tới</span>
            <input type="email" multiple inputMode="email" autoCapitalize="off" value={to} onChange={(e) => setTo(e.target.value)} className={`${field} text-slate-900`} />
            {!showCc && (
              <button type="button" onClick={() => setShowCc(true)} className="text-sm font-medium text-teal-700">
                Cc
              </button>
            )}
          </label>
          {showCc && (
            <label className="flex items-center gap-3 text-slate-500">
              <span className="w-10 text-sm">Cc</span>
              <input type="email" multiple inputMode="email" autoCapitalize="off" value={cc} onChange={(e) => setCc(e.target.value)} className={`${field} text-slate-900`} />
            </label>
          )}
          <input placeholder="Tiêu đề" value={subject} onChange={(e) => setSubject(e.target.value)} className={field} />
          <textarea
            placeholder="Soạn thư"
            value={text}
            onChange={(e) => setText(e.target.value)}
            className={`${field} min-h-[50vh] resize-none leading-relaxed`}
            autoFocus={!replyTo && !forward ? false : true}
            onFocus={(e) => replyTo && e.currentTarget.setSelectionRange(0, 0)}
          />
        </div>
      </main>
    </div>
  );
}

/* ---------- khung ứng dụng ---------- */

export default function App() {
  const route = useRoute();
  const [config, setConfig] = useState<Config | null>(null);
  const [user, setUser] = useState<string | null | undefined>(undefined);
  const [unread, setUnread] = useState(0);
  const [fatal, setFatal] = useState("");

  const checkSession = useCallback(() => {
    api.session().then(
      (s) => setUser(s.email),
      (e) => (e instanceof ApiError && e.status === 401 ? setUser(null) : setFatal(e.message)),
    );
  }, []);

  useEffect(() => {
    api.config().then(setConfig, (e) => setFatal(e.message));
    checkSession();
  }, [checkSession]);

  const refreshCounts = useCallback(() => {
    api.counts().then((c) => setUnread(c.unread), () => {});
  }, []);

  if (fatal) return <ErrorBox message={`Không kết nối được máy chủ: ${fatal}`} onRetry={() => location.reload()} />;
  if (!config || user === undefined) return <Spinner />;
  if (!user) return <Login config={config} onDone={checkSession} />;

  const logout = () => api.logout().finally(() => setUser(null));

  switch (route.name) {
    case "message":
      return <MessageView id={route.id} refreshCounts={refreshCounts} />;
    case "compose":
      return <Compose key={`${route.replyTo}-${route.forward}`} replyTo={route.replyTo} forward={route.forward} config={config} />;
    default:
      return <MailList key={route.folder} folder={route.folder} unread={unread} onLogout={logout} refreshCounts={refreshCounts} />;
  }
}
