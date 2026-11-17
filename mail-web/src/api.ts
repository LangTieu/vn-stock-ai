export type Addr = { address: string; name: string };

export type MessageItem = {
  id: string;
  folder: "inbox" | "sent";
  from: Addr;
  to: Addr[];
  subject: string;
  snippet: string;
  date: number;
  isRead: boolean;
  hasAttachments: boolean;
};

export type MessageDetail = MessageItem & {
  cc: Addr[];
  replyTo: Addr[];
  messageId: string | null;
  text: string;
  html: string | null;
  attachments: { index: number; filename: string; mimeType: string; size: number }[];
};

export type Config = { googleClientId: string; devLogin: boolean; mailbox: string; sendingEnabled: boolean };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Mail-Client": "1", ...(init.headers || {}) },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, (data as { error?: string }).error || `Lỗi ${res.status}`);
  return data as T;
}

export const api = {
  config: () => call<Config>("/api/config"),
  session: () => call<{ email: string; mailbox: string }>("/api/session"),
  loginGoogle: (credential: string) =>
    call<{ email: string }>("/api/auth/google", { method: "POST", body: JSON.stringify({ credential }) }),
  loginDev: () => call<{ email: string }>("/api/auth/dev", { method: "POST" }),
  logout: () => call("/api/logout", { method: "POST" }),
  list: (folder: string, q: string, before?: number | null) => {
    const p = new URLSearchParams({ folder });
    if (q) p.set("q", q);
    if (before) p.set("before", String(before));
    return call<{ items: MessageItem[]; nextBefore: number | null }>(`/api/messages?${p}`);
  },
  counts: () => call<{ unread: number }>("/api/counts"),
  get: (id: string) => call<MessageDetail>(`/api/messages/${id}`),
  markRead: (id: string, read: boolean) =>
    call(`/api/messages/${id}/read`, { method: "POST", body: JSON.stringify({ read }) }),
  send: (body: { to: string; cc: string; subject: string; text: string; replyToId?: string; clientId: string }) =>
    call<{ id: string }>("/api/send", { method: "POST", body: JSON.stringify(body) }),
};
