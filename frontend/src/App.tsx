import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./lib/api";
import { useData } from "./lib/useData";
import Builder from "./pages/Builder";
import Closing from "./pages/Closing";
import Export from "./pages/Export";
import Families from "./pages/Families";
import Login from "./pages/Login";
import LotDetail from "./pages/LotDetail";
import PedigreeReview from "./pages/PedigreeReview";
import Settings from "./pages/Settings";
import Sources from "./pages/Sources";
import Suggestions from "./pages/Suggestions";
import Watchlist from "./pages/Watchlist";

const NAV: [string, string][] = [
  ["/", "Suggestions"], ["/closing", "Closing soon"], ["/watchlist", "Watchlist"], ["/families", "Families"],
  ["/builder", "Family Builder"], ["/pedigree", "Pedigree review"], ["/sources", "Sources"], ["/settings", "Settings"], ["/export", "Export"],
];

function AlertBell() {
  const { data } = useData<{ id: number }[]>("/alerts?unread=true", 30_000);
  return <NavLink to="/watchlist" className="bell">🔔{data && data.length > 0 ? <b>{data.length}</b> : null}</NavLink>;
}

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const check = () => api.get("/me").then(() => setAuthed(true)).catch(() => setAuthed(false));
  useEffect(() => {
    check();
    const onAuth = () => setAuthed(false);
    window.addEventListener("olr-auth", onAuth);
    return () => window.removeEventListener("olr-auth", onAuth);
  }, []);
  if (authed === null) return null;
  if (!authed) return <Login onDone={() => setAuthed(true)} />;
  return (
    <div className="app">
      <header>
        <span className="brand">OLR Scout</span>
        <nav>{NAV.map(([to, label]) => <NavLink key={to} to={to} end={to === "/"}>{label}</NavLink>)}</nav>
        <AlertBell />
        <button className="btn ghost small" onClick={async () => { await api.post("/logout"); setAuthed(false); }}>Log out</button>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Suggestions />} />
          <Route path="/closing" element={<Closing />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/lot/:id" element={<LotDetail />} />
          <Route path="/families" element={<Families />} />
          <Route path="/builder" element={<Builder />} />
          <Route path="/pedigree" element={<PedigreeReview />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/export" element={<Export />} />
        </Routes>
      </main>
    </div>
  );
}
