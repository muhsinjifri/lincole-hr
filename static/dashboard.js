(function () {
  const es = new EventSource("/api/events/stream");

  function labelForCount(n) {
    const w = n === 1 ? "response" : "responses";
    return `${n} ${w}`;
  }

  function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function setText(el, text) {
    if (!el) return;
    clear(el);
    el.appendChild(document.createTextNode(text == null ? "" : String(text)));
  }

  function renderDepartment(deptBody, data) {
    if (!deptBody) return;
    clear(deptBody);
    const label = document.getElementById("live-dept-label");
    const root = document.getElementById("dept-card-root");
    if (!data.department_field_id) {
      if (root) root.dataset.muted = "";
      setText(
        label,
        "Department",
      );
      const p = document.createElement("p");
      p.className = "card-empty";
      p.appendChild(
        document.createTextNode(
          "No department column detected. Rename a field to include Department, or set JOTFORM_DEPARTMENT_FIELD_ID in .env.",
        ),
      );
      deptBody.appendChild(p);
      return;
    }
    if (root) delete root.dataset.muted;

    const hdr = data.columns.find((c) => c[0] === data.department_field_id);
    setText(label, hdr ? hdr[1] : "Department");

    const rows = data.department_breakdown || [];
    if (!rows.length) {
      const p = document.createElement("p");
      p.className = "card-empty";
      p.appendChild(document.createTextNode("No department values on these rows yet."));
      deptBody.appendChild(p);
      return;
    }

    const max = Math.max(...rows.map((r) => r.count), 0);
    const ul = document.createElement("ul");
    ul.className = "dept-list";
    ul.setAttribute("aria-label", "Counts by department");
    ul.id = "live-dept-list";
    for (const item of rows) {
      const li = document.createElement("li");
      li.className = "dept-row";

      const top = document.createElement("div");
      top.className = "dept-top";
      const name = document.createElement("span");
      name.className = "dept-name";
      name.textContent = item.name;
      const cnt = document.createElement("span");
      cnt.className = "dept-count";
      cnt.textContent = String(item.count);
      top.appendChild(name);
      top.appendChild(cnt);

      const track = document.createElement("div");
      track.className = "bar-track";
      track.setAttribute("role", "presentation");
      const fill = document.createElement("div");
      fill.className = "bar-fill";
      const pct = max > 0 ? Math.round((1000 * item.count) / max) / 10 : 0;
      fill.style.width = `${pct}%`;

      track.appendChild(fill);
      li.appendChild(top);
      li.appendChild(track);
      ul.appendChild(li);
    }
    deptBody.appendChild(ul);
  }

  function renderTable(data) {
    const theadRow = document.getElementById("live-thead-row");
    const tbody = document.getElementById("live-tbody");
    if (!theadRow || !tbody) return;

    clear(theadRow);
    for (const [, label] of data.columns) {
      const th = document.createElement("th");
      th.textContent = label;
      theadRow.appendChild(th);
    }

    clear(tbody);
    const cols = data.columns.map((c) => c[0]);
    if (!data.rows || !data.rows.length) {
      const tr = document.createElement("tr");
      tr.className = "empty-row";
      const td = document.createElement("td");
      td.className = "empty-cell";
      td.colSpan = Math.max(cols.length, 1);
      td.textContent = "No submissions yet.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    for (const row of data.rows) {
      const tr = document.createElement("tr");
      for (const key of cols) {
        const td = document.createElement("td");
        td.textContent = row[key] == null ? "" : String(row[key]);
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  }

  async function refreshDashboard() {
    const res = await fetch("/api/submissions", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();

    const title = data.form_title && String(data.form_title).trim();
    setText(document.getElementById("live-hero-title"), title || "Form submissions");
    setText(document.getElementById("live-stat-total"), String(data.submission_count ?? 0));
    setText(document.getElementById("live-pill-total"), labelForCount(Number(data.submission_count ?? 0)));

    renderDepartment(document.getElementById("live-dept-body"), data);
    renderTable(data);
  }

  es.addEventListener("message", async (ev) => {
    let payload;
    try {
      payload = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (!payload || payload.type === "ready") return;
    if (payload.type === "submission") {
      await refreshDashboard();
    }
  });

  es.addEventListener("error", () => {
    /* browser will retry EventSource */
  });
})();
