import { api } from "./lib/api";

function b64ToBytes(b64: string): Uint8Array {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export async function enablePush(): Promise<string> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return "This browser does not support web push. On iPhone, add the app to the home screen first.";
  const { enabled, public_key } = await api.get<{ enabled: boolean; public_key: string | null }>("/push/key");
  if (!enabled || !public_key) return "Push is not configured on the server (VAPID keys / pywebpush). Alerts still show in the app.";
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return "Notifications were not allowed.";
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(public_key) });
  await api.post("/push/subscribe", sub.toJSON());
  return "Notifications on.";
}
