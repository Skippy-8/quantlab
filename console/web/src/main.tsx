import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { StreamProvider } from "./stream";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <StreamProvider>
      <App />
    </StreamProvider>
  </StrictMode>,
);
