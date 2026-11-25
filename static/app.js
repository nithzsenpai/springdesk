const workspace = document.querySelector("#workspace");
const navigation = document.querySelector("#projects");
const notice = document.querySelector("#notice");
const dialog = document.querySelector("#editor");
const form = document.querySelector("#edit-form");
const formError = document.querySelector("#form-error");
const submit = form.querySelector('[type="submit"]');
const statuses = ["Backlog", "In progress", "Done"];

let projectId = null;
let editor = null;
let requestVersion = 0;
let reportTimer;
let reportRequestVersion = 0;
let reportsOpen = false;
const expandedStories = new Set();

async function api(path, method = "GET", body) {
  const response = await fetch("/api" + path, {
    method,
    ...(body && { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(error => error.loc.at(-1) + " — " + error.msg).join(". ")
      : data.detail;
    throw new Error(detail || "Request failed (" + response.status + ")");
  }
  return data;
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(text, action, className) {
  const node = element("button", text, className);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

function showError(error, target = notice) {
  target.textContent = error.message;
  target.hidden = false;
}

function edit(kind, path, item) {
  editor = { path, method: item ? "PUT" : "POST" };
  form.reset();
  formError.hidden = true;
  document.querySelector("#editor-title").textContent = (item ? "Edit " : "New ") + kind;
  const fields = {
    project: [],
    "user story": ["status", "priority"],
    task: ["status", "assignee"],
  };
  for (const label of form.querySelectorAll("[data-field]")) {
    const field = label.dataset.field;
    label.hidden = !fields[kind].includes(field);
    form.elements[field].disabled = label.hidden;
  }
  form.elements.priority.value = "Medium";
  for (const field of ["title", "description", ...fields[kind]]) {
    if (item) form.elements[field].value = item[field];
  }
  dialog.showModal();
}

function taskRow(task) {
  const row = element("div", undefined, "task");
  row.append(
    element("strong", task.title),
    element("p", task.status + " · " + (task.assignee || "Unassigned")),
  );
  if (task.description) row.append(element("p", task.description));
  row.append(button("Edit task", () => edit("task", "/tasks/" + task.id, task)));
  return row;
}

function storyCard(story) {
  const card = element("article", undefined, "card");
  const actions = element("div", undefined, "actions");
  actions.append(
    button("Edit story", () => edit("user story", "/stories/" + story.id, story)),
    button("+ Task", () => {
      expandedStories.add(story.id);
      edit("task", "/stories/" + story.id + "/tasks");
    }),
  );
  const tasks = element("details");
  tasks.open = expandedStories.has(story.id);
  tasks.addEventListener("toggle", () => {
    if (tasks.open) expandedStories.add(story.id);
    else expandedStories.delete(story.id);
  });
  const done = story.tasks.filter(task => task.status === "Done").length;
  tasks.append(element("summary", "Tasks · " + done + "/" + story.tasks.length + " done"));
  if (!story.tasks.length) tasks.append(element("p", "No tasks yet."));
  for (const task of story.tasks) tasks.append(taskRow(task));
  card.append(element("span", story.priority + " priority", "badge " + story.priority.toLowerCase()),
    element("h3", story.title));
  if (story.description) card.append(element("p", story.description));
  card.append(tasks, actions);
  return card;
}

function renderBoard(project) {
  const path = "/projects/" + project.id;
  const header = element("header");
  const heading = element("div");
  heading.append(element("h1", project.title));
  if (project.description) heading.append(element("p", project.description));
  const actions = element("div", undefined, "actions");
  actions.append(
    button("Edit project", () => edit("project", path, project)),
    button("+ New story", () => edit("user story", path + "/stories"), "primary"),
  );
  header.append(heading, actions);
  const stats = element("section", undefined, "stats");
  stats.setAttribute("aria-label", "Project totals");
  const tasks = project.stories.flatMap(story => story.tasks);
  for (const [label, value] of [
    ["Stories", project.stories.length],
    ["Tasks", tasks.length],
    ["Tasks done", tasks.filter(task => task.status === "Done").length],
  ]) {
    const stat = element("div", undefined, "stat");
    stat.append(element("strong", String(value)), element("p", label));
    stats.append(stat);
  }

  const board = element("section", undefined, "board");
  board.setAttribute("aria-label", "Story board");
  for (const status of statuses) {
    const lane = element("section", undefined, "lane");
    const stories = project.stories.filter(story => story.status === status);
    const label = element("h2");
    label.append(element("span", "", "dot"), document.createTextNode(status),
      element("span", String(stories.length), "count"));
    lane.append(label);
    for (const story of stories) lane.append(storyCard(story));
    if (!stories.length) lane.append(element("p", "No stories"));
    board.append(lane);
  }

  const reports = element("section", undefined, "reports");
  const reportList = element("div");
  const generate = button("Generate report", async () => {
    generate.disabled = true;
    notice.hidden = true;
    try {
      await api(path + "/reports", "POST");
      refreshReports(project.id, reportList);
    } catch (error) {
      if (reports.isConnected) showError(error);
    } finally {
      generate.disabled = false;
    }
  });
  const history = element("details");
  history.open = reportsOpen;
  history.addEventListener("toggle", () => { reportsOpen = history.open; });
  history.append(element("summary", "Report history"), reportList);
  reports.append(element("h2", "Progress reports"), generate, history);
  workspace.replaceChildren(header, stats, board, reports);
  refreshReports(project.id, reportList);
}

async function refreshReports(id, list) {
  if (!list.isConnected || id !== projectId) return;
  const version = ++reportRequestVersion;
  clearTimeout(reportTimer);
  try {
    const reports = await api("/projects/" + id + "/reports");
    if (!list.isConnected || id !== projectId || version !== reportRequestVersion) return;
    list.replaceChildren();
    if (!reports.length) list.append(element("p", "No reports yet."));
    for (const report of reports) {
      const row = element("div", undefined, "report-row");
      const date = new Date(report.created_at * 1000).toLocaleString();
      row.append(element("strong", "Report #" + report.id + " · " + date));
      if (report.result) {
        for (const group of ["stories", "tasks"]) {
          const totals = statuses.map(status => status + " " + (report.result[group][status] ?? 0));
          row.append(element("p", (group === "stories" ? "Stories" : "Tasks") + " · " + totals.join(" · ")));
        }
      } else {
        row.append(element("p", report.status === "failed"
          ? "Failed after " + report.attempts + " attempts. Generate a new report to try again."
          : "Queued · " + report.attempts + " attempts"));
      }
      list.append(row);
    }
    if (reports.some(report => report.status === "queued")) {
      reportTimer = setTimeout(() => refreshReports(id, list), 1500);
    }
  } catch (error) {
    if (list.isConnected && version === reportRequestVersion) {
      list.replaceChildren(element("p", error.message), button("Refresh reports", () => refreshReports(id, list)));
    }
  }
}

async function load(id = projectId) {
  const version = ++requestVersion;
  clearTimeout(reportTimer);
  workspace.setAttribute("aria-busy", "true");
  notice.hidden = true;
  try {
    const projects = await api("/projects");
    if (version !== requestVersion) return;
    projectId = projects.find(project => project.id === id)?.id ?? projects[0]?.id ?? null;
    navigation.replaceChildren();
    for (const project of projects) {
      const link = button(project.title, () => load(project.id));
      link.setAttribute("aria-current", String(project.id === projectId));
      navigation.append(link);
    }
    if (projectId === null) {
      const empty = element("section", undefined, "empty");
      empty.append(element("h1", "Start a project"), element("p", "Create a project to organize user stories and their tasks."),
        button("+ New project", () => edit("project", "/projects"), "primary"));
      workspace.replaceChildren(empty);
      return;
    }
    const project = await api("/projects/" + projectId);
    if (version === requestVersion) renderBoard(project);
  } catch (error) {
    if (version === requestVersion) {
      showError(error);
      workspace.replaceChildren(button("Retry loading workspace", () => load(id)));
    }
  } finally {
    if (version === requestVersion) workspace.setAttribute("aria-busy", "false");
  }
}

document.querySelector("#new-project").addEventListener("click", () => edit("project", "/projects"));
document.querySelector("#cancel").addEventListener("click", () => dialog.close());
dialog.addEventListener("cancel", event => {
  if (submit.disabled) event.preventDefault();
});
form.addEventListener("submit", async event => {
  event.preventDefault();
  const { path, method } = editor;
  formError.hidden = true;
  submit.disabled = true;
  document.querySelector("#cancel").disabled = true;
  try {
    const result = await api(path, method, Object.fromEntries(new FormData(form)));
    dialog.close();
    await load(path === "/projects" ? result.id : projectId);
  } catch (error) {
    showError(error, formError);
  } finally {
    submit.disabled = false;
    document.querySelector("#cancel").disabled = false;
  }
});
load();
