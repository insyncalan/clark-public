// The browser tests' way into the page (#63, #42): window.clarkPage. Only the test build (main-test.jsx) imports this file, so
// neither the served page nor a published file carries it. `tools` is what Edit adds; Help (#82) is among them.
import { show, openPeek, closePeek, setProject, setFilters, peek, project, f } from "./stores/report.js";

export function install(tools) {
  const help = tools && tools.help ? { help: Object.freeze({ open: tools.help.open, close: tools.help.close, isOpen: tools.help.isOpen }) } : {};
  window.clarkPage = Object.freeze({ show, openPeek, closePeek, setProject, setFilters, filters: () => f.value, peek: () => peek.value, project: () => project.value, ...help });
}
