import { useState } from "react";
import { useAuctionFilter } from "../components/AuctionFilter";
import { api, DEMO } from "../lib/api";

async function demoDownload(e: React.MouseEvent<HTMLAnchorElement>, kind: "csv" | "xlsx") {
  if (!DEMO) return;
  e.preventDefault();
  const { demoExports } = await import("../demo/mock");
  const a = document.createElement("a");
  a.href = demoExports[kind]();
  a.download = `olr-scout-suggestions.${kind}`;
  a.click();
}

export default function Export() {
  const { selected } = useAuctionFilter();
  const q = selected.length ? `?auctions=${encodeURIComponent(selected.join(","))}` : "";
  const [text, setText] = useState("");
  const [copied, setCopied] = useState(false);
  return (
    <section>
      <h1>Export</h1>
      <p className="muted">{selected.length ? `Only the ${selected.length} auction(s) selected on Suggestions.` : "All auctions (pick specific ones on Suggestions)."}</p>
      <div className="row wrap">
        <a className="btn" href={`/api/export.csv${q}`} download="olr-scout-suggestions.csv" onClick={(e) => demoDownload(e, "csv")}>Download CSV</a>
        <a className="btn" href={`/api/export.xlsx${q}`} download="olr-scout-suggestions.xlsx" onClick={(e) => demoDownload(e, "xlsx")}>Download XLSX</a>
        <button className="btn ghost" onClick={async () => setText(await api.get<string>(`/export/whatsapp${q}`))}>WhatsApp table</button>
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
