// The page: the top bar and the open view. `tools` is what Edit adds (edit/index.js); the published page passes none.
import { view, status } from "../stores/report.js";
import { TopBar } from "./TopBar.jsx";
import { Milestones, Settings, Gate } from "./Views.jsx";
import { Dashboard } from "./Dashboard.jsx";
import { Peek } from "./Peek.jsx";
import { WorkItems } from "./WorkItems.jsx";

const PAGES = { dashboard: Dashboard, work: WorkItems, milestones: Milestones, settings: Settings };

export function App({ tools }) {
  const Page = PAGES[view.value];
  const Toast = tools && tools.Toast;
  const Layer = tools && tools.HelpLayer;                // Help (#82) sits over the open page; a published file has none
  const body = status.value === "ready" ? <Page tools={tools} /> : <Gate />;
  return (
    <>
      <TopBar tools={tools} />
      <main id="main">{Layer ? <Layer>{body}</Layer> : body}</main>
      {status.value === "ready" ? <Peek tools={tools} /> : null}
      {Toast ? <Toast /> : null}
    </>
  );
}
