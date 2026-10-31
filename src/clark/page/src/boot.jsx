// Start the page. main.jsx (served by clark) passes the Edit parts; view.jsx (the published file) passes none.
import { render } from "preact";
import { load, show, openPeek, closePeek, setProject, setFilters, peek, project, f } from "./stores/report.js";
import { App } from "./components/App.jsx";
import { workSelection } from "./stores/selection.js";

export function boot(tools) {
  // The peek's own component is #42 and its rows are #36: until they call these, the browser tests do (#63). Each goes through
  // router.js, as a click will.
  window.clarkPage = Object.freeze({ show, openPeek, closePeek, setProject, setFilters, filters: () => f.value, peek: () => peek.value, project: () => project.value, selected: () => workSelection.ids.value.slice(), ...(tools && tools.help ? { help: Object.freeze({ open: tools.help.open, close: tools.help.close, isOpen: tools.help.isOpen }) } : {}) });
  if (tools && tools.help) tools.help.installKeys();
  render(<App tools={tools} />, document.getElementById("app"));
  document.documentElement.dataset.ready = "1";
  // The server puts this run's token in a data block after this script, and a published file (#39) has its data in one: read
  // whichever is there once the whole page is parsed.
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
}
