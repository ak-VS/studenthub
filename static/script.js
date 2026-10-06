/* ---------- Theme (day / night) ---------- */

const THEME_KEY = "studenthub-theme";

function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

window.__charts = [];

function applyChartTheme() {
    if (!window.Chart) return;
    Chart.defaults.color = cssVar("--muted");
    Chart.defaults.borderColor = cssVar("--border");
    Chart.defaults.font.family = '"Plus Jakarta Sans", system-ui, sans-serif';
}

function registerChart(chart) {
    window.__charts.push(chart);
    return chart;
}

function setTheme(theme) {
    const root = document.documentElement;
    root.classList.add("theme-anim");
    root.setAttribute("data-theme", theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) {}

    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#0a0920" : "#f3f2fb");

    applyChartTheme();
    window.__charts.forEach(c => c.update());
    setTimeout(() => root.classList.remove("theme-anim"), 400);
}

document.querySelectorAll("[data-theme-toggle]").forEach(btn => {
    btn.addEventListener("click", () => {
        const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        setTheme(next);
    });
});

/* ---------- Mobile sidebar ---------- */

const sidebar = document.getElementById("sidebar");
const scrim = document.getElementById("scrim");
const menuBtn = document.getElementById("menuBtn");

function toggleSidebar(open) {
    if (!sidebar) return;
    sidebar.classList.toggle("open", open);
    if (scrim) scrim.classList.toggle("show", open);
}

if (menuBtn) menuBtn.addEventListener("click", () => toggleSidebar(true));
if (scrim) scrim.addEventListener("click", () => toggleSidebar(false));

/* ---------- Page loading feedback ---------- */

const progress = document.getElementById("progress");

function startProgress() {
    if (progress) progress.classList.add("active");
}

document.addEventListener("click", e => {
    const link = e.target.closest("a[href]");
    if (!link || e.defaultPrevented || e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
    if (link.target === "_blank" || link.hasAttribute("download")) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || url.pathname === location.pathname && url.hash) return;
    startProgress();
});

document.addEventListener("submit", e => {
    setTimeout(() => {
        if (e.defaultPrevented) return;
        startProgress();
        const btn = e.target.querySelector('button[type="submit"]');
        if (btn) {
            btn.classList.add("is-loading");
            btn.disabled = true;
        }
    }, 0);
});

window.addEventListener("pageshow", () => {
    if (progress) progress.classList.remove("active");
    document.querySelectorAll(".is-loading").forEach(b => {
        b.classList.remove("is-loading");
        b.disabled = false;
    });
});

/* ---------- Live student search (admin Students page) ---------- */

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
}

async function searchStudentsFromAPI() {
    const search = document.getElementById("apiSearch").value.trim();
    const response = await fetch(`/api/students?search=${encodeURIComponent(search)}`);

    if (!response.ok) {
        alert("Search failed. Please sign in again.");
        return;
    }

    const students = await response.json();
    const resultArea = document.getElementById("apiResults");
    resultArea.innerHTML = "";

    if (students.length === 0) {
        resultArea.innerHTML = '<tr><td colspan="8">No students match that search.</td></tr>';
        return;
    }

    students.forEach(s => {
        const row = document.createElement("tr");
        row.innerHTML = `
            <td>${escapeHtml(s.id)}</td>
            <td>${escapeHtml(s.name)}</td>
            <td>${escapeHtml(s.email)}</td>
            <td>${escapeHtml(s.phone)}</td>
            <td>${escapeHtml(s.gender)}</td>
            <td>${escapeHtml(s.course)}</td>
            <td>${escapeHtml(s.status)}</td>
            <td>
                <a class="view-btn" href="${window.STUDENT_URL}${s.id}">View</a>
                <a class="view-btn muted-btn" href="${window.EDIT_URL}${s.id}">Edit</a>
            </td>`;
        resultArea.appendChild(row);
    });
}

const apiBtn = document.getElementById("apiSearchBtn");
const apiInput = document.getElementById("apiSearch");

if (apiBtn && apiInput) {
    apiBtn.addEventListener("click", searchStudentsFromAPI);
    apiInput.addEventListener("keydown", e => {
        if (e.key === "Enter") searchStudentsFromAPI();
    });
}
