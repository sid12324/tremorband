import { useEffect, useState } from "react";
import Analysis from "./pages/Analysis";
import Live from "./pages/Live";
import Session from "./pages/Session";

type PageName = "live" | "session" | "analysis";

function pageFromHash(): PageName {
  const hash = window.location.hash.replace(/^#/, "");
  if (hash === "/session" || hash === "session") {
    return "session";
  }
  if (hash === "/analysis" || hash === "analysis") {
    return "analysis";
  }
  return "live";
}

export default function App() {
  const [page, setPage] = useState<PageName>(pageFromHash);

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const linkClass = (name: PageName) =>
    `inline-flex min-h-12 items-center rounded-lg border-2 border-[#121212] px-4 text-lg font-semibold ${
      page === name ? "bg-[#121212] text-white" : "bg-white text-[#121212]"
    }`;

  return (
    <>
      <nav className="mx-auto flex max-w-6xl flex-wrap gap-2 px-4 pt-6 sm:px-6" aria-label="Pages">
        <a href="#/live" className={linkClass("live")} aria-current={page === "live" ? "page" : undefined}>
          Live
        </a>
        <a href="#/session" className={linkClass("session")} aria-current={page === "session" ? "page" : undefined}>
          Session
        </a>
        <a
          href="#/analysis"
          className={linkClass("analysis")}
          aria-current={page === "analysis" ? "page" : undefined}
        >
          Analysis
        </a>
      </nav>
      {page === "live" ? <Live /> : null}
      {page === "session" ? <Session /> : null}
      {page === "analysis" ? <Analysis /> : null}
    </>
  );
}
