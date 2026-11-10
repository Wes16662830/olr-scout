import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles.css";

if ("serviceWorker" in navigator) {
  const base = import.meta.env.BASE_URL;
  window.addEventListener("load", () => navigator.serviceWorker.register(`${base}sw.js`, { scope: base }).catch(() => undefined));
}

// The current screens loaded: allow the stale-page reload again after a future update.
try { sessionStorage.removeItem("olr-stale-reload"); } catch { /* private mode */ }

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, "")}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
