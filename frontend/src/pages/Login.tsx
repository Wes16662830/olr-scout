import { FormEvent, useState } from "react";
import { api } from "../lib/api";

export default function Login({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.post("/login", { password: pw }); onDone(); }
    catch (x) { setErr((x as Error).message); }
  };
  return (
    <form className="login" onSubmit={submit}>
      <h1>OLR Scout</h1>
      <input type="password" autoFocus placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" />
      <button className="btn" type="submit">Log in</button>
      {err && <div className="error">{err}</div>}
    </form>
  );
}
