import { useEffect, useState } from "react";
import Calibration from "./pages/Calibration";
import Live from "./pages/Live";

type PageName = "live" | "calibration";

function pageFromHash(): PageName {
  const hash = window.location.hash.replace(/^#/, "");
  if (hash === "/calibration" || hash === "calibration") {
    return "calibration";
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
      <nav className="mx-auto flex max-w-6xl gap-2 px-4 pt-6 sm:px-6" aria-label="Pages">
        <a href="#/" className={linkClass("live")} aria-current={page === "live" ? "page" : undefined}>
          Live
        </a>
        <a
          href="#/calibration"
          className={linkClass("calibration")}
          aria-current={page === "calibration" ? "page" : undefined}
        >
          Calibration
        </a>
      </nav>
      {page === "calibration" ? <Calibration /> : <Live />}
    </>
  );
}
