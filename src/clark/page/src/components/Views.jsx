// The other pages as a shell: Work items and the Dashboard (Dashboard.jsx) sit in one frame of the same width (
// "Make Dashboard same width as work items"). The Work items list is WorkItems.jsx (#36).
import { status, message, project, projects, projectsState, openProject, tryAgain } from "../stores/report.js";

import { MsBlock } from "./MsBlock.jsx";

function Empty({ title, children, action }) {
  return <section class="frame empty"><h1>{title}</h1><p class="muted">{children}</p>{action}</section>;
}

export function Milestones({ tools }) {
  const More = tools && tools.MilestoneMore;      // the owner's extra block under the Plan view (#136): Edit only, so a published page has none
  return (
    <section class="frame milestones" id="milestones">
      <h1>Milestones</h1>
      <MsBlock place="page" />
      {More ? <More /> : null}
    </section>
  );
}

export function Settings({ tools }) {
  const ClientFolder = tools && tools.ClientFolder;      // the client folder (#43); the rest of Settings is FR-1
  const Personal = tools && tools.Personal;            // Settings › Personal (#45): Edit's page only; a published file has no Settings
  const Safety = tools && tools.Safety;                  // the backups (#111); a published file has none
  const AskSettings = tools && tools.AskSettings;        // asking: the switch and its folders (#47)
  const AiSettings = tools && tools.AiSettings;          // AI sign-in: Claude and OpenAI, and the model (#54)
  return (
    <>
      <Empty title="Settings">Settings are not ready yet.</Empty>
      {ClientFolder ? <ClientFolder /> : null}
      {Personal ? <Personal /> : null}
      {Safety ? <Safety /> : null}
      {AskSettings ? <AskSettings /> : null}
      {AiSettings ? <AiSettings /> : null}
    </>
  );
}

// The "No project open" screen: the projects to choose from or, when there are none (or the list could not be read), what to do.
function NoProject() {
  const list = projects.value, state = projectsState.value;
  if (state === "loading") return <Empty title="No project open">Looking for projects.</Empty>;
  if (state === "failed") return <Empty title="No project open" action={<button type="button" class="again" onClick={tryAgain}>Try again</button>}>{message.value}</Empty>;
  if (!list.length) {
    return (
      <section class="frame empty">
        <h1>No project open</h1>
        <p class="muted">There are no projects yet.</p>
        <p class="muted">To look around with made-up projects, close clark and start it again with <code>python3 -m clark --demo</code>.</p>
      </section>
    );
  }
  return (
    <section class="frame empty">
      <h1>No project open</h1>
      <p class="muted">Choose a project.</p>
      <ul class="plain choose">{list.map((p) => <li key={p.code}><button type="button" class="link" onClick={() => openProject(p.code)}>{p.name}</button> <span class="muted num">{p.code}</span></li>)}</ul>
    </section>
  );
}

export function Gate() {
  const s = status.value;
  if (s === "none") return <NoProject />;
  if (s === "loading") return <Empty title="Loading">Opening {project.value}.</Empty>;
  if (s === "missing") return <Empty title="That project isn't here">{message.value || "Check the project's code."}</Empty>;
  if (s === "failed") return <Empty title="Something went wrong" action={<button type="button" class="again" onClick={tryAgain}>Try again</button>}>{message.value}</Empty>;
  return null;
}
