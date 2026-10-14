import { useEffect, useState } from "react";

import { icons } from "./components/icons";
import { Data } from "./pages/Data";
import { Launch } from "./pages/Launch";
import { Live } from "./pages/Live";
import { RunView, Runs } from "./pages/Runs";
import { StudyView, Studies } from "./pages/Studies";

type Theme = "system" | "light" | "dark";

function useHash(): string[] {
  const read = () => location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const on = () => {
      setParts(read());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return parts;
}

function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem("ql-theme") as Theme) || "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("ql-theme", theme);
    } catch {
      // private windows: the choice just isn't remembered
    }
  }, [theme]);
  return [theme, setTheme];
}

const NAV = [
  { key: "", label: "Live", icon: icons.live },
  { key: "runs", label: "Runs", icon: icons.runs },
  { key: "studies", label: "Studies", icon: icons.studies },
  { key: "launch", label: "Launch", icon: icons.launch },
  { key: "data", label: "Data", icon: icons.data },
];

export function App() {
  const [page = "", arg] = useHash();
  const [theme, setTheme] = useTheme();

  let body;
  if (page === "runs") body = arg ? <RunView id={arg} /> : <Runs />;
  else if (page === "studies") body = arg ? <StudyView study={arg} /> : <Studies />;
  else if (page === "launch") body = <Launch jobId={arg} />;
  else if (page === "data") body = <Data />;
  else body = <Live />;

  return (
    <div className="shell">
      <nav className="rail" aria-label="Console">
        <div className="brand"><b>quantlab</b><span>console</span></div>
        <div className="nav">
          {NAV.map((n) => (
            <a key={n.key} href={`#/${n.key}`} aria-current={page === n.key ? "page" : undefined}>
              {n.icon}
              {n.label}
            </a>
          ))}
        </div>
        <div className="rail-foot">
          <div className="theme-toggle" role="group" aria-label="Theme">
            {(["system", "light", "dark"] as const).map((t) => (
              <button key={t} type="button" aria-pressed={theme === t} onClick={() => setTheme(t)}>{t}</button>
            ))}
          </div>
        </div>
      </nav>
      <main>{body}</main>
    </div>
  );
}
