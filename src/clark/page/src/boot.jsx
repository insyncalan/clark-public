// Start the page. main.jsx (served by clark) passes the Edit parts; view.jsx (the published file) passes none.
import { render } from "preact";
import { load } from "./stores/report.js";
import { App } from "./components/App.jsx";

export function boot(tools) {
  if (tools && tools.help) tools.help.installKeys();
  render(<App tools={tools} />, document.getElementById("app"));
  document.documentElement.dataset.ready = "1";
  // The server puts this run's token in a data block after this script, and a published file (#39) has its data in one: read
  // whichever is there once the whole page is parsed.
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
}
