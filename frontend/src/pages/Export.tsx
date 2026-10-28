import { useState } from "react";
import { api } from "../lib/api";

export default function Export() {
  const [text, setText] = useState("");
  const [copied, setCopied] = useState(false);
  return (
    <section>
      <h1>Export</h1>
      <div className="row wrap">
        <a className="btn" href="/api/export.csv">Download CSV</a>
        <a className="btn" href="/api/export.xlsx">Download XLSX</a>
        <button className="btn ghost" onClick={async () => setText(await api.get<string>("/export/whatsapp"))}>WhatsApp table</button>
      </div>
      {text && (
        <>
          <pre className="ocr">{text}</pre>
          <button className="btn" onClick={async () => { await navigator.clipboard.writeText(text); setCopied(true); }}>{copied ? "Copied" : "Copy"}</button>
        </>
      )}
    </section>
  );
}
