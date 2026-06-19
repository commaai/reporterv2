let gridApi = null;
let selectedRuns = new Set();
let restoring = true;  // until the first restore runs, so a shared ?q= link isn't wiped on init

// table state in the URL, github-style: ?q=command:gill trainer:path  (+ &page= &selected=)
const URL_FILTERS = {command: "text", trainer: "text", run_id: "text", last_step: "number"};
const urlFilter = (t, v) => ({filterType: t, type: t === "number" ? "equals" : "contains", filter: t === "number" ? Number(v) : v});

function initGrid(load = true) {
  function fmtDuration(s) {
    if (s == null) return "";
    s = Number(s);
    if (!Number.isFinite(s) || s < 0) s = 0;
    s = Math.floor(s);
    let d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }
  function getCommandDisplay(data) {
    let name = data?.display_name || "";
    let commandText = data?.command || "";
    let extraFields = [data?.hostname, data?.slurm_job_id, data?.slurm_job_name, data?.branch]
      .map(v => (v == null ? "" : String(v).trim()))
      .filter(Boolean);
    if (extraFields.length) commandText += `${commandText ? " " : ""}# ${extraFields.join(" ")}`;
    let fullText = `${name}${name && commandText ? " " : ""}${commandText}`;
    return {name, commandText, fullText};
  }
  const colDefs = [
    {headerCheckboxSelection: true, checkboxSelection: true, width: 50, suppressSizeToFit: true, sortable: false, filter: false},
    {field: "created_at", headerName: "Started", width: 175, suppressSizeToFit: true, sort: "desc",
      valueFormatter: p => p.value ? new Date(p.value * 1000).toLocaleString(undefined, {year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}) : ""},
    {headerName: "Duration", width: 110, suppressSizeToFit: true, valueGetter: p => {
        let d = p.data;
        let start = Number(d.created_at);
        if (!Number.isFinite(start) || start <= 0) return null;
        let end = d.last_timestamp == null ? Date.now() / 1000 : Number(d.last_timestamp);
        if (!Number.isFinite(end)) return 0;
        return Math.max(0, end - start);
      },
      valueFormatter: p => fmtDuration(p.value),
      cellRenderer: p => {
        let duration = p.valueFormatted || fmtDuration(p.value);
        if (!duration) return "";
        let wrapper = document.createElement("span");
        wrapper.style.cssText = "display:inline-flex;align-items:center;gap:6px";
        if ((p.data?.status || "").toLowerCase() === "running") {
          let dot = document.createElement("span");
          dot.style.cssText = "width:7px;height:7px;border-radius:50%;background:#16a34a;display:inline-block;flex:0 0 auto";
          wrapper.appendChild(dot);
        }
        let label = document.createElement("span");
        label.textContent = duration;
        wrapper.appendChild(label);
        return wrapper;
      },
      type: "numericColumn"},
    {field: "last_step", headerName: "Steps", width: 90, suppressSizeToFit: true, type: "numericColumn"},
    {field: "run_id", headerName: "Run ID", flex: 1, minWidth: 115, maxWidth: 310,
      cellRenderer: p => {
        let a = document.createElement("a");
        a.href = "/" + p.data.run_id;
        a.textContent = p.value;
        return a;
      }},
    {field: "trainer", headerName: "Trainer", width: 140, suppressSizeToFit: true},
    {field: "command", headerName: "Command", flex: 2, wrapText: true, autoHeight: true,
      filterValueGetter: p => getCommandDisplay(p.data).fullText,
      cellRenderer: p => {
        let div = document.createElement("div");
        div.style.cssText = "white-space:normal;line-height:1.4";
        let {name, commandText} = getCommandDisplay(p.data);
        if (name) {
          let b = document.createElement("b");
          b.textContent = name;
          div.appendChild(b);
        }
        if (name && commandText) div.appendChild(document.createTextNode(" "));
        div.appendChild(document.createTextNode(commandText));
        return div;
      }},
  ];
  const gridOptions = {
    columnDefs: colDefs,
    rowSelection: "multiple",
    suppressRowClickSelection: true,
    animateRows: true,
    defaultColDef: {sortable: true, resizable: true, filter: true, floatingFilter: true},
    onSelectionChanged: () => {
      selectedRuns = new Set(gridApi.getSelectedRows().map(r => r.run_id));
      updateCompareBar();
    },
    enableCellTextSelection: true,
    ensureDomOrder: true,
    suppressColumnVirtualisation: true,
    suppressRowVirtualisation: true,
    rowModelType: "clientSide",
    autoSizeStrategy: {type: "fitGridWidth"},
    pagination: true,
    paginationPageSize: 100,
    paginationPageSizeSelector: false,
    getRowId: p => p.data.run_id,
    onStateUpdated: gridStateToUrl,
  };
  gridApi = agGrid.createGrid(document.getElementById("table-view"), gridOptions);
  updateCompareBar();
  if (load) loadRuns();
}

