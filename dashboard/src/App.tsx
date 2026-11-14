import { useEffect, useState } from "react";
import Agent from "./pages/Agent";
import Calibration from "./pages/Calibration";
import Clinician from "./pages/Clinician";
import Live from "./pages/Live";
import Log from "./pages/Log";
import Report from "./pages/Report";
import Settings from "./pages/Settings";
import Tests from "./pages/Tests";
import Trends from "./pages/Trends";

type PageName = "live" | "calibration" | "trends" | "log" | "agent" | "report" | "tests" | "settings" | "clinician";

function pageFromHash(): PageName {
  const hash = window.location.hash.replace(/^#/, "");
  if (hash === "/calibration" || hash === "calibration") {
    return "calibration";
  }
  if (hash === "/trends" || hash === "trends") {
    return "trends";
  }
  if (hash === "/log" || hash === "log") {
    return "log";
  }
  if (hash === "/agent" || hash === "agent") {
    return "agent";
  }
  if (hash === "/report" || hash.startsWith("/report/") || hash === "report") {
    return "report";
  }
  if (hash === "/tests" || hash === "tests") {
    return "tests";
  }
  if (hash === "/settings" || hash === "settings") {
    return "settings";
  }
  if (hash === "/clinician" || hash === "clinician") {
    return "clinician";
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
        <a href="#/trends" className={linkClass("trends")} aria-current={page === "trends" ? "page" : undefined}>
          Trends
        </a>
        <a href="#/log" className={linkClass("log")} aria-current={page === "log" ? "page" : undefined}>
          Log
        </a>
        <a href="#/agent" className={linkClass("agent")} aria-current={page === "agent" ? "page" : undefined}>
          Agent
        </a>
        <a href="#/report" className={linkClass("report")} aria-current={page === "report" ? "page" : undefined}>
          Report
        </a>
        <a href="#/tests" className={linkClass("tests")} aria-current={page === "tests" ? "page" : undefined}>
          Tests
        </a>
        <a href="#/settings" className={linkClass("settings")} aria-current={page === "settings" ? "page" : undefined}>
          Settings
        </a>
        <a href="#/clinician" className={linkClass("clinician")} aria-current={page === "clinician" ? "page" : undefined}>
          Clinician
        </a>
      </nav>
      {page === "live" ? <Live /> : null}
      {page === "calibration" ? <Calibration /> : null}
      {page === "trends" ? <Trends /> : null}
      {page === "log" ? <Log /> : null}
      {page === "agent" ? <Agent /> : null}
      {page === "report" ? <Report /> : null}
      {page === "tests" ? <Tests /> : null}
      {page === "settings" ? <Settings /> : null}
      {page === "clinician" ? <Clinician /> : null}
    </>
  );
}
