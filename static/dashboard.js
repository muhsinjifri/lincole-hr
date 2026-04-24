(function () {
  const es = new EventSource("/api/events/stream");
  let activeTab = "responses";

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

  function renderFormColumns(tbody, columns) {
    if (!tbody) return;
    clear(tbody);
    const list = Array.isArray(columns) ? columns : [];
    if (!list.length) {
      const tr = document.createElement("tr");
      tr.className = "empty-row";
      const td = document.createElement("td");
      td.className = "empty-cell";
      td.colSpan = 3;
      td.textContent = "No form fields returned from Jotform.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    for (const c of list) {
      const tr = document.createElement("tr");
      const tdLabel = document.createElement("td");
      tdLabel.textContent = c && c.name != null ? String(c.name) : "";
      const tdQid = document.createElement("td");
      const code = document.createElement("code");
      code.textContent = c && c.qid != null ? String(c.qid) : "";
      tdQid.appendChild(code);
      const tdKind = document.createElement("td");
      tdKind.textContent = c && c.kind != null ? String(c.kind) : "";
      tr.appendChild(tdLabel);
      tr.appendChild(tdQid);
      tr.appendChild(tdKind);
      tbody.appendChild(tr);
    }
  }

  function renderSections(tbody, sections) {
    if (!tbody) return;
    clear(tbody);
    const list = Array.isArray(sections) ? sections : [];
    if (!list.length) {
      const tr = document.createElement("tr");
      tr.className = "empty-row";
      const td = document.createElement("td");
      td.className = "empty-cell";
      td.colSpan = 3;
      td.innerHTML =
        "No section widgets found. Add a <strong>Heading</strong>, <strong>Section Collapse</strong>, or <strong>Page Break</strong> in Jotform to list them here.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    for (const s of list) {
      const tr = document.createElement("tr");
      const tdName = document.createElement("td");
      tdName.textContent = s && s.name != null ? String(s.name) : "";
      const tdQid = document.createElement("td");
      const code = document.createElement("code");
      code.textContent = s && s.qid != null ? String(s.qid) : "";
      tdQid.appendChild(code);
      const tdKind = document.createElement("td");
      tdKind.textContent = s && s.kind != null ? String(s.kind) : "";
      tr.appendChild(tdName);
      tr.appendChild(tdQid);
      tr.appendChild(tdKind);
      tbody.appendChild(tr);
    }
  }

  function selectDashboardTab(name) {
    const allowed = new Set(["responses", "columns", "sections"]);
    const tab = allowed.has(name) ? name : "responses";
    activeTab = tab;
    document.querySelectorAll(".panel-tabs .tab-btn").forEach((btn) => {
      const on = (btn.dataset.tab || "") === tab;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    const pr = document.getElementById("panel-responses");
    const pc = document.getElementById("panel-columns");
    const ps = document.getElementById("panel-sections");
    if (pr) pr.classList.toggle("is-active", tab === "responses");
    if (pc) pc.classList.toggle("is-active", tab === "columns");
    if (ps) ps.classList.toggle("is-active", tab === "sections");
    document.querySelectorAll("[data-tab-hint]").forEach((p) => {
      const on = (p.getAttribute("data-tab-hint") || "") === tab;
      p.classList.toggle("is-active", on);
    });
  }

  function bindTabs() {
    const tabs = document.querySelectorAll(".panel-tabs .tab-btn");
    tabs.forEach((btn) => {
      btn.addEventListener("click", () => selectDashboardTab(btn.dataset.tab || "responses"));
    });
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
      const sid = row._id == null ? "" : String(row._id);
      if (sid) tr.dataset.submissionId = sid;
      for (const key of cols) {
        const td = document.createElement("td");
        if (key === "_resume") {
          const files = Array.isArray(row[key]) ? row[key] : [];
          if (!files.length) {
            const dash = document.createElement("span");
            dash.className = "muted";
            dash.textContent = "—";
            td.appendChild(dash);
          } else {
            const wrap = document.createElement("div");
            wrap.className = "resume-cell";
            for (const f of files) {
              const name = f && f.name != null ? String(f.name) : "file";
              const viewUrl = f && f.view_url != null ? String(f.view_url) : "";
              const downloadUrl = f && f.download_url != null ? String(f.download_url) : viewUrl;
              const line = document.createElement("div");
              line.className = "resume-file";
              const nm = document.createElement("span");
              nm.className = "resume-name";
              nm.textContent = name;
              const links = document.createElement("span");
              links.className = "resume-links";
              const aView = document.createElement("a");
              aView.className = "resume-link";
              aView.href = viewUrl;
              aView.target = "_blank";
              aView.rel = "noopener noreferrer";
              aView.textContent = "View";
              const sep = document.createElement("span");
              sep.className = "resume-sep";
              sep.setAttribute("aria-hidden", "true");
              sep.textContent = "·";
              const aDl = document.createElement("a");
              aDl.className = "resume-link";
              aDl.href = downloadUrl;
              aDl.target = "_blank";
              aDl.rel = "noopener noreferrer";
              aDl.textContent = "Download";
              links.appendChild(aView);
              links.appendChild(sep);
              links.appendChild(aDl);
              line.appendChild(nm);
              line.appendChild(links);
              wrap.appendChild(line);
            }
            td.appendChild(wrap);
          }
        } else if (key === "_dept_ui") {
          const wrap = document.createElement("div");
          wrap.className = "note-editor";
          const input = document.createElement("input");
          input.type = "text";
          input.className = "note-input";
          input.setAttribute("autocomplete", "off");
          input.setAttribute("aria-label", "Department");
          input.value = row[key] == null ? "" : String(row[key]);
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "dashboard-field-save";
          btn.dataset.saveKind = "department";
          btn.textContent = "Save";
          wrap.appendChild(input);
          wrap.appendChild(btn);
          td.appendChild(wrap);
        } else if (key === "_note_ui") {
          const wrap = document.createElement("div");
          wrap.className = "note-editor";
          const input = document.createElement("input");
          input.type = "text";
          input.className = "note-input";
          input.setAttribute("autocomplete", "off");
          input.setAttribute("aria-label", "Note");
          input.value = row[key] == null ? "" : String(row[key]);
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "dashboard-field-save";
          btn.dataset.saveKind = "note";
          btn.textContent = "Save";
          wrap.appendChild(input);
          wrap.appendChild(btn);
          td.appendChild(wrap);
        } else {
          td.textContent = row[key] == null ? "" : String(row[key]);
        }
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  }

  function installDashboardFieldSaveDelegation() {
    const root = document.getElementById("panel-responses");
    if (!root || root.dataset.fieldSaveBound === "1") return;
    root.dataset.fieldSaveBound = "1";
    root.addEventListener("click", async (ev) => {
      const btn = ev.target.closest(".dashboard-field-save");
      if (!btn) return;
      const cfg = window.__NOTE_POST__;
      if (!cfg || !cfg.token) return;
      const kind = btn.dataset.saveKind;
      if (kind === "note" && !cfg.notes) return;
      if (kind === "department" && !cfg.department) return;
      const wrap = btn.closest(".note-editor");
      const tr = btn.closest("tr");
      const input = wrap?.querySelector(".note-input");
      const submissionId = tr?.dataset?.submissionId;
      if (!input || !submissionId) return;
      btn.disabled = true;
      const text = input.value;
      const path =
        kind === "department"
          ? `/api/submissions/${encodeURIComponent(submissionId)}/department`
          : `/api/submissions/${encodeURIComponent(submissionId)}/notes`;
      const label = kind === "department" ? "department" : "note";
      try {
        const res = await fetch(path, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${cfg.token}`,
          },
          body: JSON.stringify({ text }),
        });
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(errText || res.statusText);
        }
        input.classList.add("note-saved");
        setTimeout(() => input.classList.remove("note-saved"), 1400);
      } catch (e) {
        window.alert(`Could not save ${label}: ${e && e.message ? e.message : String(e)}`);
      } finally {
        btn.disabled = false;
      }
    });
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
    renderFormColumns(document.getElementById("live-columns-tbody"), data.form_columns);
    renderSections(document.getElementById("live-section-tbody"), data.form_sections);
    selectDashboardTab(activeTab);
  }

  bindTabs();
  installDashboardFieldSaveDelegation();

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
