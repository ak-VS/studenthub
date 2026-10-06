// Live student search (admin Students page)

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
        resultArea.innerHTML = '<tr><td colspan="8">No students found.</td></tr>';
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
                <a class="view-btn" href="${window.EDIT_URL}${s.id}">Edit</a>
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