function updateCompareBar() {
  document.getElementById("compare-count").textContent = `${selectedRuns.size} selected`;
  let hasSelection = selectedRuns.size > 0;
  for (let btn of document.querySelectorAll("#compare-bar button")) btn.disabled = !hasSelection;
  let link = document.getElementById("compare-link");
  if (hasSelection) {
    link.href = "/" + [...selectedRuns].join("_");
    link.classList.remove("disabled");
  } else {
    link.removeAttribute("href");
    link.classList.add("disabled");
  }
}

function gridStateToUrl(e) {
  if (restoring) return;
  let fm = e.api.getFilterModel(), tokens = [];
  for (let col of Object.keys(URL_FILTERS)) {
    let f = fm[col];
    if (f?.filter != null && (f.type === "contains" || f.type === "equals"))
      tokens.push(`${col}:${/\s/.test(f.filter) ? `"${f.filter}"` : f.filter}`);
  }
  let params = new URLSearchParams();
  if (tokens.length) params.set("q", tokens.join(" "));
  let page = e.api.paginationGetCurrentPage();
  if (page > 0) params.set("page", page + 1);
  let selected = e.api.getSelectedRows().map(r => r.run_id);
  if (selected.length) params.set("selected", selected.join(","));
  let qs = params.toString().replace(/%3A/gi, ":").replace(/%2C/gi, ",");  // : and , stay literal
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

function restoreStateFromUrl() {
  restoring = true;
  let params = new URLSearchParams(location.search), fm = {};
  for (let tok of (params.get("q") || "").match(/(?:[^\s"]+|"[^"]*")+/g) || []) {
    let i = tok.indexOf(":");
    let col = i > 0 ? tok.slice(0, i) : "command";  // bare word filters command, github-style
    let val = (i > 0 ? tok.slice(i + 1) : tok).replace(/^"|"$/g, "");
    if (URL_FILTERS[col]) fm[col] = urlFilter(URL_FILTERS[col], val);
  }
  gridApi.setFilterModel(Object.keys(fm).length ? fm : null);
  if (params.has("page")) gridApi.paginationGoToPage(params.get("page") - 1);
  let selected = new Set((params.get("selected") || "").split(",").filter(Boolean));
  gridApi.forEachNode(n => n.setSelected(selected.has(n.data.run_id)));
  restoring = false;
}

async function loadRuns(search) {
  await fetch("/api/reindex", {method: "POST"});
  let url = "/api/runs";
  if (search) url += `&search=${encodeURIComponent(search)}`;
  let resp = await fetch(url);
  let data = await resp.json();
  gridApi.setGridOption("rowData", data.runs);
  restoreStateFromUrl();
  updateIndexStatus();
}

async function updateIndexStatus() {
  try {
    let resp = await fetch("/api/index_status");
    let data = await resp.json();
    let el = document.getElementById("index-status");
    if (!el) {
      el = document.createElement("span");
      el.id = "index-status";
      el.style.cssText = "font-size:12px;color:#7f8fa6;margin-left:auto";
      document.getElementById("header").appendChild(el);
    }
    if (data.last_updated) {
      let ts = new Date(data.last_updated * 1000).toLocaleString();
      let elapsed = data.elapsed != null ? ` (in ${(data.elapsed * 1000).toFixed(0)}ms)` : "";
      el.textContent = `index updated ${ts}${elapsed}`;
    } else {
      el.textContent = "index not yet built";
    }
  } catch(e) {}
}

function clearSelection() {
  gridApi.deselectAll();
  selectedRuns.clear();
  updateCompareBar();
}

async function deleteSelected() {
  if (!selectedRuns.size) return;
  if (!confirm(`delete ${selectedRuns.size} run${selectedRuns.size > 1 ? "s" : ""}?`)) return;
  await Promise.all([...selectedRuns].map(id => fetch(`/api/runs/${id}`, {method: "DELETE"})));
  clearSelection();
  loadRuns();
}

function showTable() {
  document.getElementById("table-view").style.display = "block";
  document.getElementById("compare-bar").style.display = "flex";
  document.getElementById("experiment-view").style.display = "none";
  updateCompareBar();
  document.getElementById("nav-back").style.display = "none";
  let indexStatus = document.getElementById("index-status");
  if (indexStatus) indexStatus.style.display = "";
  let expStatus = document.getElementById("experiment-status");
  if (expStatus) expStatus.remove();
  loadRuns();
}
